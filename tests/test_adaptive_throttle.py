"""Header-driven throttling: the only defence against *other* tools on the IP.

The configured interval only knows about this app. X-Rate-Limit-Ip-State
reports what the whole IP has spent, so it's what keeps a busy connection
out of a ban.
"""

from __future__ import annotations

import httpx
import pytest

from poe2arb.client import GggExchangeClient
from poe2arb.config import Config


def client(tmp_path, **kwargs) -> GggExchangeClient:
    return GggExchangeClient(Config(cache_dir=tmp_path, **kwargs))


def response(limit: str | None, state: str | None) -> httpx.Response:
    headers = {}
    if limit:
        headers["X-Rate-Limit-Ip"] = limit
    if state:
        headers["X-Rate-Limit-Ip-State"] = state
    return httpx.Response(200, headers=headers, json={})


LIMITS = "5:15:60,10:90:300,30:300:1800"


class TestAdaptiveBackoff:
    def test_quiet_ip_adds_no_backoff(self, tmp_path):
        c = client(tmp_path)
        c._apply_rate_limit_headers(response(LIMITS, "1:15:0,2:90:0,3:300:0"))
        assert c._header_backoff_s == 0.0

    def test_busy_ip_triggers_backoff(self, tmp_path):
        """Another tool has eaten the budget — slow down even though our own
        request count is low."""
        c = client(tmp_path)
        c._apply_rate_limit_headers(response(LIMITS, "1:15:0,2:90:0,26:300:0"))
        assert c._header_backoff_s > 0

    def test_active_restriction_waits_it_out(self, tmp_path):
        c = client(tmp_path)
        c._apply_rate_limit_headers(response(LIMITS, "0:15:0,0:90:0,30:300:1800"))
        assert c._header_backoff_s == pytest.approx(1800.0)

    def test_backoff_raises_effective_interval(self, tmp_path):
        c = client(tmp_path, request_interval_s=13.0)
        c._apply_rate_limit_headers(response(LIMITS, "0:15:0,0:90:0,30:300:600"))
        assert max(c.cfg.request_interval_s, c._header_backoff_s) == 600.0

    def test_backoff_clears_when_pressure_passes(self, tmp_path):
        c = client(tmp_path)
        c._apply_rate_limit_headers(response(LIMITS, "5:15:0,9:90:0,29:300:0"))
        assert c._header_backoff_s > 0
        c._apply_rate_limit_headers(response(LIMITS, "1:15:0,1:90:0,1:300:0"))
        assert c._header_backoff_s == 0.0

    def test_safety_fraction_controls_sensitivity(self, tmp_path):
        state = "0:15:0,0:90:0,20:300:0"  # 20 of 30 used
        relaxed = client(tmp_path, rate_limit_safety_fraction=1.0)
        relaxed._apply_rate_limit_headers(response(LIMITS, state))
        cautious = client(tmp_path, rate_limit_safety_fraction=0.5)
        cautious._apply_rate_limit_headers(response(LIMITS, state))
        assert relaxed._header_backoff_s == 0.0
        assert cautious._header_backoff_s > 0

    def test_server_limits_override_our_defaults(self, tmp_path):
        """GGG can change limits without notice; trust the header."""
        c = client(tmp_path)
        c._apply_rate_limit_headers(response("4:300:900", "4:300:0"))
        assert c._header_backoff_s == pytest.approx(75.0)  # 300s / 4

    def test_missing_headers_are_harmless(self, tmp_path):
        c = client(tmp_path)
        c._apply_rate_limit_headers(response(None, None))
        assert c._header_backoff_s == 0.0

    def test_garbage_headers_are_harmless(self, tmp_path):
        c = client(tmp_path)
        c._apply_rate_limit_headers(response("nonsense", "also:nonsense"))
        assert c._header_backoff_s == 0.0
