"""Currency selection: liquidity floor, exclusions, value cap."""

from __future__ import annotations

from datetime import datetime, timezone

from poe2arb.client import NinjaOverview
from poe2arb.config import Config
from poe2arb.scan import select_nodes


def overview(values: dict[str, float], volumes: dict[str, float]) -> NinjaOverview:
    return NinjaOverview(
        league="Test",
        fetched_at=datetime.now(timezone.utc),
        values=values,
        volumes=volumes,
        names={c: c for c in values},
    )


BASE = overview(
    values={"divine": 1.0, "mirror": 4886.0, "chaos": 0.11, "exalted": 0.0022, "annul": 0.5},
    volumes={"divine": float("inf"), "mirror": 5000.0, "chaos": 60000.0,
             "exalted": 40000.0, "annul": 8000.0},
)


class TestExclusions:
    def test_nothing_excluded_by_default(self):
        """Excluding anything is the user's call — we don't presume."""
        assert Config().exclude_currencies == []
        nodes = select_nodes(BASE, Config())
        assert "mirror" in nodes
        assert "chaos" in nodes and "exalted" in nodes

    def test_explicit_exclusion_list(self):
        nodes = select_nodes(BASE, Config(exclude_currencies=["chaos", "annul"]))
        assert "chaos" not in nodes and "annul" not in nodes
        assert "mirror" in nodes

    def test_exclusions_are_case_and_space_insensitive(self):
        nodes = select_nodes(BASE, Config(exclude_currencies=[" Chaos ", "MIRROR"]))
        assert "chaos" not in nodes and "mirror" not in nodes

    def test_empty_exclusion_list_keeps_everything(self):
        nodes = select_nodes(BASE, Config(exclude_currencies=[], max_currencies=10))
        assert "mirror" in nodes

    def test_primary_always_present_and_first(self):
        # Even if someone tries to exclude it — there'd be nothing to price against.
        nodes = select_nodes(BASE, Config(exclude_currencies=["divine"]))
        assert nodes[0] == "divine"
        assert nodes.count("divine") == 1


class TestValueCap:
    def test_cap_drops_expensive_currencies(self):
        nodes = select_nodes(
            BASE, Config(exclude_currencies=[], max_currency_value_divines=100.0)
        )
        assert "mirror" not in nodes
        assert "chaos" in nodes

    def test_zero_cap_means_no_limit(self):
        nodes = select_nodes(
            BASE, Config(exclude_currencies=[], max_currency_value_divines=0.0)
        )
        assert "mirror" in nodes


class TestLiquidityAndSize:
    def test_liquidity_floor_applies(self):
        nodes = select_nodes(
            BASE, Config(exclude_currencies=[], liquidity_floor_divines=30000.0)
        )
        assert set(nodes) == {"divine", "chaos", "exalted"}

    def test_max_currencies_caps_graph_size(self):
        nodes = select_nodes(BASE, Config(exclude_currencies=[], max_currencies=3))
        assert len(nodes) == 3
        assert nodes[0] == "divine"

    def test_ordered_by_volume_descending(self):
        nodes = select_nodes(BASE, Config(exclude_currencies=[]))
        volumes = [BASE.volumes[c] for c in nodes[1:]]
        assert volumes == sorted(volumes, reverse=True)
