"""Temporal integrity: how far apart a loop's prices were actually observed.

A scan issues one paced request per (want, chunk), and order books are
disk-cached on top of that, so the edges of a cycle are never seen at the same
moment. These tests pin down that the spread is measured honestly and never
understated — a loop that looks tightly-timed but isn't is exactly the phantom
this number exists to expose.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.client import Offer
from poe2arb.format import fmt_skew
from poe2arb.graph import Edge, build_graph, cycle_skew_s, find_opportunities, price_cycle

T0 = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def ring(stamps: dict[tuple[str, str], float | None]) -> dict:
    """A 3-ring a->b->c->a, each edge stamped at the given offset."""
    rates = {("a", "b"): 2.0, ("b", "c"): 2.0, ("c", "a"): 0.3}
    return {
        pair: Edge(
            src=pair[0], dst=pair[1], rate=rate, raw_rate=rate,
            depth_filled_divines=10.0,
            observed_at=at(stamps[pair]) if stamps.get(pair) is not None else None,
        )
        for pair, rate in rates.items()
    }


class TestCycleSkew:
    def test_spread_is_oldest_to_newest(self):
        edges = ring({("a", "b"): 0, ("b", "c"): 26, ("c", "a"): 130})
        assert price_cycle(edges, ("a", "b", "c")).skew_s == 130.0

    def test_simultaneous_edges_have_no_spread(self):
        edges = ring({("a", "b"): 0, ("b", "c"): 0, ("c", "a"): 0})
        assert price_cycle(edges, ("a", "b", "c")).skew_s == 0.0

    def test_order_of_stamps_does_not_matter(self):
        """It's a span, not a direction — the newest edge can be any hop."""
        first = ring({("a", "b"): 200, ("b", "c"): 0, ("c", "a"): 50})
        second = ring({("a", "b"): 0, ("b", "c"): 50, ("c", "a"): 200})
        assert price_cycle(first, ("a", "b", "c")).skew_s == 200.0
        assert price_cycle(second, ("a", "b", "c")).skew_s == 200.0

    def test_one_unstamped_edge_makes_the_whole_answer_unknown(self):
        """Reporting the spread of the stamped subset would understate it."""
        edges = ring({("a", "b"): 0, ("b", "c"): 26, ("c", "a"): None})
        assert price_cycle(edges, ("a", "b", "c")).skew_s is None

    def test_synthetic_edges_report_nothing_rather_than_zero(self):
        edges = ring({})
        assert price_cycle(edges, ("a", "b", "c")).skew_s is None

    def test_empty_hop_list(self):
        assert cycle_skew_s([]) == 0.0


class TestEdgeStamping:
    def offers(self, stamp: datetime | None) -> list[Offer]:
        return [
            Offer("div", 1.0, "chaos", 9.0, stock=90.0, observed_at=stamp),
            Offer("chaos", 9.0, "div", 0.11, stock=900.0, observed_at=stamp),
        ]

    def test_edge_carries_the_observation_time(self):
        edges = build_graph(
            self.offers(at(42)), {"div": 1.0, "chaos": 1 / 9}, ["div", "chaos"],
            fee_pct=0.0, depth_divines=5.0, bait_filter_ratio=1.5,
        )
        assert edges[("div", "chaos")].observed_at == at(42)

    def test_edge_takes_the_oldest_of_its_offers(self):
        """An edge is only as current as the stalest thing behind it."""
        offers = [
            Offer("div", 1.0, "chaos", 9.0, stock=90.0, observed_at=at(300)),
            Offer("div", 1.0, "chaos", 8.5, stock=90.0, observed_at=at(10)),
        ]
        edges = build_graph(
            offers, {"div": 1.0, "chaos": 1 / 9}, ["div", "chaos"],
            fee_pct=0.0, depth_divines=5.0, bait_filter_ratio=1.5,
        )
        assert edges[("div", "chaos")].observed_at == at(10)

    def test_unstamped_offers_leave_the_edge_unstamped(self):
        edges = build_graph(
            self.offers(None), {"div": 1.0, "chaos": 1 / 9}, ["div", "chaos"],
            fee_pct=0.0, depth_divines=5.0, bait_filter_ratio=1.5,
        )
        assert edges[("div", "chaos")].observed_at is None


class TestSkewIsReportedNotFiltered:
    """Rejecting on skew would discard most real loops — see TODO for the data."""

    def test_a_widely_spread_loop_is_still_reported(self):
        edges = ring({("a", "b"): 0, ("b", "c"): 260, ("c", "a"): 520})
        ops, _ = find_opportunities(edges, max_cycle_len=3, min_profit_pct=3.0)
        assert ops, "a profitable loop must not vanish because it spans a scan"
        assert ops[0].skew_s == 520.0

    def test_the_bellman_ford_route_carries_spread_too(self):
        edges = ring({("a", "b"): 0, ("b", "c"): 26, ("c", "a"): 130})
        _, longer = find_opportunities(edges, max_cycle_len=3, min_profit_pct=99.0)
        assert longer is not None and longer.skew_s == 130.0


class TestCacheStamping:
    """The stamp must say when the book was *fetched*, not when it was read.

    Order books are disk-cached for refresh_minutes, so a scan reusing a cached
    response is working from data that old. Stamping it "now" would report a
    ten-minute-old book as current — the exact lie this field exists to prevent.
    """

    def test_cached_offers_keep_the_original_fetch_time(self, tmp_path):
        from poe2arb.client import GggExchangeClient
        from poe2arb.config import Config

        cfg = Config(cache_dir=tmp_path, refresh_minutes=600)
        client = GggExchangeClient(cfg)
        try:
            # Seed the cache directly, as an earlier scan would have.
            key = "ggg_exchange_T_chaos_divine"
            stored_at = client.cache.store(
                key,
                {"result": {"x": {"listing": {
                    "offers": [{
                        "exchange": {"currency": "divine", "amount": 1},
                        "item": {"currency": "chaos", "amount": 9, "stock": 100},
                    }],
                    "account": {"name": "someone"},
                }}}},
            )
            offers = client.fetch_offers("T", "chaos", ["divine"])
            assert offers, "fixture should parse to at least one offer"
            assert all(o.observed_at == stored_at for o in offers)
        finally:
            client.close()

    def test_a_stale_cache_hit_is_visibly_old(self, tmp_path):
        """The whole point: the stamp exposes age rather than hiding it."""
        from poe2arb.client import GggExchangeClient
        from poe2arb.config import Config

        cfg = Config(cache_dir=tmp_path, refresh_minutes=600)
        client = GggExchangeClient(cfg)
        try:
            key = "ggg_exchange_T_chaos_divine"
            client.cache.store(key, {"result": {"x": {"listing": {
                "offers": [{
                    "exchange": {"currency": "divine", "amount": 1},
                    "item": {"currency": "chaos", "amount": 9, "stock": 100},
                }],
                "account": {"name": "someone"},
            }}}})
            # Rewrite the stored timestamp to look like an old scan.
            import json

            path = tmp_path / (GggExchangeClient(cfg).cache._slug(key) + ".json")
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            old = datetime.now(timezone.utc) - timedelta(minutes=9)
            wrapper["fetched_at"] = old.isoformat()
            path.write_text(json.dumps(wrapper), encoding="utf-8")

            offers = client.fetch_offers("T", "chaos", ["divine"])
            age = (datetime.now(timezone.utc) - offers[0].observed_at).total_seconds()
            assert age > 8 * 60
        finally:
            client.close()


class TestHistoryRoundTrip:
    """Skew is only useful if it survives the restart that shows it to you."""

    def test_edge_stamp_and_skew_come_back(self, tmp_path):
        from poe2arb.graph import Opportunity
        from poe2arb.history import append_scan, read_recent
        from poe2arb.scan import result_from_history_record

        path = tmp_path / "h.jsonl"
        append_scan(
            path, league="T", values={"divine": 1.0}, volumes={"divine": 5.0},
            edges={("a", "b"): Edge("a", "b", 1.1, 1.12, 30.0, observed_at=at(7))},
            opportunities=[Opportunity(("a", "b"), 4.2, 30.0, skew_s=91.0)],
        )
        result = result_from_history_record(read_recent(path, 8)[0], {})
        assert result.edges[("a", "b")].observed_at == at(7)
        assert result.opportunities[0].skew_s == 91.0

    def test_records_written_before_this_existed_still_load(self, tmp_path):
        """v0.2.5 and earlier wrote neither field; they must not become errors."""
        import json

        from poe2arb.scan import result_from_history_record

        record = {
            "ts": T0.isoformat(),
            "league": "T",
            "ninja_values_divine": {"divine": 1.0},
            "ninja_volumes_divine": {"divine": 5.0},
            "book_edges": [{"src": "a", "dst": "b", "raw_rate": 1.1,
                            "effective_rate": 1.08, "depth_divines": 30.0}],
            "opportunities": [{"cycle": ["a", "b"], "profit_pct": 4.2,
                               "min_depth_divines": 30.0}],
        }
        result = result_from_history_record(json.loads(json.dumps(record)), {})
        assert result.edges[("a", "b")].observed_at is None
        assert result.opportunities[0].skew_s is None

    def test_garbage_stamp_is_ignored_not_fatal(self, tmp_path):
        from poe2arb.scan import result_from_history_record

        record = {
            "ts": T0.isoformat(),
            "book_edges": [{"src": "a", "dst": "b", "raw_rate": 1.1,
                            "effective_rate": 1.08, "depth_divines": 30.0,
                            "observed_at": "last tuesday"}],
            "opportunities": [{"cycle": ["a", "b"], "profit_pct": 4.2,
                               "min_depth_divines": 30.0, "skew_s": "soon"}],
        }
        result = result_from_history_record(record, {})
        assert result.edges[("a", "b")].observed_at is None
        assert result.opportunities[0].skew_s is None


class TestFormatting:
    def test_unknown(self):
        assert fmt_skew(None) == "—"

    def test_seconds(self):
        assert fmt_skew(52.0) == "52s"

    def test_minutes_and_seconds(self):
        assert fmt_skew(234.0) == "3m 54s"

    def test_exact_minute(self):
        assert fmt_skew(120.0) == "2m 00s"

    def test_zero(self):
        assert fmt_skew(0.0) == "0s"
