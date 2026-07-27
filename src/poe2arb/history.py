"""Append-only JSONL scan history.

One record per scan, including the raw rates snapshot (not just detected
cycles) so a later trend-analysis phase has full data to work from.

Append-only, but not unbounded: a watch loop writes a record every few minutes
forever, so old records are pruned once the file grows past a size worth
rewriting. See `prune`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .graph import Edge, Opportunity

log = logging.getLogger(__name__)

# Don't bother rewriting the file below this size. A record is a few KB, so
# this is thousands of scans — weeks of watching — and it keeps the common
# case (append, do nothing else) free.
PRUNE_MIN_BYTES = 2 * 1024 * 1024


def read_recent(path: Path, max_age_hours: float) -> list[dict]:
    """Scan records from the last `max_age_hours`, oldest first.

    Used to repopulate the app's log and tables on startup so a restart
    doesn't look like a blank slate. Best-effort: a corrupt line is skipped
    rather than allowed to break launch.
    """
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    records: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = datetime.fromisoformat(record["ts"])
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
                if ts >= cutoff:
                    records.append(record)
    except OSError:
        return []
    records.sort(key=lambda r: r["ts"])
    return records


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


def append_scan(
    path: Path,
    *,
    league: str,
    values: dict[str, float],
    volumes: dict[str, float],
    edges: dict[tuple[str, str], Edge],
    opportunities: list[Opportunity],
    longer_cycle: Opportunity | None = None,
    retention_days: float = 0.0,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "ninja_values_divine": values,
        "ninja_volumes_divine": volumes,
        "book_edges": [
            {
                "src": e.src,
                "dst": e.dst,
                "raw_rate": e.raw_rate,
                "effective_rate": e.rate,
                "depth_divines": e.depth_filled_divines,
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
            }
            for e in edges.values()
        ],
        "opportunities": [
            {
                "cycle": list(op.cycle),
                "profit_pct": op.profit_pct,
                "min_depth_divines": op.min_depth_divines,
                "skew_s": op.skew_s,
            }
            for op in opportunities
        ],
    }
    if longer_cycle is not None:
        record["longer_cycle"] = {
            "cycle": list(longer_cycle.cycle),
            "profit_pct": longer_cycle.profit_pct,
            "min_depth_divines": longer_cycle.min_depth_divines,
            "skew_s": longer_cycle.skew_s,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    prune(path, retention_days)
