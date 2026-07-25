"""Parser tests against saved real API responses (captured 2026-07-25, Runes of Aldur)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poe2arb.client import PRIMARY, SchemaError, parse_exchange, parse_overview

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestParseOverview:
    def test_real_response(self):
        ov = parse_overview(
            load("ninja_currency_overview.json"), "Runes of Aldur",
            datetime.now(timezone.utc),
        )
        assert ov.values[PRIMARY] == 1.0
        assert 0 < ov.values["chaos"] < 1          # chaos is worth < 1 divine
        assert 0 < ov.values["exalted"] < ov.values["chaos"]
        assert ov.volumes["chaos"] > 0
        assert ov.names["chaos"] == "Chaos Orb"
        assert len(ov.values) > 40                 # 52 lines captured live

    def test_missing_lines_is_schema_error(self):
        with pytest.raises(SchemaError):
            parse_overview({"core": {}}, "x", datetime.now(timezone.utc))

    def test_changed_primary_unit_is_schema_error(self):
        data = load("ninja_currency_overview.json")
        data["core"]["primary"] = "chaos"
        with pytest.raises(SchemaError, match="primary unit"):
            parse_overview(data, "x", datetime.now(timezone.utc))

    def test_nonpositive_values_skipped(self):
        data = {
            "core": {"primary": PRIMARY, "secondary": "chaos", "rates": {}, "items": []},
            "lines": [
                {"id": "good", "primaryValue": 0.5, "volumePrimaryValue": 10},
                {"id": "zero", "primaryValue": 0},
                {"id": "none", "primaryValue": None},
            ],
            "items": [],
        }
        ov = parse_overview(data, "x", datetime.now(timezone.utc))
        assert "good" in ov.values
        assert "zero" not in ov.values and "none" not in ov.values


class TestParseExchange:
    def test_real_response(self):
        offers = parse_exchange(load("ggg_exchange_want_divine.json"))
        assert len(offers) > 50
        pairs = {(o.pay_currency, o.get_currency) for o in offers}
        assert ("exalted", "divine") in pairs
        assert ("chaos", "divine") in pairs
        for o in offers:
            assert o.pay_amount > 0
            assert o.rate > 0

    def test_missing_result_is_schema_error(self):
        with pytest.raises(SchemaError):
            parse_exchange({"nope": 1})

    def test_empty_result_as_list(self):
        # No matches = empty list, not empty object (seen live 2026-07-25).
        assert parse_exchange({"id": "x", "result": [], "total": 0}) == []

    def test_malformed_listing_skipped(self):
        data = {
            "result": {
                "a": {"listing": {"offers": [
                    {"exchange": {"currency": "x", "amount": 0},   # zero amount
                     "item": {"currency": "y", "amount": 1, "stock": 5}},
                    {"exchange": {"currency": "x", "amount": 2},
                     "item": {"currency": "y", "amount": 1, "stock": 5}},
                ]}},
            }
        }
        offers = parse_exchange(data)
        assert len(offers) == 1
        assert offers[0].rate == pytest.approx(0.5)
