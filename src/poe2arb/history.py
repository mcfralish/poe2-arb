"""Append-only JSONL scan history.

One record per scan, including the raw rates snapshot (not just detected
cycles) so a later trend-analysis phase has full data to work from.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .graph import Edge, Opportunity


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


def append_scan(
    path: Path,
    *,
    league: str,
    values: dict[str, float],
    volumes: dict[str, float],
    edges: dict[tuple[str, str], Edge],
    opportunities: list[Opportunity],
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
            }
            for e in edges.values()
        ],
        "opportunities": [
            {
                "cycle": list(op.cycle),
                "profit_pct": op.profit_pct,
                "min_depth_divines": op.min_depth_divines,
            }
            for op in opportunities
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
