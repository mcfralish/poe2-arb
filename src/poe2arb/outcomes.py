"""What happened after each whisper — the only way the ranking improves.

Every threshold in `listings.py` currently rests on 14 whispers and two fills.
That was enough to establish direction (deep discounts don't fill) and nowhere
near enough to fit a curve. This module records one row per attempt, with the
features that plausibly predict a fill — gap, listing age, AFK, price band,
denomination — so the thresholds can eventually come from data instead of from
a hunch.

Two design choices worth keeping:

- **An attempt is logged when the whisper is copied, not when it succeeds.**
  Recording only successes would produce a file in which everything filled.
  The unanswered ones are the whole signal.
- **Outcomes are corrections to an existing row, appended rather than edited.**
  The file stays append-only (cheap, crash-safe, same shape as scan history) and
  the reader folds later verdicts onto earlier attempts by id. Amendments — the
  quantity actually bought, when it differs from the quantity whispered for —
  work the same way, so the original ask is never overwritten.

Every attempt also carries the **session** it belongs to and the **league** it
was made in. Neither is derivable afterwards: sessions are a fact about how the
app was driven, and league names rotate, so a log spanning two of them silently
mixes two different economies.
"""

from __future__ import annotations

import json
import math
import os
import logging
import statistics
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path


log = logging.getLogger(__name__)


class Outcome(Enum):
    """What came of a whisper.

    `SOLD` and the silent verdicts are deliberately distinct even though both
    mean "no trade". A seller who answers to say it's gone was reachable and the
    listing was stale; silence may mean either. Collapsing them would hide which
    of those two problems freshness filtering actually solves.

    **`NO_REPLY` is a legacy value and is never written any more.** Up to 0.7.0
    it was both what the five-minute timer wrote and what the user pressed, and
    those are different facts: the timer knows only that the deadline passed —
    which on 2026-08-01 it wrote three and a half minutes *after* a trade had
    completed — while the user pressing a button knows *why* there was no trade.
    So the timer now writes `EXPIRED` and the buttons are `AFK` and `OFFLINE`,
    the two reasons the maintainer ever actually pressed it. The member stays
    because `outcomes.jsonl` returns `no_reply` records forever; same constraint
    as `bands.symbol_for_name`.
    """

    PENDING = "pending"      # whisper copied, nothing reported back yet
    FILLED = "filled"        # trade completed
    SOLD = "sold"            # seller replied: already gone
    NO_REPLY = "no_reply"    # legacy: written by <=0.7.0, never written now
    DECLINED = "declined"    # seller replied and refused the listed price
    EXPIRED = "expired"      # the timer gave up; nothing is claimed about why
    AFK = "afk"              # GGG's auto-reply came back, or they were away
    OFFLINE = "offline"      # the game said the character is not online

    @property
    def is_resolved(self) -> bool:
        return self is not Outcome.PENDING

    @property
    def is_success(self) -> bool:
        return self is Outcome.FILLED

    @property
    def is_silence(self) -> bool:
        """No answer came back, whatever the app decided to call it.

        The three-way split is for measuring *why* a whisper goes unanswered;
        anything asking "did they answer at all" wants this, and must keep
        matching `NO_REPLY` for records written before the split.
        """
        return self in (
            Outcome.NO_REPLY, Outcome.EXPIRED, Outcome.AFK, Outcome.OFFLINE
        )


# What each verdict is called on screen. One map, because the Opportunities,
# Results and Trends tabs all name the same verdicts and had drifted into two
# private copies of this dict already. Title Case throughout, matching the rest
# of the user-facing text — the enum's own lowercase values are what goes in the
# log and must not be shown.
LABELS = {
    Outcome.PENDING: "Waiting",
    Outcome.FILLED: "Traded",
    Outcome.SOLD: "Already Sold",
    Outcome.NO_REPLY: "No Reply",
    Outcome.DECLINED: "Refused",
    Outcome.EXPIRED: "Expired",
    Outcome.AFK: "AFK",
    Outcome.OFFLINE: "Offline",
}

# Why each is written, for the button and the cell that carries it.
TIPS = {
    Outcome.FILLED: "The trade went through.",
    Outcome.SOLD: "They replied to say it's gone.",
    Outcome.DECLINED: "They replied but wouldn't honour the listed price.",
    Outcome.NO_REPLY: "Recorded before 0.8.0, when the timeout and 'they never "
                      "answered' were the same verdict.",
    Outcome.EXPIRED: "Nobody said what happened before the timer ran out. Not a "
                     "claim that the seller stayed silent — pin a row to stop "
                     "its clock.",
    Outcome.AFK: "They were away — the game's auto-reply came back, or nothing did.",
    Outcome.OFFLINE: "The game said that character isn't online.",
}


def label_for(outcome: Outcome) -> str:
    return LABELS.get(outcome, outcome.value)


@dataclass(frozen=True)
class Attempt:
    """One whisper, and what became of it."""

    id: str
    ts: datetime
    item_id: str
    item_name: str
    account: str
    character: str | None
    pay_currency: str
    unit_price_divines: float
    ce_divines: float
    gap: float
    band: str
    lots: int
    units: float
    cost_divines: float
    expected_profit_divines: float
    listing_age_s: float | None
    afk: bool
    # How many the seller advertised. Without it there is no way to tell a
    # whole-lot ask from an affordable fraction of one after the fact, which is
    # exactly the comparison "do partial asks get answered?" needs. Absent
    # before 2026-08-02; TODO claimed the log could already answer that question
    # and it could not.
    stock: float | None = None
    # How old the CE reference price was when the whisper went out. The pricing
    # error is the reference *moving* (~±6% on liquid pairs, far worse on thin
    # ones), and freshness is the only surviving hypothesis for it — untestable
    # without dating the number each attempt was priced against.
    ce_age_s: float | None = None
    outcome: Outcome = Outcome.PENDING
    resolved_at: datetime | None = None
    # What the trade actually cleared, when the user tells us. Left None on a
    # fill we weren't given a figure for, which is not the same as zero.
    actual_profit_divines: float | None = None
    # Total paid in the seller's own currency — the figure that went into the
    # whisper. `cost_divines` is the same money in the unit the maths runs in.
    pay_units: float = 0.0
    pay_currency_total: str | None = None
    # Which run of the app this whisper belongs to, and which league it was made
    # in. None on records written before 0.7.0.
    session_id: str | None = None
    league: str | None = None
    # What the resale was costed against: the divine worth of one unit of the
    # settlement currency, and its name. Written from 0.8.0 on and None before
    # it — the settlement currency used to be recoverable from nothing, so an
    # amendment to a past trade could not re-apply the rounding floor that
    # decided its profit. See `plan_correction`.
    sale_unit_divines: float | None = None
    settle_currency: str | None = None
    # True once the trade has been corrected after the fact — the seller had
    # fewer than they advertised, the buyer could only afford part of it, or the
    # price was counteroffered.
    amended: bool = False
    # What was originally asked for, kept when `amended`. A correction that
    # erased the ask would hide how often sellers list stock they don't have —
    # or, for the price, how often one is negotiated (1 fill in 36, measured
    # 2026-08-01).
    asked_units: float | None = None
    asked_pay_units: float | None = None
    asked_cost_divines: float | None = None


# --- retention -------------------------------------------------------------
# Moved here from history.py when the scan log went: this is now the only
# append-only file the app keeps.

# Don't bother rewriting the file below this size. A record is a few KB, so
# this is thousands of attempts — and it keeps the common
# case (append, do nothing else) free.
PRUNE_MIN_BYTES = 2 * 1024 * 1024


def _timestamp(line: str) -> datetime | None:
    try:
        return datetime.fromisoformat(json.loads(line)["ts"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _oldest_timestamp(path: Path) -> datetime | None:
    """Timestamp of the first readable record, without loading the file."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                ts = _timestamp(line)
                if ts is not None:
                    return ts
    except OSError:
        return None
    return None


def prune(path: Path, retention_days: float, *, min_bytes: int = PRUNE_MIN_BYTES) -> int:
    """Drop records older than `retention_days`. Returns how many went.

    Skipped entirely unless the file is both large enough to be worth rewriting
    and actually holds something expired — so the usual case costs one stat and
    one short read rather than a full rewrite on every scan.

    Best-effort, like the rest of this module: history is a convenience, and
    failing to prune it must never take the app down. The rewrite goes through
    a temporary file so an interruption can't truncate real data.
    """
    if retention_days <= 0:
        return 0
    try:
        if path.stat().st_size < min_bytes:
            return 0
    except OSError:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    oldest = _oldest_timestamp(path)
    if oldest is None or oldest >= cutoff:
        return 0

    tmp = path.with_suffix(path.suffix + ".tmp")
    dropped = 0
    try:
        with open(path, encoding="utf-8") as src, open(tmp, "w", encoding="utf-8") as dst:
            for line in src:
                if not line.strip():
                    continue
                ts = _timestamp(line)
                # Unreadable lines go too — read_recent already skips them, so
                # keeping them only grows the file no one can use.
                if ts is None or ts < cutoff:
                    dropped += 1
                    continue
                dst.write(line if line.endswith("\n") else line + "\n")
        os.replace(tmp, path)
    except OSError:
        log.warning("could not prune history at %s", path, exc_info=True)
        tmp.unlink(missing_ok=True)
        return 0
    log.info("pruned %d history record(s) older than %g days", dropped, retention_days)
    return dropped


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def record_attempt(
    path: Path,
    candidate,
    *,
    session_id: str | None = None,
    league: str | None = None,
    ce_age_s: float | None = None,
    retention_days: float = 0.0,
) -> str:
    """Log a copied whisper as a pending attempt. Returns its id."""
    listing = candidate.listing
    attempt_id = _new_id()
    row = {
        "kind": "attempt",
        "id": attempt_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "league": league,
        "item_id": listing.item_id,
        "item_name": candidate.item_name,
        "account": listing.account,
        "character": listing.character,
        "pay_currency": listing.pay_currency,
        "unit_price_divines": candidate.unit_price_divines,
        "ce_divines": candidate.ce_divines,
        "gap": candidate.gap,
        "band": candidate.band.value,
        "lots": candidate.plan.lots,
        "units": candidate.plan.units,
        "pay_units": candidate.pay_total,
        "cost_divines": candidate.plan.cost_divines,
        "expected_profit_divines": candidate.profit_divines,
        # Recorded so a later correction can re-apply the same rounding floor.
        # Proceeds round down to a whole unit of the settlement currency, and
        # without this an amended quantity could only be re-costed by guessing
        # at the denomination that decided the original figure.
        "sale_unit_divines": candidate.plan.sale_unit_divines,
        "settle_currency": candidate.settle_currency,
        "listing_age_s": listing.age_s(),
        "afk": listing.afk,
        # What the seller advertised, against `units` asked for: the two differ
        # whenever the bankroll could only afford part of the listing.
        "stock": listing.stock,
        # Age of the CE reference price this was costed against.
        "ce_age_s": ce_age_s,
        "outcome": Outcome.PENDING.value,
    }
    _append(path, row, retention_days)
    return attempt_id


def record_amendment(
    path: Path, attempt_id: str, candidate, *, retention_days: float = 0.0
) -> None:
    """Correct an attempt to the trade that actually happened.

    Appended, never edited over the top: the difference between what was asked
    for and what was available is itself a measurement — the field test found
    sellers advertising two Omens and holding one — and an amendment that
    overwrote the ask would destroy it. `read_attempts` folds these on and keeps
    the originals in `asked_units`, `asked_pay_units` and `asked_cost_divines`.

    Takes a live candidate, so it is for a trade still in the queue.
    `record_correction` writes the same record for a row that only exists in the
    log, where the listing behind it is long gone.
    """
    record_correction(
        path,
        attempt_id,
        lots=candidate.plan.lots,
        units=candidate.plan.units,
        pay_units=candidate.pay_total,
        cost_divines=candidate.plan.cost_divines,
        expected_profit_divines=candidate.profit_divines,
        retention_days=retention_days,
    )


def record_correction(
    path: Path,
    attempt_id: str,
    *,
    lots: int | None = None,
    units: float | None = None,
    pay_units: float | None = None,
    cost_divines: float | None = None,
    expected_profit_divines: float | None = None,
    retention_days: float = 0.0,
) -> None:
    """Amend a logged attempt by value rather than from a candidate.

    The route back to a trade whose listing no longer exists — which is every
    trade older than the sweep that found it, including the biggest one the
    project has made. Fields left None are omitted from the record and therefore
    left alone by `read_attempts`, so a price correction does not have to invent
    a quantity to go with it.
    """
    row = {
        "kind": "amend",
        "id": attempt_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    for key, value in (
        ("lots", lots),
        ("units", units),
        ("pay_units", pay_units),
        ("cost_divines", cost_divines),
        ("expected_profit_divines", expected_profit_divines),
    ):
        if value is not None:
            row[key] = value
    _append(path, row, retention_days)


@dataclass(frozen=True)
class Correction:
    """What a logged attempt becomes once the user corrects it."""

    lots: int
    units: float
    pay_units: float
    cost_divines: float
    expected_profit_divines: float


def plan_correction(
    attempt: "Attempt",
    *,
    units: float | None = None,
    cost_divines: float | None = None,
) -> Correction:
    """Re-cost a logged attempt at a corrected quantity or price.

    The log-only counterpart to `listings.replan_units` and `listings.repriced`.
    It cannot call either, because a logged attempt has no listing behind it —
    all that survives of the trade is the numbers in this row.

    Three rules, each of which is the honest reading of what the user is saying:

    - **Changing the quantity leaves the price per item alone.** "They only had
      three" does not change what three cost each, so the totals scale. The
      quantity itself snaps to a whole lot, because the price only divides that
      finely (`listings.smallest_lot`); `lots` is recorded per attempt, so the
      step is recoverable.
    - **Changing the total leaves the quantity alone.** That is the counteroffer
      case, and the seller's own currency moves with the divine figure.
    - **Proceeds are re-floored, not scaled.** Partial currency cannot be
      traded, so proceeds round down to a whole unit of the settlement currency.
      When the quantity is untouched the original proceeds are exact and are
      reused (`profit + cost`); when it changes they are recomputed against
      `sale_unit_divines`. On records written before 0.8.0 that field is missing
      and the floor falls back to a whole divine — the pessimistic reading, and
      the same default `listings.plan_trade` takes, because understating profit
      is the safe direction to be wrong in.
    """
    old_units = attempt.units
    new_units = old_units if units is None else max(0.0, float(units))

    # Snap to a whole lot, where the log recorded enough to know what one is.
    per_lot = old_units / attempt.lots if attempt.lots else 0.0
    if per_lot > 0:
        lots = max(1, round(new_units / per_lot))
        new_units = lots * per_lot
    else:
        lots = attempt.lots

    if cost_divines is None:
        scale = new_units / old_units if old_units else 1.0
        new_cost = attempt.cost_divines * scale
        new_pay = attempt.pay_units * scale
    else:
        new_cost = max(0.0, float(cost_divines))
        ratio = new_cost / attempt.cost_divines if attempt.cost_divines else 0.0
        new_pay = attempt.pay_units * ratio

    proceeds = _proceeds(attempt, new_units)
    return Correction(
        lots=lots,
        units=new_units,
        pay_units=new_pay,
        cost_divines=new_cost,
        expected_profit_divines=proceeds - new_cost,
    )


def _proceeds(attempt: "Attempt", units: float) -> float:
    """Divines the resale realises for `units`, after the rounding floor."""
    original = attempt.expected_profit_divines + attempt.cost_divines
    if units == attempt.units or attempt.ce_divines <= 0:
        return original
    unit = attempt.sale_unit_divines or 1.0
    if unit <= 0:
        unit = 1.0
    return math.floor(units * attempt.ce_divines / unit) * unit


def record_outcome(
    path: Path,
    attempt_id: str,
    outcome: Outcome,
    *,
    actual_profit_divines: float | None = None,
    retention_days: float = 0.0,
) -> None:
    """Append a verdict for an earlier attempt."""
    row = {
        "kind": "outcome",
        "id": attempt_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome.value,
    }
    if actual_profit_divines is not None:
        row["actual_profit_divines"] = actual_profit_divines
    _append(path, row, retention_days)


def _append(path: Path, row: dict, retention_days: float) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        # Losing a log line must never cost the user a trade they're mid-way
        # through. Warn and carry on.
        log.warning("could not record trade outcome to %s", path, exc_info=True)
        return
    prune(path, retention_days)


def _opt_float(value: object) -> float | None:
    """A number that is allowed to be absent. None is not zero here."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_attempts(path: Path) -> list[Attempt]:
    """Every attempt, with later verdicts folded in, oldest first.

    Unreadable lines and verdicts for unknown ids are skipped rather than
    raised: this file is diagnostic, and a truncated write must not stop the
    app from opening.
    """
    if not path.exists():
        return []
    attempts: dict[str, dict] = {}
    order: list[str] = []
    verdicts: list[dict] = []
    amendments: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") == "attempt" and row.get("id"):
                    if row["id"] not in attempts:
                        order.append(row["id"])
                    attempts[row["id"]] = row
                elif row.get("kind") == "outcome" and row.get("id"):
                    verdicts.append(row)
                elif row.get("kind") == "amend" and row.get("id"):
                    amendments.append(row)
    except OSError:
        return []

    # Amendments before verdicts, because a verdict can carry a realised profit
    # and must not be undone by a quantity correction written earlier.
    for a in amendments:
        row = attempts.get(a["id"])
        if row is None:
            continue
        # Only the *first* amendment writes these, so a row corrected twice
        # still reports what was originally whispered rather than what the
        # previous correction left behind.
        for kept, live in (
            ("asked_units", "units"),
            ("asked_pay_units", "pay_units"),
            ("asked_cost_divines", "cost_divines"),
        ):
            row.setdefault(kept, row.get(live))
        row["amended"] = True
        for key in ("lots", "units", "pay_units", "cost_divines",
                    "expected_profit_divines"):
            if key in a:
                row[key] = a[key]

    for v in verdicts:
        row = attempts.get(v["id"])
        if row is None:
            continue
        row["outcome"] = v.get("outcome", Outcome.PENDING.value)
        row["resolved_at"] = v.get("ts")
        if "actual_profit_divines" in v:
            row["actual_profit_divines"] = v["actual_profit_divines"]

    out: list[Attempt] = []
    for attempt_id in order:
        row = attempts[attempt_id]
        ts = _parse_ts(row.get("ts"))
        if ts is None:
            continue
        try:
            outcome = Outcome(row.get("outcome", "pending"))
        except ValueError:
            outcome = Outcome.PENDING
        out.append(
            Attempt(
                id=attempt_id,
                ts=ts,
                item_id=row.get("item_id", "?"),
                item_name=row.get("item_name") or row.get("item_id", "?"),
                account=row.get("account", "?"),
                character=row.get("character"),
                pay_currency=row.get("pay_currency", "divine"),
                unit_price_divines=float(row.get("unit_price_divines") or 0.0),
                ce_divines=float(row.get("ce_divines") or 0.0),
                gap=float(row.get("gap") or 0.0),
                band=row.get("band", "?"),
                lots=int(row.get("lots") or 0),
                units=float(row.get("units") or 0.0),
                cost_divines=float(row.get("cost_divines") or 0.0),
                expected_profit_divines=float(row.get("expected_profit_divines") or 0.0),
                listing_age_s=(
                    float(row["listing_age_s"]) if row.get("listing_age_s") is not None else None
                ),
                afk=bool(row.get("afk")),
                stock=_opt_float(row.get("stock")),
                ce_age_s=_opt_float(row.get("ce_age_s")),
                outcome=outcome,
                resolved_at=_parse_ts(row.get("resolved_at")),
                actual_profit_divines=(
                    float(row["actual_profit_divines"])
                    if row.get("actual_profit_divines") is not None
                    else None
                ),
                pay_units=float(row.get("pay_units") or 0.0),
                session_id=row.get("session_id") or None,
                league=row.get("league") or None,
                sale_unit_divines=_opt_float(row.get("sale_unit_divines")),
                settle_currency=row.get("settle_currency") or None,
                amended=bool(row.get("amended")),
                asked_units=_opt_float(row.get("asked_units")),
                asked_pay_units=_opt_float(row.get("asked_pay_units")),
                asked_cost_divines=_opt_float(row.get("asked_cost_divines")),
            )
        )
    return out


@dataclass(frozen=True)
class Session:
    """One run of the trade loop, as reconstructed from the log."""

    id: str | None
    started_at: datetime
    ended_at: datetime
    league: str | None
    attempts: int
    fills: int
    realised_divines: float

    @property
    def label(self) -> str:
        """What the session picker shows. Local time — the user's own clock."""
        start = self.started_at.astimezone()
        if self.id is None:
            return f"Before sessions were recorded ({self.attempts} whispers)"
        span = self.ended_at.astimezone()
        clock = start.strftime("%d %b %H:%M")
        if span - start >= timedelta(minutes=1):
            clock += f"–{span.strftime('%H:%M')}"
        return f"{clock}  ·  {self.fills}/{self.attempts} traded"


def sessions(attempts: list[Attempt]) -> list[Session]:
    """Every session in the log, newest first.

    Grouped by the id the app stamped on each attempt rather than by a gap in
    the timestamps: a session is defined by the queue draining, which is not
    something a clock can see — two sweeps twenty minutes apart with a whisper
    outstanding across them are one session, and two a minute apart with nothing
    in between are two.
    """
    groups: dict[str | None, list[Attempt]] = {}
    for a in attempts:
        groups.setdefault(a.session_id, []).append(a)
    out = []
    for session_id, rows in groups.items():
        fills = [a for a in rows if a.outcome.is_success]
        out.append(
            Session(
                id=session_id,
                started_at=min(a.ts for a in rows),
                ended_at=max(a.ts for a in rows),
                league=next((a.league for a in rows if a.league), None),
                attempts=len(rows),
                fills=len(fills),
                realised_divines=sum(
                    a.actual_profit_divines
                    if a.actual_profit_divines is not None
                    else a.expected_profit_divines
                    for a in fills
                ),
            )
        )
    return sorted(out, key=lambda s: s.started_at, reverse=True)


def leagues(attempts: list[Attempt]) -> list[str]:
    """Every league the log has whispers from, most recent first."""
    seen: dict[str, datetime] = {}
    for a in attempts:
        if a.league:
            seen[a.league] = max(seen.get(a.league, a.ts), a.ts)
    return sorted(seen, key=lambda name: seen[name], reverse=True)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

# Below this, a fill rate is a coincidence rather than a measurement. Two fills
# out of fourteen was enough to see a direction and not enough to set a
# threshold; the UI says "not enough data yet" until a bucket clears this.
MIN_SAMPLES = 10


@dataclass(frozen=True)
class Bucket:
    label: str
    attempts: int
    fills: int
    realised_divines: float

    @property
    def fill_rate(self) -> float | None:
        """None, not zero, when there is too little data to claim a rate."""
        if self.attempts < MIN_SAMPLES:
            return None
        return self.fills / self.attempts

    @property
    def value_per_attempt(self) -> float | None:
        """Divines actually earned per whisper sent — the number that matters.

        A high fill rate on trades worth 0.3 divines is worse than a low one on
        trades worth 5. This is what a ranking should ultimately maximise.
        """
        if self.attempts < MIN_SAMPLES:
            return None
        return self.realised_divines / self.attempts


@dataclass(frozen=True)
class OutcomeSummary:
    total: int
    resolved: int
    fills: int
    realised_divines: float
    by_gap: list[Bucket]
    by_age: list[Bucket]
    by_presence: list[Bucket]

    @property
    def fill_rate(self) -> float | None:
        if self.resolved < MIN_SAMPLES:
            return None
        return self.fills / self.resolved

    @property
    def has_enough_data(self) -> bool:
        return self.resolved >= MIN_SAMPLES


GAP_BUCKETS = [
    (1.0, 1.1, "1.0-1.1x"),
    (1.1, 1.25, "1.1-1.25x"),
    (1.25, 1.5, "1.25-1.5x"),
    (1.5, 3.0, "1.5-3x"),
    (3.0, float("inf"), "over 3x"),
]

AGE_BUCKETS = [
    (0.0, 3600.0, "under 1h"),
    (3600.0, 6 * 3600.0, "1-6h"),
    (6 * 3600.0, 24 * 3600.0, "6-24h"),
    (24 * 3600.0, float("inf"), "over a day"),
]


def _bucket(attempts: list[Attempt], label: str) -> Bucket:
    resolved = [a for a in attempts if a.outcome.is_resolved]
    fills = [a for a in resolved if a.outcome.is_success]
    realised = sum(
        a.actual_profit_divines
        if a.actual_profit_divines is not None
        else a.expected_profit_divines
        for a in fills
    )
    return Bucket(label=label, attempts=len(resolved), fills=len(fills), realised_divines=realised)


def summarise(attempts: list[Attempt]) -> OutcomeSummary:
    """Fill rates by the features that might predict them."""
    resolved = [a for a in attempts if a.outcome.is_resolved]
    fills = [a for a in resolved if a.outcome.is_success]
    realised = sum(
        a.actual_profit_divines
        if a.actual_profit_divines is not None
        else a.expected_profit_divines
        for a in fills
    )

    by_gap = [
        _bucket([a for a in attempts if lo <= a.gap < hi], label)
        for lo, hi, label in GAP_BUCKETS
    ]
    by_age = [
        _bucket(
            [a for a in attempts if a.listing_age_s is not None and lo <= a.listing_age_s < hi],
            label,
        )
        for lo, hi, label in AGE_BUCKETS
    ]
    by_presence = [
        _bucket([a for a in attempts if not a.afk], "seller active"),
        _bucket([a for a in attempts if a.afk], "seller AFK"),
    ]
    return OutcomeSummary(
        total=len(attempts),
        resolved=len(resolved),
        fills=len(fills),
        realised_divines=realised,
        by_gap=[b for b in by_gap if b.attempts],
        by_age=[b for b in by_age if b.attempts],
        by_presence=[b for b in by_presence if b.attempts],
    )


def suggested_gap_band(summary: OutcomeSummary) -> tuple[float, float] | None:
    """The gap range earning the most per whisper, once there's data to say.

    Returns None until enough buckets clear MIN_SAMPLES. Deliberately advisory:
    it is shown to the user rather than applied, because a band fitted to one
    league's data on one account is not a fact about the game.
    """
    usable = [
        (b, b.value_per_attempt)
        for b in summary.by_gap
        if b.value_per_attempt is not None
    ]
    if len(usable) < 2:
        return None
    best_label = max(usable, key=lambda pair: pair[1])[0].label
    for lo, hi, label in GAP_BUCKETS:
        if label == best_label:
            return (lo, hi if hi != float("inf") else 99.0)
    return None
