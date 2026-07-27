"""Reading scan history back for startup restore."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poe2arb.history import append_scan, prune, read_recent
from poe2arb.graph import Edge, Opportunity
from poe2arb.scan import result_from_history_record


def write_record(path: Path, *, hours_ago: float, ops: list[tuple] = ()) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    record = {
        "ts": ts.isoformat(),
        "league": "Test League",
        "ninja_values_divine": {"divine": 1.0, "chaos": 0.11},
        "ninja_volumes_divine": {"divine": 999.0, "chaos": 5000.0},
        "book_edges": [
            {"src": "divine", "dst": "chaos", "raw_rate": 9.0,
             "effective_rate": 8.86, "depth_divines": 40.0},
        ],
        "opportunities": [
            {"cycle": list(c), "profit_pct": p, "min_depth_divines": d} for c, p, d in ops
        ],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


class TestReadRecent:
    def test_missing_file_is_empty(self, tmp_path):
        assert read_recent(tmp_path / "nope.jsonl", 8) == []

    def test_reads_records_within_window(self, tmp_path):
        p = tmp_path / "history.jsonl"
        write_record(p, hours_ago=1)
        write_record(p, hours_ago=2)
        assert len(read_recent(p, 8)) == 2

    def test_excludes_records_older_than_window(self, tmp_path):
        p = tmp_path / "history.jsonl"
        write_record(p, hours_ago=1)
        write_record(p, hours_ago=20)
        records = read_recent(p, 8)
        assert len(records) == 1

    def test_returned_oldest_first(self, tmp_path):
        p = tmp_path / "history.jsonl"
        write_record(p, hours_ago=1)
        write_record(p, hours_ago=5)
        records = read_recent(p, 8)
        assert records[0]["ts"] < records[1]["ts"]

    def test_corrupt_lines_skipped(self, tmp_path):
        p = tmp_path / "history.jsonl"
        write_record(p, hours_ago=1)
        with open(p, "a") as f:
            f.write("not json at all\n\n")
        write_record(p, hours_ago=2)
        assert len(read_recent(p, 8)) == 2

    def test_record_without_timestamp_skipped(self, tmp_path):
        p = tmp_path / "history.jsonl"
        with open(p, "w") as f:
            f.write(json.dumps({"league": "x"}) + "\n")
        assert read_recent(p, 8) == []

    def test_round_trips_a_real_append(self, tmp_path):
        """Whatever append_scan writes must be readable back."""
        p = tmp_path / "history.jsonl"
        append_scan(
            p,
            league="Test",
            values={"divine": 1.0},
            volumes={"divine": 5.0},
            edges={("a", "b"): Edge("a", "b", 1.1, 1.12, 30.0)},
            opportunities=[Opportunity(("a", "b"), 4.2, 30.0)],
        )
        records = read_recent(p, 8)
        assert len(records) == 1
        assert records[0]["opportunities"][0]["profit_pct"] == 4.2


class TestPrune:
    """A watch loop appends forever, so old records have to age out."""

    def test_drops_records_past_retention(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        write_record(p, hours_ago=1)
        assert prune(p, 30.0, min_bytes=0) == 1
        assert len(read_recent(p, 24 * 365)) == 1

    def test_keeps_everything_inside_retention(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=1)
        write_record(p, hours_ago=48)
        assert prune(p, 30.0, min_bytes=0) == 0
        assert len(read_recent(p, 24 * 365)) == 2

    def test_zero_retention_keeps_everything(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 400)
        assert prune(p, 0.0, min_bytes=0) == 0
        assert len(read_recent(p, 24 * 500)) == 1

    def test_small_file_is_left_alone(self, tmp_path):
        """The common case must not rewrite the file on every single scan."""
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        assert prune(p, 30.0) == 0  # default min_bytes, file is tiny
        assert len(read_recent(p, 24 * 500)) == 1

    def test_corrupt_lines_dropped_when_pruning(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        with open(p, "a") as f:
            f.write("not json\n")
        write_record(p, hours_ago=1)
        assert prune(p, 30.0, min_bytes=0) == 2
        assert len(read_recent(p, 24 * 365)) == 1

    def test_missing_file_is_harmless(self, tmp_path):
        assert prune(tmp_path / "nope.jsonl", 30.0, min_bytes=0) == 0

    def test_no_temp_file_left_behind(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        write_record(p, hours_ago=1)
        prune(p, 30.0, min_bytes=0)
        assert [f.name for f in tmp_path.iterdir()] == ["h.jsonl"]

    def test_append_prunes_when_asked(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        append_scan(
            p, league="T", values={}, volumes={}, edges={}, opportunities=[],
            retention_days=30.0,
        )
        # Default min_bytes protects a file this small, so nothing goes yet.
        assert len(read_recent(p, 24 * 500)) == 2

    def test_records_stay_readable_after_pruning(self, tmp_path):
        p = tmp_path / "h.jsonl"
        write_record(p, hours_ago=24 * 40)
        write_record(p, hours_ago=2, ops=[(("a", "b"), 7.5, 10.0)])
        prune(p, 30.0, min_bytes=0)
        records = read_recent(p, 24 * 365)
        assert records[0]["opportunities"][0]["profit_pct"] == 7.5


class TestLongerCyclePersistence:
    """The route Bellman-Ford found must survive a restart, like the rest."""

    def test_round_trips(self, tmp_path):
        p = tmp_path / "h.jsonl"
        append_scan(
            p, league="T", values={"divine": 1.0}, volumes={"divine": 5.0},
            edges={}, opportunities=[],
            longer_cycle=Opportunity(("a", "b", "c", "d"), 1.4, 12.0),
        )
        result = result_from_history_record(read_recent(p, 8)[0], {})
        assert result.longer_cycle.cycle == ("a", "b", "c", "d")
        assert result.longer_cycle.profit_pct == 1.4
        assert result.longer_cycle_hint

    def test_absent_when_not_recorded(self, tmp_path):
        record = write_record(tmp_path / "h.jsonl", hours_ago=1)
        result = result_from_history_record(record, {})
        assert result.longer_cycle is None
        assert not result.longer_cycle_hint

    def test_malformed_entry_ignored(self, tmp_path):
        record = write_record(tmp_path / "h.jsonl", hours_ago=1)
        record["longer_cycle"] = {"cycle": ["a", "b"]}  # missing profit
        assert result_from_history_record(record, {}).longer_cycle is None


class TestResultReconstruction:
    def test_rebuilds_tables_worth_of_data(self, tmp_path):
        p = tmp_path / "h.jsonl"
        record = write_record(p, hours_ago=1, ops=[(("divine", "chaos"), 4.5, 40.0)])
        result = result_from_history_record(record, {})

        assert result.league == "Test League"
        assert result.overview.values["chaos"] == 0.11
        assert result.overview.volumes["chaos"] == 5000.0
        assert result.edges[("divine", "chaos")].rate == 8.86
        assert result.opportunities[0].profit_pct == 4.5
        assert set(result.nodes) == {"divine", "chaos"}

    def test_names_applied_when_available(self, tmp_path):
        record = write_record(tmp_path / "h.jsonl", hours_ago=1)
        result = result_from_history_record(record, {"chaos": "Chaos Orb"})
        assert result.overview.names["chaos"] == "Chaos Orb"

    def test_ids_used_when_names_unknown(self, tmp_path):
        record = write_record(tmp_path / "h.jsonl", hours_ago=1)
        result = result_from_history_record(record, {})
        assert result.overview.names["chaos"] == "chaos"

    def test_opportunities_ranked_by_profit(self, tmp_path):
        record = write_record(
            tmp_path / "h.jsonl", hours_ago=1,
            ops=[(("a", "b"), 2.0, 10.0), (("c", "d"), 9.0, 10.0)],
        )
        result = result_from_history_record(record, {})
        assert [op.profit_pct for op in result.opportunities] == [9.0, 2.0]

    def test_malformed_entries_skipped_not_fatal(self, tmp_path):
        record = write_record(tmp_path / "h.jsonl", hours_ago=1)
        record["book_edges"].append({"src": "x"})  # missing fields
        record["opportunities"].append({"cycle": ["a"]})
        result = result_from_history_record(record, {})
        assert len(result.edges) == 1
        assert result.opportunities == []

    def test_empty_record_is_harmless(self):
        result = result_from_history_record(
            {"ts": datetime.now(timezone.utc).isoformat()}, {}
        )
        assert result.edges == {} and result.opportunities == []
