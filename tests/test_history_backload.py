"""Reading scan history back for startup restore."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poe2arb.history import append_scan, read_recent
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
