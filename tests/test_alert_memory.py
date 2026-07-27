"""What the window remembers between scans, and across a restart.

The methods under test only touch `_known`, `_known_longer` and `_log`, so they
run against a stub rather than a real MainWindow — constructing one starts
worker threads and hits the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.graph import Opportunity  # noqa: E402
from poe2arb.gui.main_window import ALERT_MEMORY_HOURS, MainWindow  # noqa: E402
from poe2arb.scan import ScanResult  # noqa: E402


class Stub:
    """Just the attributes the two methods reach for."""

    def __init__(self):
        self._known: dict[tuple[str, ...], float] = {}
        self._known_longer: tuple[str, ...] | None = None
        self.lines: list[str] = []

    def _log(self, line, ts=None):
        self.lines.append(line)


def ago(hours: float) -> datetime:
    return datetime.now().astimezone() - timedelta(hours=hours)


def result_with(longer: Opportunity | None) -> ScanResult:
    overview = NinjaOverview(
        league="T", fetched_at=datetime.now(timezone.utc),
        values={}, volumes={}, names={},
    )
    return ScanResult(
        league="T", overview=overview, nodes=[], edges={},
        opportunities=[], longer_cycle=longer,
    )


class TestCarryForwardAlerts:
    def test_fresh_opportunities_count_as_already_announced(self):
        """Otherwise a restart re-toasts every loop the user was just told about."""
        stub = Stub()
        seen = {("a", "b"): 4.0, ("c", "d"): 6.0}
        MainWindow._carry_forward_alerts(stub, seen, ago(0.1))
        assert stub._known == seen

    def test_stale_opportunities_are_announced_again(self):
        """Hours later a loop reappearing is news, not a repeat."""
        stub = Stub()
        MainWindow._carry_forward_alerts(
            stub, {("a", "b"): 4.0}, ago(ALERT_MEMORY_HOURS + 1)
        )
        assert stub._known == {}

    def test_nothing_to_carry_is_silent(self):
        stub = Stub()
        MainWindow._carry_forward_alerts(stub, {}, ago(0.1))
        assert stub._known == {} and stub.lines == []

    def test_the_user_is_told_it_happened(self):
        stub = Stub()
        MainWindow._carry_forward_alerts(stub, {("a", "b"): 4.0}, ago(0.1))
        assert any("restart" in line for line in stub.lines)


class TestLongerCycleNotice:
    def test_route_is_named_not_just_asserted(self):
        stub = Stub()
        op = Opportunity(("exalted", "chaos", "annul", "divine"), 1.4, 12.0)
        MainWindow._note_longer_cycle(stub, result_with(op), {"chaos": "Chaos Orb"})
        assert len(stub.lines) == 1
        assert "Chaos Orb" in stub.lines[0]
        assert "+1.40%" in stub.lines[0]

    def test_same_route_not_repeated_every_scan(self):
        stub = Stub()
        op = Opportunity(("a", "b", "c", "d"), 1.4, 12.0)
        for _ in range(3):
            MainWindow._note_longer_cycle(stub, result_with(op), {})
        assert len(stub.lines) == 1

    def test_a_different_route_is_reported(self):
        stub = Stub()
        MainWindow._note_longer_cycle(stub, result_with(Opportunity(("a", "b"), 1.0, 5.0)), {})
        MainWindow._note_longer_cycle(stub, result_with(Opportunity(("c", "d"), 2.0, 5.0)), {})
        assert len(stub.lines) == 2

    def test_nothing_logged_when_there_is_no_cycle(self):
        stub = Stub()
        MainWindow._note_longer_cycle(stub, result_with(None), {})
        assert stub.lines == []

    def test_clearing_lets_it_be_reported_again_later(self):
        stub = Stub()
        op = Opportunity(("a", "b"), 1.0, 5.0)
        MainWindow._note_longer_cycle(stub, result_with(op), {})
        MainWindow._note_longer_cycle(stub, result_with(None), {})
        MainWindow._note_longer_cycle(stub, result_with(op), {})
        assert len(stub.lines) == 2
