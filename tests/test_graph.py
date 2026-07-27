"""Cycle-detection tests: synthetic graphs with planted cycles + edge pricing."""

from __future__ import annotations

import math

import pytest

from poe2arb.client import Offer
from poe2arb.graph import (
    Edge,
    bellman_ford_has_negative_cycle,
    brute_force_cycles,
    build_graph,
    effective_rate,
    find_negative_cycle,
    find_opportunities,
    price_cycle,
)


def make_edges(rates: dict[tuple[str, str], float], fee_pct: float = 0.0) -> dict:
    """Synthetic edge dict from plain rates, mimicking build_graph's haircut."""
    haircut = 1.0 - fee_pct / 100.0
    return {
        (a, b): Edge(src=a, dst=b, rate=r * haircut, raw_rate=r, depth_filled_divines=10.0)
        for (a, b), r in rates.items()
    }


def consistent_rates(values: dict[str, float]) -> dict[tuple[str, str], float]:
    """All cross-rates derived from one price vector — zero arbitrage by construction."""
    return {
        (a, b): values[a] / values[b]
        for a in values
        for b in values
        if a != b
    }


class TestPlantedCycles:
    def test_planted_3_cycle_detected(self):
        # ex -> chaos -> div -> ex multiplies to 1.10: +10% loop
        rates = consistent_rates({"div": 1.0, "ex": 1 / 400, "chaos": 1 / 9})
        rates[("chaos", "div")] *= 1.10
        edges = make_edges(rates)
        ops = brute_force_cycles(edges, max_len=3, min_profit_pct=3.0)
        assert ops, "planted 3-cycle not found"
        three = [op for op in ops if set(op.cycle) == {"div", "ex", "chaos"}]
        assert len(three) == 1
        assert three[0].profit_pct == pytest.approx(10.0, abs=0.01)
        assert bellman_ford_has_negative_cycle(edges)

    def test_profit_below_fee_haircut_not_reported(self):
        # Gross +4.04% on the 3-loop (2% on each of two edges), but a 1.5%/hop fee
        # across 3 hops (~4.4%) eats it: net = 1.0404 * 0.985^3 ≈ 0.994 -> must NOT
        # be reported at any threshold. Spread across two edges so no single pair's
        # book is crossed (a crossed pair would be a legitimate 2-cycle arb).
        rates = consistent_rates({"div": 1.0, "ex": 1 / 400, "chaos": 1 / 9})
        rates[("ex", "chaos")] *= 1.02
        rates[("chaos", "div")] *= 1.02
        edges = make_edges(rates, fee_pct=1.5)
        ops = brute_force_cycles(edges, max_len=3, min_profit_pct=0.0)
        assert ops == []
        assert not bellman_ford_has_negative_cycle(edges)

    def test_crossed_book_2_cycle_detected(self):
        # One pair whose two directions multiply above 1 even after fees:
        # the classic buy-low/sell-high arb on a single pair.
        rates = consistent_rates({"div": 1.0, "ex": 1 / 400, "chaos": 1 / 9})
        rates[("chaos", "div")] *= 1.08  # 0.985^2 * 1.08 ≈ 1.048
        edges = make_edges(rates, fee_pct=1.5)
        ops = brute_force_cycles(edges, max_len=3, min_profit_pct=3.0)
        assert any(set(op.cycle) == {"chaos", "div"} for op in ops)
        assert bellman_ford_has_negative_cycle(edges)

    def test_planted_4_cycle_detected_only_at_len_4(self):
        values = {"div": 1.0, "ex": 1 / 400, "chaos": 1 / 9, "annul": 0.5}
        rates = {}
        # Only a single directed 4-ring exists — no 3-cycles possible.
        ring = ["div", "ex", "chaos", "annul"]
        for i, a in enumerate(ring):
            b = ring[(i + 1) % 4]
            rates[(a, b)] = values[a] / values[b]
        rates[("annul", "div")] *= 1.08
        edges = make_edges(rates)
        assert brute_force_cycles(edges, max_len=3, min_profit_pct=3.0) == []
        ops = brute_force_cycles(edges, max_len=4, min_profit_pct=3.0)
        assert len(ops) == 1
        assert ops[0].profit_pct == pytest.approx(8.0, abs=0.01)

    def test_consistent_market_has_no_cycles(self):
        values = {"div": 1.0, "ex": 1 / 400, "chaos": 1 / 9, "annul": 0.5, "vaal": 0.02}
        edges = make_edges(consistent_rates(values))
        assert brute_force_cycles(edges, max_len=4, min_profit_pct=0.001) == []
        assert not bellman_ford_has_negative_cycle(edges)

    def test_bellman_ford_agrees_with_brute_force(self):
        # Bellman-Ford flags a profitable loop that brute force misses at max_len=3
        # -> surfaced as the longer_cycle.
        edges = make_edges(self.ring_rates())
        ops, longer = find_opportunities(edges, max_cycle_len=3, min_profit_pct=3.0)
        assert ops == [] and longer is not None
        ops4, longer4 = find_opportunities(edges, max_cycle_len=4, min_profit_pct=3.0)
        assert ops4 and longer4 is None

    @staticmethod
    def ring_rates() -> dict[tuple[str, str], float]:
        """A single directed 4-ring with a +50% edge: no 3-cycle can exist."""
        values = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        ring = ["a", "b", "c", "d"]
        rates = {}
        for i, x in enumerate(ring):
            y = ring[(i + 1) % 4]
            rates[(x, y)] = values[x] / values[y]
        rates[("d", "a")] *= 1.5
        return rates


class TestNegativeCycleRoute:
    """Bellman-Ford must name the loop it found, not just assert one exists."""

    def test_names_the_route_it_found(self):
        edges = make_edges(TestPlantedCycles.ring_rates())
        cycle = find_negative_cycle(edges)
        assert cycle is not None
        assert set(cycle) == {"a", "b", "c", "d"}

    def test_route_is_traversable_in_order(self):
        """Every consecutive pair must be a real edge, closing back to the start."""
        edges = make_edges(TestPlantedCycles.ring_rates())
        cycle = find_negative_cycle(edges)
        for i, src in enumerate(cycle):
            assert (src, cycle[(i + 1) % len(cycle)]) in edges

    def test_route_is_actually_profitable(self):
        edges = make_edges(TestPlantedCycles.ring_rates())
        op = price_cycle(edges, find_negative_cycle(edges))
        assert op.profit_pct == pytest.approx(50.0, abs=0.01)

    def test_longer_cycle_carries_profit_and_depth(self):
        edges = make_edges(TestPlantedCycles.ring_rates())
        _, longer = find_opportunities(edges, max_cycle_len=3, min_profit_pct=3.0)
        assert longer.profit_pct == pytest.approx(50.0, abs=0.01)
        assert longer.min_depth_divines == 10.0

    def test_finds_a_two_cycle_route(self):
        rates = consistent_rates({"div": 1.0, "chaos": 1 / 9})
        rates[("chaos", "div")] *= 1.08
        cycle = find_negative_cycle(make_edges(rates))
        assert set(cycle) == {"chaos", "div"}

    def test_consistent_market_yields_no_route(self):
        edges = make_edges(consistent_rates({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}))
        assert find_negative_cycle(edges) is None

    def test_empty_graph_is_safe(self):
        assert find_negative_cycle({}) is None

    def test_route_reported_below_threshold_too(self):
        """A real but small loop is hidden by the threshold — still worth naming."""
        rates = consistent_rates({"a": 1.0, "b": 2.0, "c": 3.0})
        rates[("c", "a")] *= 1.01  # +1%, under a 3% threshold
        edges = make_edges(rates)
        ops, longer = find_opportunities(edges, max_cycle_len=3, min_profit_pct=3.0)
        assert ops == []
        assert longer is not None and longer.profit_pct == pytest.approx(1.0, abs=0.01)

    def test_disconnected_component_still_searched(self):
        """A virtual source reaches every node, so an isolated loop isn't missed."""
        rates = consistent_rates({"a": 1.0, "b": 2.0})
        rates.update(consistent_rates({"y": 1.0, "z": 5.0}))
        rates[("z", "y")] *= 1.2
        cycle = find_negative_cycle(make_edges(rates))
        assert set(cycle) == {"y", "z"}


class TestPriceCycle:
    def test_missing_hop_is_not_priced(self):
        edges = make_edges({("a", "b"): 2.0})
        assert price_cycle(edges, ("a", "b")) is None  # no b->a edge

    def test_depth_is_the_bottleneck_hop(self):
        edges = {
            ("a", "b"): Edge("a", "b", 2.0, 2.0, depth_filled_divines=50.0),
            ("b", "a"): Edge("b", "a", 0.6, 0.6, depth_filled_divines=7.0),
        }
        assert price_cycle(edges, ("a", "b")).min_depth_divines == 7.0

    def test_rotations_are_deduplicated(self):
        rates = consistent_rates({"a": 1.0, "b": 2.0, "c": 3.0})
        rates[("c", "a")] *= 1.2
        edges = make_edges(rates)
        ops = brute_force_cycles(edges, max_len=3, min_profit_pct=1.0)
        cycles = [op.cycle for op in ops]
        assert len(cycles) == len(set(cycles))
        # a->b->c and b->c->a are the same loop; reverse direction is a different
        # (unprofitable) loop and must not appear.
        assert sum(1 for c in cycles if set(c) == {"a", "b", "c"}) == 1


class TestEffectiveRate:
    def offers(self, specs: list[tuple[float, float]]) -> list[Offer]:
        return [
            Offer(pay_currency="x", pay_amount=1.0, get_currency="y",
                  get_amount=rate, stock=stock)
            for rate, stock in specs
        ]

    def test_marginal_rate_at_depth(self):
        # 2 units at rate 10, 100 units at rate 9; get-value 1 div/unit, depth 5 div
        # -> must walk into the 9s: marginal rate 9.
        rate = effective_rate(
            self.offers([(10.0, 2.0), (9.0, 100.0)]),
            fair_rate=9.5, depth_divines=5.0, get_value_divines=1.0,
            bait_filter_ratio=1.5,
        )
        assert rate is not None
        assert rate[0] == pytest.approx(9.0)

    def test_bait_listings_filtered(self):
        # A 1-divine-per-exalted scam (fair is ~0.00225) must be ignored.
        rate = effective_rate(
            self.offers([(1.0, 31.0), (0.0021, 10000.0)]),
            fair_rate=0.00225, depth_divines=5.0, get_value_divines=1.0,
            bait_filter_ratio=1.5,
        )
        assert rate is not None
        assert rate[0] == pytest.approx(0.0021)

    def test_single_account_fake_wall_cannot_set_rate(self):
        # One account posts a huge wall 8% better than fair (passes a 1.10 bait
        # filter); with min_accounts=2 the walk must continue into the next
        # account's honest offers, whose rate wins.
        offers = [
            Offer("x", 1.0, "y", 9.4, stock=1000.0, account="fixer"),
            Offer("x", 1.0, "y", 8.5, stock=1000.0, account="honest"),
        ]
        rate = effective_rate(
            offers, fair_rate=8.69, depth_divines=5.0, get_value_divines=1.0,
            bait_filter_ratio=1.10, min_accounts=2,
        )
        assert rate is not None
        assert rate[0] == pytest.approx(8.5)
        # Sanity: with min_accounts=1 the wall would have set the phantom rate.
        rate1 = effective_rate(
            offers, fair_rate=8.69, depth_divines=5.0, get_value_divines=1.0,
            bait_filter_ratio=1.10, min_accounts=1,
        )
        assert rate1[0] == pytest.approx(9.4)

    def test_thin_book_returns_none(self):
        rate = effective_rate(
            self.offers([(9.0, 1.0)]),
            fair_rate=9.0, depth_divines=5.0, get_value_divines=1.0,
            bait_filter_ratio=1.5,
        )
        assert rate is None

    def test_zero_stock_ignored(self):
        rate = effective_rate(
            self.offers([(9.0, 0.0)]),
            fair_rate=9.0, depth_divines=1.0, get_value_divines=1.0,
            bait_filter_ratio=1.5,
        )
        assert rate is None


class TestBuildGraph:
    def test_build_graph_applies_haircut_and_drops_thin_pairs(self):
        values = {"div": 1.0, "chaos": 1 / 9}
        offers = [
            Offer("div", 1.0, "chaos", 9.0, stock=90.0),   # liquid: 10 div depth
            Offer("chaos", 9.0, "div", 1.0, stock=1.0),    # thin: 1 div depth
        ]
        edges = build_graph(
            offers, values, ["div", "chaos"],
            fee_pct=2.0, depth_divines=5.0, bait_filter_ratio=1.5,
        )
        assert ("div", "chaos") in edges
        assert ("chaos", "div") not in edges
        e = edges[("div", "chaos")]
        assert e.raw_rate == pytest.approx(9.0)
        assert e.rate == pytest.approx(9.0 * 0.98)
