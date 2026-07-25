"""Scan orchestration: ninja values -> node selection -> GGG books -> cycles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    longer_cycle_hint: bool


def select_nodes(overview: NinjaOverview, cfg: Config) -> list[str]:
    """Top-N currencies by daily volume above the liquidity floor."""
    liquid = [
        cid
        for cid, vol in overview.volumes.items()
        if cid != PRIMARY and vol >= cfg.liquidity_floor_divines
    ]
    liquid.sort(key=lambda cid: overview.volumes[cid], reverse=True)
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
) -> ScanResult:
    ninja = NinjaClient(cfg)
    ggg = GggExchangeClient(cfg)
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
        ops, hint = find_opportunities(
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
            )
        return ScanResult(
            league=league, overview=overview, nodes=nodes, edges=edges,
            opportunities=ops, longer_cycle_hint=hint,
        )
    finally:
        ninja.close()
        ggg.close()
