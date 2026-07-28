"""Reading the banked scan history back as evidence.

Storing every scan's raw rates was justified by a promise: that it would later
support "this loop appeared six times this week" rather than only "here is what
is true right now". This module is that reader.

It also exists to keep the node-selection work honest. Choosing which currencies
to track is a scoring problem, and any scoring function is a *hypothesis* about
where arbitrage lives. `currency_stats` measures the thing that matters — how
often a tracked currency actually turned up in a profitable loop — so a new
scorer can be compared against plain top-N-by-volume instead of merely feeling
more sophisticated.

Everything here is a pure function over history records, so it is testable
without a network, a league, or a GUI.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .history import read_recent

# A loop seen once is an anecdote. This is the default bar for calling something
# recurring, used for the "recurring" flag rather than for filtering anything
# out — a one-off 40% loop is still worth seeing.
RECURRING_THRESHOLD = 3


@dataclass(frozen=True)
class LoopStats:
    """One arbitrage loop's track record across many scans."""

    cycle: tuple[str, ...]
    times_seen: int
    scans_covered: int          # scans that could have seen it (all of them)
    first_seen: datetime
    last_seen: datetime
    best_profit_pct: float
    median_profit_pct: float
    median_depth_divines: float
    median_skew_s: float | None

    @property
    def recurring(self) -> bool:
        return self.times_seen >= RECURRING_THRESHOLD

    @property
    def frequency_pct(self) -> float:
        """Share of scans in which this loop was above threshold."""
        if not self.scans_covered:
            return 0.0
        return 100.0 * self.times_seen / self.scans_covered


@dataclass(frozen=True)
class CurrencyStats:
    """How much a tracked currency actually earned its slot in the graph.

    `scans_tracked` counts scans where the currency was a graph node at all,
    which is what makes `hit_rate` fair: a currency added to the graph
    yesterday isn't penalised against one tracked for a month.
    """

    item_id: str
    scans_tracked: int
    loops_seen: int
    best_profit_pct: float

    @property
    def hit_rate_pct(self) -> float:
        """Share of its tracked scans in which it appeared in a loop."""
        if not self.scans_tracked:
            return 0.0
        return 100.0 * self.loops_seen / self.scans_tracked


@dataclass(frozen=True)
class HistorySummary:
    scans: int
    window_days: float
    first_scan: datetime | None
    last_scan: datetime | None
    scans_with_opportunity: int
    loops: list[LoopStats]
    currencies: list[CurrencyStats]

    @property
    def hit_rate_pct(self) -> float:
        """Share of scans that found anything at all."""
        if not self.scans:
            return 0.0
        return 100.0 * self.scans_with_opportunity / self.scans

    @property
    def is_empty(self) -> bool:
        return self.scans == 0


def _stamp(record: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(record["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def summarise(records: list[dict], *, window_days: float = 0.0) -> HistorySummary:
    """Roll a list of history records up into loop and currency statistics."""
    stamps: list[datetime] = []
    # cycle -> accumulated observations
    seen: dict[tuple[str, ...], dict] = {}
    tracked: dict[str, int] = {}     # item -> scans where it was a graph node
    appeared: dict[str, int] = {}    # item -> scans where it was in a loop
    best_for: dict[str, float] = {}
    scans_with_opportunity = 0

    for record in records:
        ts = _stamp(record)
        if ts is None:
            continue  # a record with no timestamp can't be placed in time
        stamps.append(ts)

        # Graph membership is derivable from the edges that were priced, which
        # is more honest than trusting a separately-stored node list.
        nodes = {n for e in record.get("book_edges", []) for n in (e.get("src"), e.get("dst"))}
        nodes.discard(None)
        for node in nodes:
            tracked[node] = tracked.get(node, 0) + 1

        ops = record.get("opportunities") or []
        if ops:
            scans_with_opportunity += 1
        in_this_scan: set[str] = set()
        for op in ops:
            try:
                cycle = tuple(op["cycle"])
                profit = float(op["profit_pct"])
                depth = float(op["min_depth_divines"])
            except (KeyError, TypeError, ValueError):
                continue
            skew = op.get("skew_s")
            entry = seen.setdefault(
                cycle,
                {"first": ts, "last": ts, "profits": [], "depths": [], "skews": []},
            )
            entry["first"] = min(entry["first"], ts)
            entry["last"] = max(entry["last"], ts)
            entry["profits"].append(profit)
            entry["depths"].append(depth)
            if isinstance(skew, (int, float)):
                entry["skews"].append(float(skew))
            for item in cycle:
                in_this_scan.add(item)
                best_for[item] = max(best_for.get(item, profit), profit)
        for item in in_this_scan:
            appeared[item] = appeared.get(item, 0) + 1

    total = len(stamps)
    loops = [
        LoopStats(
            cycle=cycle,
            times_seen=len(entry["profits"]),
            scans_covered=total,
            first_seen=entry["first"],
            last_seen=entry["last"],
            best_profit_pct=max(entry["profits"]),
            median_profit_pct=_median(entry["profits"]),
            median_depth_divines=_median(entry["depths"]),
            median_skew_s=_median(entry["skews"]) if entry["skews"] else None,
        )
        for cycle, entry in seen.items()
    ]
    # The cycle breaks ties. Without it, rows with equal counts fall back to
    # dict insertion order, which traces back to a set of node ids — and string
    # hashing is randomised per process, so the table would reshuffle on every
    # launch for no visible reason.
    loops.sort(key=lambda s: (-s.times_seen, -s.best_profit_pct, s.cycle))

    currencies = [
        CurrencyStats(
            item_id=item,
            scans_tracked=count,
            loops_seen=appeared.get(item, 0),
            best_profit_pct=best_for.get(item, 0.0),
        )
        for item, count in tracked.items()
    ]
    # Worst first would bury the interesting rows; the ones earning their slot
    # lead, and the dead weight sorts to the bottom where it's easy to spot.
    # Id breaks ties for the same reason as above.
    currencies.sort(key=lambda s: (-s.hit_rate_pct, -s.best_profit_pct, s.item_id))

    return HistorySummary(
        scans=total,
        window_days=window_days,
        first_scan=min(stamps) if stamps else None,
        last_scan=max(stamps) if stamps else None,
        scans_with_opportunity=scans_with_opportunity,
        loops=loops,
        currencies=currencies,
    )


def summarise_file(path: Path, window_days: float) -> HistorySummary:
    """Read history from disk and summarise the last `window_days` of it.

    `window_days <= 0` means everything on disk.
    """
    hours = window_days * 24 if window_days > 0 else 24 * 365 * 100
    return summarise(read_recent(Path(path), hours), window_days=window_days)


# Below this many scans, "never appeared in a loop" says nothing — the market
# simply may not have offered one yet.
DEAD_WEIGHT_MIN_SCANS = 20


def judgeable(summary: HistorySummary, *, min_scans: int = DEAD_WEIGHT_MIN_SCANS) -> list[CurrencyStats]:
    """Currencies tracked long enough for their hit rate to mean anything."""
    return [c for c in summary.currencies if c.scans_tracked >= min_scans]


def dead_weight(
    summary: HistorySummary, *, min_scans: int = DEAD_WEIGHT_MIN_SCANS
) -> list[CurrencyStats]:
    """Currencies tracked often enough to judge that never produced a loop.

    These are the slots a better node-selection scorer should be reclaiming.
    `min_scans` guards against condemning something added to the graph an hour
    ago — with too small a sample, "never" means nothing.
    """
    return [c for c in judgeable(summary, min_scans=min_scans) if c.loops_seen == 0]


def window_choices() -> tuple[tuple[str, float], ...]:
    """(label, days) options for a history window selector."""
    return (("Last 24 hours", 1.0), ("Last 7 days", 7.0),
            ("Last 30 days", 30.0), ("Everything", 0.0))
