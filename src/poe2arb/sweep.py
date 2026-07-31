"""Cross-venue sweep: pick items, fetch their live listings, rank candidates.

One request per item, so the cost is linear rather than the n^2/have_chunk the
cycle scanner pays. That is what makes a wide sweep affordable — and what makes
a *narrow* one preferable anyway, since listings churn faster than a broad sweep
can complete. See TODO.md, "Which items to sweep".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from typing import Callable

from .client import GggExchangeClient, ScanCancelled
from .config import Config
from .listings import Candidate, Listing, build_candidates, rank_candidates
from .scout import CeSnapshot, ScoutClient

log = logging.getLogger(__name__)


def resolve_league(cfg: Config) -> str:
    """The league to sweep: the configured one, else poe.ninja's current league.

    **Never falls back to a hardcoded name.** This used to read
    `cfg.league or "Standard"`, which meant a default install swept the permanent
    league while the user played the temp one. That is not a cosmetic mismatch:
    measured 2026-07-30, Standard prices Omen of Whittling at 25,761 exalted
    against Runes of Aldur's 4,518 — **5.7x** — so every listing looks like a
    windfall and no whisper can ever be answered, because the sellers are in a
    different league to the player.

    `NinjaClient.leagues` is disk-cached, so this costs a request once per TTL
    and nothing thereafter. If poe.ninja is unreachable we raise rather than
    guess: sweeping the wrong league is worse than not sweeping.
    """
    if cfg.league:
        return cfg.league
    from .client import NinjaClient

    client = NinjaClient(cfg)
    try:
        league = client.current_league()
    finally:
        client.close()
    log.info("league auto-detected as %r", league)
    return league


@dataclass(frozen=True)
class SweepResult:
    league: str
    started_at: datetime
    finished_at: datetime
    items: list[str]              # what was swept, in request order
    candidates: list[Candidate]   # ranked, best first
    listings_seen: int
    errors: dict[str, str]        # item id -> why it failed, if any did

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


def select_sweep_items(snapshot: CeSnapshot, cfg: Config) -> list[str]:
    """Items worth sweeping, most CE-traded first.

    Two gates, both structural rather than tuned:

    - **Exit liquidity.** An underpriced listing is worthless if the Currency
      Exchange won't absorb the item afterwards, so CE traded value is the
      primary filter and the sort key.
    - **The integer floor.** Proceeds are floored to whole divines, so an item
      too cheap to clear ~2 divines in a lot cannot profit at the quantities
      this venue actually carries.

    Deliberately *not* filtered by an upper value bound. Both expensive items in
    the category spot-check came back empty, which suggests one, but six samples
    is not enough to cut a band — sweeping them costs a few minutes and measured
    yield can prune them later.
    """
    excluded = {c.strip().lower() for c in cfg.exclude_currencies if c.strip()}
    picked: list[str] = []
    for item in snapshot.by_liquidity():
        if item.item_id in excluded:
            continue
        if item.divines is None or item.divines < cfg.sweep_min_value_divines:
            continue
        if item.value_traded < cfg.sweep_min_ce_traded:
            continue
        picked.append(item.item_id)
        if len(picked) >= cfg.sweep_items:
            break
    return picked


def run_sweep(
    cfg: Config,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_budget: Callable[..., None] | None = None,
    ggg: GggExchangeClient | None = None,
    snapshot: CeSnapshot | None = None,
) -> SweepResult:
    """Sweep the candidate items and return ranked cross-venue candidates.

    Clients are injectable so the whole flow can be exercised without network
    access. A failure on one item is logged and skipped rather than aborting:
    a sweep is a series of independent probes, and losing item 40 of 69 is no
    reason to discard the 39 already priced.
    """
    started = datetime.now(timezone.utc)
    own_ggg = ggg is None
    own_scout = snapshot is None
    ggg = ggg or GggExchangeClient(cfg, should_cancel, on_budget)
    scout: ScoutClient | None = None
    errors: dict[str, str] = {}
    try:
        if snapshot is None:
            scout = ScoutClient(cfg)
            snapshot = scout.snapshot(resolve_league(cfg))
        league = snapshot.league
        items = select_sweep_items(snapshot, cfg)
        log.info(
            "cross-venue sweep: %d items in %s, ~%.0f min at %.0fs/request",
            len(items), league, len(items) * cfg.request_interval_s / 60, cfg.request_interval_s,
        )

        ce_price = {i.item_id: i.divines for i in snapshot.priced() if i.divines}
        names = {i.item_id: i.name for i in snapshot.items.values()}
        # What one unit of the settlement currency is worth. Falls back to
        # divines if the snapshot can't price it — pessimistic, not wrong.
        sale_unit = ce_price.get(cfg.sale_currency) or 1.0
        if cfg.sale_currency != "divine" and sale_unit == 1.0:
            log.warning(
                "no CE price for settlement currency %r — costing sales in "
                "whole divines, which understates profit", cfg.sale_currency,
            )

        listings: list[Listing] = []
        for n, item_id in enumerate(items, 1):
            # Announced before the fetch, not after: the label should name what
            # is being waited on, which is the whole point of watching it.
            if progress is not None:
                progress(n, len(items), names.get(item_id, item_id))
            try:
                listings.extend(ggg.fetch_listings(league, item_id))
            except ScanCancelled:
                raise
            except Exception as e:  # noqa: BLE001 - one bad item must not end the sweep
                log.warning("sweep: %s failed: %s", item_id, e)
                errors[item_id] = str(e)

        candidates = rank_candidates(
            build_candidates(
                listings,
                ce_price,
                names,
                min_gap=cfg.min_gap_ratio,
                max_gap=cfg.max_gap_ratio,
                bankroll=cfg.bankroll(),
                sale_unit_divines=sale_unit,
                settle_currency=cfg.sale_currency,
                min_profit_divines=cfg.min_profit_divines,
            ),
            risk_appetite=cfg.risk_appetite,
        )
        log.info(
            "cross-venue sweep: %d listings -> %d candidates (%d plausible)",
            len(listings), len(candidates),
            sum(1 for c in candidates if c.band.name == "PLAUSIBLE"),
        )
        return SweepResult(
            league=league,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            items=items,
            candidates=candidates,
            listings_seen=len(listings),
            errors=errors,
        )
    finally:
        if own_ggg:
            ggg.close()
        if own_scout and scout is not None:
            scout.close()


class RecheckStatus(Enum):
    LIVE = "live"          # same seller, same price, same or better stock
    REDUCED = "reduced"    # still there, but smaller than planned
    GONE = "gone"          # not in the book any more
    UNKNOWN = "unknown"    # the check itself failed; say so rather than guess


@dataclass(frozen=True)
class RecheckResult:
    status: RecheckStatus
    detail: str
    listing: Listing | None

    @property
    def worth_whispering(self) -> bool:
        """UNKNOWN counts as yes: a failed check is not evidence of absence."""
        return self.status is not RecheckStatus.GONE


def recheck(
    cfg: Config,
    candidate,
    *,
    ggg: GggExchangeClient | None = None,
) -> RecheckResult:
    """Re-fetch one item's book and report whether this exact listing survives.

    One request, immediately before whispering. In the first field test two of
    four attempts failed because the listing was already gone — one seller said
    "already sold", another's listing vanished from the book within minutes — so
    this turns the most common failure into something known before the message
    is sent rather than after.

    Matched on account, price and denomination rather than on a listing id: the
    exchange response carries no identifier stable across fetches, and a seller
    who has re-posted at a different price is not the trade that was planned.
    Deliberately uncached — a cached answer would defeat the entire point.
    """
    own = ggg is None
    ggg = ggg or GggExchangeClient(cfg)
    listing = candidate.listing
    try:
        fresh = ggg.fetch_listings(
            resolve_league(cfg), listing.item_id, use_cache=False
        )
    except ScanCancelled:
        raise
    except Exception as e:  # noqa: BLE001 — a failed check must not block the user
        log.warning("recheck of %s failed: %s", listing.item_id, e)
        return RecheckResult(RecheckStatus.UNKNOWN, str(e), None)
    finally:
        if own:
            ggg.close()

    for other in fresh:
        if other.account != listing.account:
            continue
        if other.pay_currency != listing.pay_currency:
            continue
        if abs(other.price_per_unit - listing.price_per_unit) > 1e-9:
            continue
        if other.stock + 1e-9 < listing.get_amount:
            return RecheckResult(
                RecheckStatus.REDUCED, "less than one lot left", other
            )
        if other.stock + 1e-9 < candidate.plan.units:
            return RecheckResult(
                RecheckStatus.REDUCED,
                f"stock down from {listing.stock:g} to {other.stock:g} — "
                f"ask for less than {candidate.plan.units:g}",
                other,
            )
        return RecheckResult(RecheckStatus.LIVE, "still listed", other)
    return RecheckResult(RecheckStatus.GONE, "no longer listed", None)
