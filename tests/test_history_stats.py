"""Rolling banked scans up into evidence about loops and currencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.history_stats import (
    RECURRING_THRESHOLD,
    dead_weight,
    summarise,
    summarise_file,
)

T0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def scan(
    minutes: float,
    *,
    nodes: tuple[str, ...] = ("divine", "chaos", "exalted"),
    ops: tuple[tuple, ...] = (),
) -> dict:
    """One history record: `nodes` were in the graph, `ops` were found.

    Edges are synthesised as a full mesh so graph membership is derivable the
    same way the reader derives it — from the edges that were actually priced.
    """
    return {
        "ts": (T0 + timedelta(minutes=minutes)).isoformat(),
        "league": "T",
        "book_edges": [
            {"src": a, "dst": b, "raw_rate": 1.0, "effective_rate": 1.0,
             "depth_divines": 10.0}
            for a in nodes for b in nodes if a != b
        ],
        "opportunities": [
            {"cycle": list(cycle), "profit_pct": profit,
             "min_depth_divines": depth, "skew_s": skew}
            for cycle, profit, depth, skew in ops
        ],
    }


class TestLoopStats:
    def test_counts_how_often_a_loop_appeared(self):
        """The headline question: did this happen once, or does it keep happening?"""
        records = [
            scan(0, ops=((("divine", "chaos"), 4.0, 20.0, 60.0),)),
            scan(10),
            scan(20, ops=((("divine", "chaos"), 5.0, 30.0, 90.0),)),
            scan(30, ops=((("divine", "chaos"), 3.0, 10.0, 70.0),)),
        ]
        summary = summarise(records)
        assert len(summary.loops) == 1
        loop = summary.loops[0]
        assert loop.times_seen == 3
        assert loop.scans_covered == 4
        assert loop.frequency_pct == 75.0

    def test_first_and_last_seen_span_the_sightings(self):
        records = [
            scan(0, ops=((("a", "b"), 4.0, 20.0, 60.0),)),
            scan(120, ops=((("a", "b"), 4.0, 20.0, 60.0),)),
        ]
        loop = summarise(records).loops[0]
        assert loop.first_seen == T0
        assert loop.last_seen == T0 + timedelta(minutes=120)

    def test_reports_best_and_typical_profit(self):
        """The best sighting sells the loop; the median says what to expect."""
        records = [
            scan(0, ops=((("a", "b"), 3.0, 10.0, 60.0),)),
            scan(10, ops=((("a", "b"), 40.0, 10.0, 60.0),)),
            scan(20, ops=((("a", "b"), 4.0, 10.0, 60.0),)),
        ]
        loop = summarise(records).loops[0]
        assert loop.best_profit_pct == 40.0
        assert loop.median_profit_pct == 4.0

    def test_recurring_needs_more_than_one_sighting(self):
        once = summarise([scan(0, ops=((("a", "b"), 4.0, 10.0, 60.0),))]).loops[0]
        assert not once.recurring
        many = summarise([
            scan(i * 10, ops=((("a", "b"), 4.0, 10.0, 60.0),))
            for i in range(RECURRING_THRESHOLD)
        ]).loops[0]
        assert many.recurring

    def test_ranked_by_how_often_then_how_good(self):
        records = [
            scan(0, ops=((("a", "b"), 30.0, 10.0, 60.0),)),
            scan(10, ops=((("c", "d"), 4.0, 10.0, 60.0),)),
            scan(20, ops=((("c", "d"), 4.0, 10.0, 60.0),)),
        ]
        assert summarise(records).loops[0].cycle == ("c", "d")

    def test_median_skew_is_carried_through(self):
        records = [
            scan(0, ops=((("a", "b"), 4.0, 10.0, 60.0),)),
            scan(10, ops=((("a", "b"), 4.0, 10.0, 200.0),)),
            scan(20, ops=((("a", "b"), 4.0, 10.0, 220.0),)),
        ]
        assert summarise(records).loops[0].median_skew_s == 200.0

    def test_unstamped_loops_report_no_skew(self):
        records = [scan(0, ops=((("a", "b"), 4.0, 10.0, None),))]
        assert summarise(records).loops[0].median_skew_s is None

    def test_rotations_are_distinct_records(self):
        """History stores what was found; the detector already deduped rotations."""
        records = [scan(0, ops=((("a", "b", "c"), 4.0, 10.0, 60.0),))]
        assert summarise(records).loops[0].cycle == ("a", "b", "c")


class TestCurrencyStats:
    def test_tracks_how_long_each_currency_was_in_the_graph(self):
        records = [
            scan(0, nodes=("divine", "chaos")),
            scan(10, nodes=("divine", "chaos", "exalted")),
        ]
        by_id = {c.item_id: c for c in summarise(records).currencies}
        assert by_id["divine"].scans_tracked == 2
        assert by_id["exalted"].scans_tracked == 1

    def test_hit_rate_is_relative_to_time_tracked(self):
        """A currency added yesterday mustn't look worse than a month-old one."""
        records = [
            scan(0, nodes=("divine", "chaos")),
            scan(10, nodes=("divine", "chaos")),
            scan(20, nodes=("divine", "chaos", "new"),
                 ops=((("divine", "new"), 5.0, 10.0, 60.0),)),
        ]
        by_id = {c.item_id: c for c in summarise(records).currencies}
        assert by_id["new"].scans_tracked == 1
        assert by_id["new"].hit_rate_pct == 100.0
        assert by_id["divine"].hit_rate_pct == pytest.approx(33.33, abs=0.01)

    def test_a_currency_counted_once_per_scan_not_once_per_loop(self):
        records = [
            scan(0, ops=(
                (("divine", "chaos"), 4.0, 10.0, 60.0),
                (("divine", "exalted"), 5.0, 10.0, 60.0),
            )),
        ]
        by_id = {c.item_id: c for c in summarise(records).currencies}
        assert by_id["divine"].loops_seen == 1

    def test_best_profit_is_the_best_loop_it_took_part_in(self):
        records = [
            scan(0, ops=((("divine", "chaos"), 4.0, 10.0, 60.0),)),
            scan(10, ops=((("divine", "exalted"), 12.0, 10.0, 60.0),)),
        ]
        by_id = {c.item_id: c for c in summarise(records).currencies}
        assert by_id["divine"].best_profit_pct == 12.0
        assert by_id["chaos"].best_profit_pct == 4.0

    def test_earning_currencies_rank_above_dead_weight(self):
        records = [
            scan(0, ops=((("divine", "chaos"), 4.0, 10.0, 60.0),)),
        ]
        assert summarise(records).currencies[-1].item_id == "exalted"


class TestDeadWeight:
    def test_names_slots_worth_reclaiming(self):
        """The measurement node selection has to beat."""
        records = [
            scan(i, nodes=("divine", "chaos", "dud"),
                 ops=((("divine", "chaos"), 4.0, 10.0, 60.0),))
            for i in range(25)
        ]
        assert [c.item_id for c in dead_weight(summarise(records))] == ["dud"]

    def test_too_small_a_sample_condemns_nobody(self):
        records = [scan(i, nodes=("divine", "chaos", "dud")) for i in range(3)]
        assert dead_weight(summarise(records)) == []

    def test_threshold_is_adjustable(self):
        records = [scan(i, nodes=("divine", "dud")) for i in range(5)]
        assert {c.item_id for c in dead_weight(summarise(records), min_scans=5)} == {
            "divine", "dud",
        }

    def test_tied_rows_keep_a_stable_order(self):
        """Node ids come out of a set, and string hashing is randomised per
        process — without an explicit tiebreak the table reshuffles on launch."""
        records = [scan(i, nodes=("aaa", "bbb", "ccc")) for i in range(3)]
        order = [c.item_id for c in summarise(records).currencies]
        assert order == ["aaa", "bbb", "ccc"]


class TestSummaryShape:
    def test_empty_history(self):
        summary = summarise([])
        assert summary.is_empty
        assert summary.loops == [] and summary.currencies == []
        assert summary.first_scan is None
        assert summary.hit_rate_pct == 0.0

    def test_scan_hit_rate(self):
        records = [
            scan(0, ops=((("a", "b"), 4.0, 10.0, 60.0),)),
            scan(10),
            scan(20),
            scan(30, ops=((("a", "b"), 4.0, 10.0, 60.0),)),
        ]
        assert summarise(records).hit_rate_pct == 50.0

    def test_records_without_timestamps_are_skipped(self):
        assert summarise([{"league": "T"}]).scans == 0

    def test_malformed_opportunity_does_not_sink_the_scan(self):
        record = scan(0, ops=((("a", "b"), 4.0, 10.0, 60.0),))
        record["opportunities"].append({"cycle": ["x"]})  # no profit
        summary = summarise([record])
        assert summary.scans == 1
        assert len(summary.loops) == 1

    def test_reads_from_a_file(self, tmp_path):
        import json

        path = tmp_path / "history.jsonl"
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(3):
            row = scan(0, ops=((("a", "b"), 4.0, 10.0, 60.0),))
            row["ts"] = (now - timedelta(hours=i)).isoformat()
            rows.append(json.dumps(row))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        assert summarise_file(path, window_days=7.0).scans == 3

    def test_window_excludes_older_scans(self, tmp_path):
        import json

        path = tmp_path / "history.jsonl"
        now = datetime.now(timezone.utc)
        rows = []
        for age_hours in (1, 100):
            row = scan(0)
            row["ts"] = (now - timedelta(hours=age_hours)).isoformat()
            rows.append(json.dumps(row))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        assert summarise_file(path, window_days=1.0).scans == 1
        assert summarise_file(path, window_days=0.0).scans == 2

    def test_missing_file_is_empty_not_an_error(self, tmp_path):
        assert summarise_file(tmp_path / "nope.jsonl", 7.0).is_empty


class TestJudgeable:
    """Guards the Trends note against claiming more than the data supports."""

    def test_a_thin_history_supports_no_verdict(self):
        """Two scans and no loops must not read as 'everything is earning its slot'."""
        from poe2arb.history_stats import judgeable

        records = [scan(i, nodes=("divine", "chaos")) for i in range(2)]
        assert judgeable(summarise(records)) == []

    def test_enough_scans_makes_a_currency_judgeable(self):
        from poe2arb.history_stats import DEAD_WEIGHT_MIN_SCANS, judgeable

        records = [
            scan(i, nodes=("divine", "chaos"))
            for i in range(DEAD_WEIGHT_MIN_SCANS)
        ]
        assert len(judgeable(summarise(records))) == 2

    def test_dead_weight_is_a_subset_of_what_can_be_judged(self):
        from poe2arb.history_stats import judgeable

        records = [
            scan(i, nodes=("divine", "chaos", "dud"),
                 ops=((("divine", "chaos"), 4.0, 10.0, 60.0),))
            for i in range(25)
        ]
        summary = summarise(records)
        judged = {c.item_id for c in judgeable(summary)}
        assert {c.item_id for c in dead_weight(summary)} <= judged
