"""Scan orchestration: ninja values -> node selection -> GGG books -> cycles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .client import PRIMARY, GggExchangeClient, NinjaClient, NinjaOverview, Offer
from .config import Config
from .graph import Edge, Opportunity, build_graph, find_opportunities
from .history import append_scan

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    league: str
    overview: NinjaOverview
    nodes: list[str]
    edges: dict[tuple[str, str], Edge]
    opportunities: list[Opportunity]
    # A profitable loop Bellman-Ford found outside the reported window — longer
    # than max_cycle_len, or below the profit threshold. None when there's
    # nothing beyond what `opportunities` already shows.
    longer_cycle: Opportunity | None = None

    @property
    def longer_cycle_hint(self) -> bool:
        return self.longer_cycle is not None


def select_nodes(overview: NinjaOverview, cfg: Config) -> list[str]:
    """Top-N currencies by daily volume, above the liquidity floor and not excluded.

    The primary unit (divine) is always included — it's the denominator every
    value is quoted in, so excluding it would leave nothing to price against.
    """
    excluded = {c.strip().lower() for c in cfg.exclude_currencies if c.strip()}
    cap = cfg.max_currency_value_divines

    def keep(cid: str) -> bool:
        if cid == PRIMARY or cid in excluded:
            return False
        if overview.volumes.get(cid, 0.0) < cfg.liquidity_floor_divines:
            return False
        if cap > 0 and overview.values.get(cid, 0.0) > cap:
            return False
        return True

    liquid = [cid for cid in overview.volumes if keep(cid)]
    liquid.sort(key=lambda cid: overview.volumes[cid], reverse=True)
    if excluded:
        log.debug("excluded currencies: %s", ", ".join(sorted(excluded)))
    return [PRIMARY] + liquid[: cfg.max_currencies - 1]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_books(
    ggg: GggExchangeClient,
    league: str,
    nodes: list[str],
    cfg: Config,
    progress: Callable[[int, int], None] | None = None,
) -> list[Offer]:
    requests = [
        (want, chunk)
        for want in nodes
        for chunk in _chunks([n for n in nodes if n != want], cfg.have_chunk)
    ]
    offers: list[Offer] = []
    for i, (want, chunk) in enumerate(requests, 1):
        offers.extend(ggg.fetch_offers(league, want, chunk))
        if progress is not None:
            progress(i, len(requests))
    return offers


def run_scan(
    cfg: Config,
    *,
    log_history: bool = True,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ScanResult:
    """Run one full scan. Raises ScanCancelled if should_cancel() goes true."""
    ninja = NinjaClient(cfg)
    ggg = GggExchangeClient(cfg, should_cancel)
    try:
        league = cfg.league or ninja.current_league()
        overview = ninja.overview(league)
        nodes = select_nodes(overview, cfg)
        log.info("scanning %d currencies in %s: %s", len(nodes), league, ", ".join(nodes))
        offers = fetch_books(ggg, league, nodes, cfg, progress)
        edges = build_graph(
            offers,
            overview.values,
            nodes,
            fee_pct=cfg.fee_pct,
            depth_divines=cfg.depth_divines,
            bait_filter_ratio=cfg.bait_filter_ratio,
            min_accounts=cfg.min_accounts,
        )
        ops, longer = find_opportunities(
            edges,
            max_cycle_len=cfg.max_cycle_len,
            min_profit_pct=cfg.profit_threshold_pct,
        )
        if log_history:
            assert cfg.history_path is not None
            append_scan(
                cfg.history_path,
                league=league,
                values=overview.values,
                volumes=overview.volumes,
                edges=edges,
                opportunities=ops,
                longer_cycle=longer,
                retention_days=cfg.history_retention_days,
            )
        return ScanResult(
            league=league, overview=overview, nodes=nodes, edges=edges,
            opportunities=ops, longer_cycle=longer,
        )
    finally:
        ninja.close()
        ggg.close()


def result_from_history_record(record: dict, names: dict[str, str]) -> ScanResult:
    """Rebuild a ScanResult from a logged scan, for repopulating the UI.

    History stores currency ids but not display names — those come from
    poe.ninja separately, so callers pass whatever they have and can rebuild
    with better names once the currency list arrives.
    """
    values = {k: float(v) for k, v in record.get("ninja_values_divine", {}).items()}
    volumes = {k: float(v) for k, v in record.get("ninja_volumes_divine", {}).items()}
    overview = NinjaOverview(
        league=record.get("league", "?"),
        fetched_at=datetime.fromisoformat(record["ts"]),
        values=values,
        volumes=volumes,
        names={cid: names.get(cid, cid) for cid in values},
    )
    edges: dict[tuple[str, str], Edge] = {}
    for e in record.get("book_edges", []):
        try:
            edge = Edge(
                src=e["src"],
                dst=e["dst"],
                rate=float(e["effective_rate"]),
                raw_rate=float(e["raw_rate"]),
                depth_filled_divines=float(e["depth_divines"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        edges[(edge.src, edge.dst)] = edge
    ops: list[Opportunity] = []
    for o in record.get("opportunities", []):
        try:
            ops.append(
                Opportunity(
                    cycle=tuple(o["cycle"]),
                    profit_pct=float(o["profit_pct"]),
                    min_depth_divines=float(o["min_depth_divines"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    ops.sort(key=lambda op: op.profit_pct, reverse=True)
    nodes = sorted({n for pair in edges for n in pair})
    longer = record.get("longer_cycle")
    try:
        restored = (
            Opportunity(
                cycle=tuple(longer["cycle"]),
                profit_pct=float(longer["profit_pct"]),
                min_depth_divines=float(longer["min_depth_divines"]),
            )
            if longer
            else None
        )
    except (KeyError, TypeError, ValueError):
        restored = None
    return ScanResult(
        league=overview.league,
        overview=overview,
        nodes=nodes,
        edges=edges,
        opportunities=ops,
        longer_cycle=restored,
    )
