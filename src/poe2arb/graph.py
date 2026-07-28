"""Directed exchange graph + arbitrage cycle detection.

Edge A->B answers: "if I pay 1 A into the order book right now, how many B do I
actually receive?" — priced by walking the book to a configurable fill depth
(marginal rate, not top-of-book, which is bait-listing territory), then applying
a per-hop safety margin (see Config.safety_margin_pct — not a fee).

Detection runs two ways and cross-checks:
  1. Bellman-Ford on -log(rate) weights: a negative cycle == a profitable loop.
  2. Brute-force enumeration of all 3- and 4-cycles (node count is small).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from itertools import permutations

from .client import Offer


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    rate: float       # dst per 1 src after the safety margin
    raw_rate: float   # marginal book rate, before the margin
    depth_filled_divines: float  # book depth actually available at <= raw_rate
    # When the order book behind this edge was fetched. None means unknown
    # (synthetic edges in tests, or history written before this was recorded).
    observed_at: datetime | None = None


@dataclass(frozen=True)
class Opportunity:
    cycle: tuple[str, ...]   # e.g. ("exalted", "chaos", "divine") — closes back to first
    profit_pct: float        # (product of effective rates - 1) * 100
    min_depth_divines: float  # bottleneck edge depth — max size this loop supports
    # Seconds between the oldest and newest edge in the loop. A scan issues one
    # paced request per (want, chunk), so a loop's edges are never observed
    # simultaneously — this says how far from simultaneous they were. None when
    # any edge lacks a timestamp.
    skew_s: float | None = None

    @property
    def key(self) -> tuple[str, ...]:
        return self.cycle


def effective_rate(
    offers: list[Offer],
    *,
    fair_rate: float | None,
    depth_divines: float,
    get_value_divines: float,
    bait_filter_ratio: float,
    min_accounts: int = 1,
) -> tuple[float, float] | None:
    """Marginal rate to fill `depth_divines` of value from an order book.

    offers: all offers for one directed pair (pay X -> get Y).
    fair_rate: consensus rate (poe.ninja) used to discard bait listings that
        are implausibly better than fair. None disables the filter.
    get_value_divines: divine value of 1 unit of the get-currency, to convert
        stock into fill depth.
    min_accounts: keep walking the book until the fill spans at least this many
        distinct lister accounts — one account posting a huge fake wall at a
        too-good rate (price-fixing bait) then can't set the rate on its own.
    Returns (marginal_rate, depth_filled_divines), or None if the book can't
    fill the requested depth (illiquid edge — dropped from the graph).
    """
    usable = [
        o
        for o in offers
        if o.stock > 0
        and not (fair_rate is not None and o.rate > fair_rate * bait_filter_ratio)
    ]
    usable.sort(key=lambda o: o.rate, reverse=True)  # best rate first
    filled = 0.0
    accounts: set[str | None] = set()
    for o in usable:
        filled += o.stock * get_value_divines
        accounts.add(o.account)
        if filled >= depth_divines and len(accounts) >= min_accounts:
            return o.rate, filled
    return None  # book exhausted before reaching target depth


def build_graph(
    offers: list[Offer],
    values: dict[str, float],
    nodes: list[str],
    *,
    margin_pct: float,
    depth_divines: float,
    bait_filter_ratio: float,
    min_accounts: int = 1,
) -> dict[tuple[str, str], Edge]:
    """Build directed edges between `nodes` from raw order-book offers."""
    node_set = set(nodes)
    by_pair: dict[tuple[str, str], list[Offer]] = {}
    for o in offers:
        if o.pay_currency in node_set and o.get_currency in node_set:
            by_pair.setdefault((o.pay_currency, o.get_currency), []).append(o)

    haircut = 1.0 - margin_pct / 100.0
    edges: dict[tuple[str, str], Edge] = {}
    for (src, dst), pair_offers in by_pair.items():
        src_v, dst_v = values.get(src), values.get(dst)
        if not src_v or not dst_v:
            continue
        fair = src_v / dst_v  # consensus dst per src
        priced = effective_rate(
            pair_offers,
            fair_rate=fair,
            depth_divines=depth_divines,
            get_value_divines=dst_v,
            bait_filter_ratio=bait_filter_ratio,
            min_accounts=min_accounts,
        )
        if priced is None:
            continue
        raw_rate, depth = priced
        # The oldest stamp among the offers, not the newest: an edge is only as
        # current as the stalest thing it was built from.
        stamps = [o.observed_at for o in pair_offers if o.observed_at is not None]
        edges[(src, dst)] = Edge(
            src=src, dst=dst, rate=raw_rate * haircut, raw_rate=raw_rate,
            depth_filled_divines=depth,
            observed_at=min(stamps) if stamps else None,
        )
    return edges


def _canonical(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate so the lexicographically smallest node comes first (dedup rotations)."""
    i = cycle.index(min(cycle))
    return cycle[i:] + cycle[:i]


def cycle_skew_s(hops: list[Edge]) -> float | None:
    """Seconds between the oldest and newest edge in a loop.

    None if any hop is unstamped: a partial answer here would understate the
    spread, which is the one direction that matters — a loop that looks
    tightly-timed but isn't is exactly the phantom this number exists to expose.
    """
    stamps = [e.observed_at for e in hops]
    if not stamps:
        return 0.0  # no hops, nothing to be spread apart
    if any(s is None for s in stamps):
        return None
    return (max(stamps) - min(stamps)).total_seconds()


def price_cycle(
    edges: dict[tuple[str, str], Edge], cycle: tuple[str, ...]
) -> Opportunity | None:
    """Cost out one closed loop. None if any hop has no edge."""
    product = 1.0
    min_depth = math.inf
    hops: list[Edge] = []
    for i, src in enumerate(cycle):
        edge = edges.get((src, cycle[(i + 1) % len(cycle)]))
        if edge is None:
            return None
        hops.append(edge)
        product *= edge.rate
        min_depth = min(min_depth, edge.depth_filled_divines)
    return Opportunity(
        cycle=cycle,
        profit_pct=(product - 1.0) * 100.0,
        min_depth_divines=min_depth,
        skew_s=cycle_skew_s(hops),
    )


def brute_force_cycles(
    edges: dict[tuple[str, str], Edge],
    *,
    max_len: int,
    min_profit_pct: float,
) -> list[Opportunity]:
    """Enumerate all simple 2..max_len cycles; report those above the threshold.

    2-cycles are included deliberately: a "crossed book" on a single pair
    (A->B->A multiplying above 1 despite the margin) is the most common real
    arbitrage, and Bellman-Ford would flag it anyway.
    """
    nodes = sorted({n for e in edges for n in e})
    found: list[Opportunity] = []
    for length in range(2, max_len + 1):
        for combo in permutations(nodes, length):
            if combo != _canonical(combo):
                continue  # each rotation class visited exactly once
            op = price_cycle(edges, combo)
            if op is not None and op.profit_pct >= min_profit_pct:
                found.append(op)
    return sorted(found, key=lambda op: op.profit_pct, reverse=True)


# Slack on the distance comparison. Rates are floats put through a logarithm,
# so an exactly-break-even loop can land a hair below zero; without this the
# detector reports arbitrage in a perfectly consistent market.
_EPS = 1e-12


def find_negative_cycle(edges: dict[tuple[str, str], Edge]) -> tuple[str, ...] | None:
    """One profitable cycle of any length, or None if the market is consistent.

    Runs on -log(rate) weights from a virtual source connected to every node,
    so disconnected components are covered: a loop multiplying above 1 is a
    negative-weight cycle, and vice versa.

    Unlike brute force this is O(V*E) regardless of loop length, but it finds
    *a* cycle rather than the best one — which is exactly what's wanted for the
    "there's something out past your search window" hint.
    """
    nodes = sorted({n for e in edges for n in e})
    if not nodes:
        return None
    dist = {n: 0.0 for n in nodes}  # virtual source: dist 0 to all
    pred: dict[str, str | None] = {n: None for n in nodes}
    weighted = [(src, dst, -math.log(e.rate)) for (src, dst), e in edges.items() if e.rate > 0]

    relaxed: str | None = None
    for _ in range(len(nodes)):
        relaxed = None
        for src, dst, w in weighted:
            if dist[src] + w < dist[dst] - _EPS:
                dist[dst] = dist[src] + w
                pred[dst] = src
                relaxed = dst
        if relaxed is None:
            return None  # settled early: no negative cycle
    # Still relaxing after |V| passes, so `relaxed` sits on or downstream of a
    # negative cycle. Walking back |V| predecessors is guaranteed to land
    # inside the cycle itself rather than on the tail leading into it.
    node = relaxed
    for _ in range(len(nodes)):
        node = pred[node]
        if node is None:
            return None  # predecessor chain broken; nothing safe to report
    cycle = [node]
    walk = pred[node]
    while walk is not None and walk != node:
        cycle.append(walk)
        walk = pred[walk]
    if walk is None:
        return None
    cycle.reverse()  # predecessors walk backwards; report in travel order
    return _canonical(tuple(cycle))


def bellman_ford_has_negative_cycle(edges: dict[tuple[str, str], Edge]) -> bool:
    """True iff any profitable cycle (of any length) exists."""
    return find_negative_cycle(edges) is not None


def find_opportunities(
    edges: dict[tuple[str, str], Edge],
    *,
    max_cycle_len: int,
    min_profit_pct: float,
) -> tuple[list[Opportunity], Opportunity | None]:
    """Returns (ranked opportunities, longer_cycle).

    longer_cycle is set when Bellman-Ford finds a profitable cycle but brute
    force reported nothing above threshold within max_cycle_len — i.e. the
    profit lives in a longer loop, or below the reporting threshold. It carries
    the actual route so the user can judge it, rather than just asserting that
    something is out there.
    """
    ops = brute_force_cycles(edges, max_len=max_cycle_len, min_profit_pct=min_profit_pct)
    if ops:
        return ops, None
    cycle = find_negative_cycle(edges)
    return ops, price_cycle(edges, cycle) if cycle is not None else None
