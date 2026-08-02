"""poe2scout client — Currency Exchange reference prices.

The in-game Currency Exchange is a different market from the Bulk Item Exchange
the GGG trade2 API serves (see TODO.md, "The two markets"). poe2scout publishes
CE snapshot data, which is the only accessible source for what an item is
actually worth on the venue you would sell into.

**Exactly one use of this API is verified.** `item.RelativePrice` divided by
`divine.RelativePrice`, taken from a pair with real traded value, reproduces
in-game ratios to 0.4-4.7% (measured 2026-07-28 against five screenshots).
Nothing else is trustworthy:

- `RelativePrice` is *not* a price in the base currency, whatever the field
  names suggest. Exalted's own `RelativePrice` should be 1.0; the median across
  pairs is 1.185, and gating to high-volume pairs makes it *worse* (1.258). The
  normalisation is unknown, so only same-pair ratios mean anything.
- Thin pairs are noise. A pair with one lifetime trade yields prices off by 25x.
  `MIN_PAIR_VALUE` exists to throw those away, and it is the difference between
  a usable price and a fabricated one.
- There is no bid, no ask and no depth anywhere in this API. It cannot support
  order-book arbitrage, only a reference price to compare listings against.

`value_traded` is used for *ranking only*. Its absolute scale inherits the same
unknown normalisation, but it is the same unit for every item, so "which items
actually trade" is answerable even though "how many divines traded" is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .client import PRIMARY, ClientError, DiskCache, SchemaError, _request_with_backoff
from .config import Config

log = logging.getLogger(__name__)

SCOUT_BASE = "https://api.poe2scout.com"
REALM = "poe2"

# Minimum ValueTraded on *both* sides of a pair before its price is believed.
# Below this the RelativePrice is derived from a handful of trades and is wrong
# by multiples, not percentages.
#
# **This is too low and there is now a measurement saying so.** Astrid's
# Creativity carries ~110k ValueTraded — 110x this floor — and on 2026-08-02 its
# in-game book was **22.2% wide** with poe2scout quoting **+53% above the bid**,
# against ~2% and ±6% on pairs at 1.6M and 10.0M. Both of the project's two known
# real losses are explained by it. Raising this is one candidate fix and a
# ValueTraded-scaled haircut is the other; the haircut is preferred because a
# floor hides listings while a haircut prices them. Do not raise it on a guess —
# the shape needs a second thin reading (n=1 today). See docs/FINDINGS.md, "The
# reference price does not match what a sale realises".
MIN_PAIR_VALUE = 1_000.0


@dataclass(frozen=True)
class CeItem:
    """One item's Currency Exchange standing."""

    item_id: str
    name: str
    category: str
    # Divines per unit, from the item's pair with divine. None when that pair is
    # absent or too thin to believe — the item is then unpriceable, not free.
    divines: float | None
    # Total ValueTraded across every pair this item appears in. Ranking only:
    # comparable between items, not convertible to any real currency amount.
    value_traded: float
    image: str | None = None


@dataclass(frozen=True)
class CeSnapshot:
    league: str
    fetched_at: datetime
    items: dict[str, CeItem]

    def price(self, item_id: str) -> float | None:
        item = self.items.get(item_id)
        return item.divines if item is not None else None

    def priced(self) -> list[CeItem]:
        return [i for i in self.items.values() if i.divines is not None]

    def by_liquidity(self) -> list[CeItem]:
        """Priced items, most-traded first. The sweep order."""
        return sorted(
            self.priced(),
            # item_id breaks ties so the order is stable across processes;
            # Python randomises string hashing, and dict order derived from a
            # set would otherwise reshuffle between runs.
            key=lambda i: (-i.value_traded, i.item_id),
        )


def _side(pair: dict, which: str) -> tuple[dict, dict]:
    return pair[which], pair[f"{which}Data"]


def parse_snapshot_pairs(
    data: list,
    league: str,
    fetched_at: datetime,
    *,
    min_pair_value: float = MIN_PAIR_VALUE,
) -> CeSnapshot:
    """Build divine-denominated CE prices from the SnapshotPairs payload.

    One pass collects total traded value per item (every pair counts, since
    liquidity is a sum), and a second takes the price only from each item's
    pair with divine (the sole verified ratio).
    """
    if not isinstance(data, list):
        raise SchemaError("poe2scout SnapshotPairs did not return a list")

    traded: dict[str, float] = {}
    meta: dict[str, dict] = {}
    prices: dict[str, list[float]] = {}

    for pair in data:
        try:
            one, one_data = _side(pair, "CurrencyOne")
            two, two_data = _side(pair, "CurrencyTwo")
            one_id, two_id = one["ApiId"], two["ApiId"]
        except (KeyError, TypeError):
            continue  # one malformed pair shouldn't lose the whole snapshot
        for item, item_data in ((one, one_data), (two, two_data)):
            item_id = item.get("ApiId")
            if not item_id:
                continue
            traded[item_id] = traded.get(item_id, 0.0) + _num(item_data.get("ValueTraded"))
            meta.setdefault(item_id, item)

        # Price comes only from the pair against divine, and only when both
        # sides have really traded.
        if PRIMARY not in (one_id, two_id) or one_id == two_id:
            continue
        if min(_num(one_data.get("ValueTraded")), _num(two_data.get("ValueTraded"))) < min_pair_value:
            continue
        if one_id == PRIMARY:
            item_id, num, den = two_id, two_data, one_data
        else:
            item_id, num, den = one_id, one_data, two_data
        rel, base = _num(num.get("RelativePrice")), _num(den.get("RelativePrice"))
        if rel <= 0 or base <= 0:
            continue
        prices.setdefault(item_id, []).append(rel / base)

    items: dict[str, CeItem] = {}
    for item_id, info in meta.items():
        seen = prices.get(item_id) or []
        items[item_id] = CeItem(
            item_id=item_id,
            name=info.get("Text") or item_id,
            category=info.get("CategoryApiId") or "",
            # Duplicate pairs do occur in the payload; average rather than
            # letting whichever arrived last win.
            divines=(sum(seen) / len(seen)) if seen else None,
            value_traded=traded.get(item_id, 0.0),
            image=info.get("IconUrl"),
        )
    # Divine prices itself at exactly 1 and never appears as its own pair.
    if PRIMARY in items and items[PRIMARY].divines is None:
        items[PRIMARY] = CeItem(
            item_id=PRIMARY,
            name=items[PRIMARY].name,
            category=items[PRIMARY].category,
            divines=1.0,
            value_traded=items[PRIMARY].value_traded,
            image=items[PRIMARY].image,
        )
    log.info(
        "poe2scout: %d items, %d priced against divine (min pair value %.0f)",
        len(items), sum(1 for i in items.values() if i.divines is not None), min_pair_value,
    )
    return CeSnapshot(league=league, fetched_at=fetched_at, items=items)


def _num(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


class ScoutClient:
    """Fetches the Currency Exchange snapshot. Cached like every other source.

    Not on GGG's rate limiter — a separate host — so this costs nothing against
    the trade API budget. It is still one volunteer-run site, so the cache TTL
    applies and callers should tolerate it being unavailable.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = DiskCache(cfg.cache_dir)
        self._http = httpx.Client(
            headers={"User-Agent": cfg.user_agent}, timeout=60, follow_redirects=True
        )

    def snapshot(self, league: str) -> CeSnapshot:
        key = f"scout_pairs_{league}"
        cached = self.cache.load(key, self.cfg.ce_refresh_minutes * 60)
        if cached:
            data, fetched_at = cached
        else:
            url = f"{SCOUT_BASE}/{REALM}/Leagues/{league}/SnapshotPairs"
            resp = _request_with_backoff(self._http, "GET", url)
            if resp.status_code != 200:
                raise ClientError(
                    f"poe2scout SnapshotPairs returned HTTP {resp.status_code}"
                )
            payload = resp.json()
            # DiskCache stores an object; the endpoint returns a bare list.
            data = {"pairs": payload}
            fetched_at = self.cache.store(key, data)
        pairs = data.get("pairs") if isinstance(data, dict) else data
        try:
            return parse_snapshot_pairs(pairs, league, fetched_at)
        except SchemaError as e:
            import json as _json

            raw = self.cache.dump_bad_response(key, _json.dumps(data))
            raise SchemaError(str(e), raw) from e

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ScoutClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def snapshot_age_s(snapshot: CeSnapshot, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - snapshot.fetched_at).total_seconds()
