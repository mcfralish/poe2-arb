"""Request-budget math. Getting this wrong means a 30-minute IP ban."""

from __future__ import annotations

import pytest

from poe2arb.rate_limit import (
    DEFAULT_WINDOWS,
    Severity,
    Window,
    check_pacing,
    max_hits_in_window,
    min_safe_interval,
    parse_state,
    parse_windows,
    requests_per_scan,
    scan_duration_estimate_s,
    worst_severity,
)


class TestHeaderParsing:
    def test_parse_windows_live_header(self):
        windows = parse_windows("5:15:60,10:90:300,30:300:1800")
        assert windows == (Window(5, 15, 60), Window(10, 90, 300), Window(30, 300, 1800))

    def test_parse_state_live_header(self):
        state = parse_state("2:15:0,4:90:0,4:300:0")
        assert state == {15: (2, 0), 90: (4, 0), 300: (4, 0)}

    def test_state_reports_active_restriction(self):
        assert parse_state("30:300:1800")[300] == (30, 1800)

    def test_malformed_parts_ignored(self):
        assert parse_windows("garbage,5:15:60,x:y:z") == (Window(5, 15, 60),)
        assert parse_state("") == {}


class TestWindowMath:
    def test_boundary_request_counts(self):
        """The +1 matters: 10s spacing puts 31 requests in a 300s window."""
        assert max_hits_in_window(300, 10.0) == 31
        assert max_hits_in_window(90, 10.0) == 10
        assert max_hits_in_window(15, 10.0) == 2

    def test_ten_seconds_exceeds_the_widest_window(self):
        """Regression: the old default was over the limit."""
        issues = check_pacing(10.0)
        assert worst_severity(issues) is Severity.ERROR
        assert any(i.window.period_s == 300 for i in issues if i.severity is Severity.ERROR)

    def test_shipped_default_is_safe(self):
        from poe2arb.config import Config

        assert worst_severity(check_pacing(Config().request_interval_s)) is Severity.OK

    def test_min_safe_interval_is_actually_safe(self):
        interval = min_safe_interval()
        assert worst_severity(check_pacing(interval)) is Severity.OK

    def test_min_safe_interval_is_not_wastefully_slow(self):
        assert min_safe_interval() <= 20.0

    @pytest.mark.parametrize("interval", [0.5, 1.0, 3.0, 5.0, 9.0, 10.0])
    def test_fast_intervals_are_errors(self, interval):
        assert worst_severity(check_pacing(interval)) is Severity.ERROR

    def test_error_message_names_the_penalty(self):
        errors = [i for i in check_pacing(1.0) if i.severity is Severity.ERROR]
        assert any("minutes" in i.message for i in errors)

    def test_warning_band_between_safe_and_illegal(self):
        """Legal but with little headroom for other tools on the same IP."""
        seen = {worst_severity(check_pacing(i / 2)) for i in range(21, 40)}
        assert Severity.WARNING in seen

    def test_safety_fraction_tightens_requirements(self):
        assert min_safe_interval(safety_fraction=0.5) > min_safe_interval(safety_fraction=1.0)

    def test_custom_windows_respected(self):
        strict = (Window(2, 60, 600),)
        assert worst_severity(check_pacing(10.0, windows=strict)) is Severity.ERROR
        # 60s spacing still lands 2 requests in a 60s window (t=0 and t=60),
        # which is legal but uses the whole budget — hence a warning, not OK.
        assert worst_severity(check_pacing(60.0, windows=strict)) is Severity.WARNING
        assert worst_severity(check_pacing(120.0, windows=strict)) is Severity.OK


class TestScanCost:
    def test_requests_per_scan_matches_observed(self):
        # 10 currencies, chunk 6 -> 2 chunks each -> 20 requests, as seen live.
        assert requests_per_scan(10, 6) == 20

    def test_fifteen_currencies_is_much_worse(self):
        assert requests_per_scan(15, 6) == 45

    def test_trivial_graphs_cost_nothing(self):
        assert requests_per_scan(1, 6) == 0

    def test_duration_estimate(self):
        # 20 requests at 13s spacing = 19 gaps.
        assert scan_duration_estimate_s(10, 6, 13.0) == pytest.approx(247.0)


class TestRealWorldConfigs:
    def test_users_15_currency_config_at_10s_is_rejected(self):
        """The exact settings that prompted this guard."""
        assert worst_severity(check_pacing(10.0)) is Severity.ERROR

    def test_all_default_windows_covered(self):
        issues = check_pacing(0.1)
        assert {i.window.period_s for i in issues} == {w.period_s for w in DEFAULT_WINDOWS}
