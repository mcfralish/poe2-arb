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
  the reader folds later verdicts onto earlier attempts by id.
"""

from __future__ import annotations

import json
import logging
import statistics
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .history import prune

log = logging.getLogger(__name__)


class Outcome(Enum):
    """What came of a whisper.

    `SOLD` and `NO_REPLY` are deliberately distinct even though both mean "no
    trade". A seller who answers to say it's gone was reachable and the listing
    was stale; silence may mean either. Collapsing them would hide which of
    those two problems freshness filtering actually solves.
    """

    PENDING = "pending"      # whisper copied, nothing reported back yet
    FILLED = "filled"        # trade completed
    SOLD = "sold"            # seller replied: already gone
    NO_REPLY = "no_reply"    # no response
    DECLINED = "declined"    # seller replied and refused the listed price

    @property
    def is_resolved(self) -> bool:
        return self is not Outcome.PENDING

    @property
    def is_success(self) -> bool:
        return self is Outcome.FILLED


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
    outcome: Outcome = Outcome.PENDING
    resolved_at: datetime | None = None
    # What the trade actually cleared, when the user tells us. Left None on a
    # fill we weren't given a figure for, which is not the same as zero.
    actual_profit_divines: float | None = None


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def record_attempt(path: Path, candidate, *, retention_days: float = 0.0) -> str:
    """Log a copied whisper as a pending attempt. Returns its id."""
    listing = candidate.listing
    attempt_id = _new_id()
    row = {
        "kind": "attempt",
        "id": attempt_id,
        "ts": datetime.now(timezone.utc).isoformat(),
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
        "cost_divines": candidate.plan.cost_divines,
        "expected_profit_divines": candidate.profit_divines,
        "listing_age_s": listing.age_s(),
        "afk": listing.afk,
        "outcome": Outcome.PENDING.value,
    }
    _append(path, row, retention_days)
    return attempt_id


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
    except OSError:
        return []

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
                outcome=outcome,
                resolved_at=_parse_ts(row.get("resolved_at")),
                actual_profit_divines=(
                    float(row["actual_profit_divines"])
                    if row.get("actual_profit_divines") is not None
                    else None
                ),
            )
        )
    return out


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
