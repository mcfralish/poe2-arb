"""Append-only JSONL scan history.

One record per scan, including the raw rates snapshot (not just detected
cycles) so a later trend-analysis phase has full data to work from.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .graph import Edge, Opportunity


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
