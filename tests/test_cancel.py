"""Scan cancellation: aborts promptly, and never on the non-cancelled path."""

from __future__ import annotations

import time

import pytest

from poe2arb.client import GggExchangeClient, ScanCancelled
from poe2arb.config import Config


def make_client(tmp_path, should_cancel, interval_s=10.0) -> GggExchangeClient:
    cfg = Config(cache_dir=tmp_path, request_interval_s=interval_s)
    return GggExchangeClient(cfg, should_cancel)


class TestPacingCancellation:
    def test_pace_returns_promptly_when_cancelled(self, tmp_path):
        """The 10s pacing sleep must not hold shutdown for 10s."""
        client = make_client(tmp_path, lambda: True)
        client._last_request_t = time.monotonic()  # full interval still to wait
        started = time.monotonic()
        with pytest.raises(ScanCancelled):
            client._pace()
        assert time.monotonic() - started < 1.0

    def test_pace_waits_when_not_cancelled(self, tmp_path):
        client = make_client(tmp_path, lambda: False, interval_s=0.5)
        client._last_request_t = time.monotonic()
        started = time.monotonic()
        client._pace()
        assert time.monotonic() - started >= 0.45

    def test_pace_no_wait_when_interval_elapsed(self, tmp_path):
        client = make_client(tmp_path, lambda: False, interval_s=10.0)
        client._last_request_t = time.monotonic() - 60  # long past due
        started = time.monotonic()
        client._pace()
        assert time.monotonic() - started < 0.2

    def test_cancel_becomes_true_midway(self, tmp_path):
        """Cancellation set during the sleep is noticed at the next slice."""
        deadline = time.monotonic() + 0.4
        client = make_client(tmp_path, lambda: time.monotonic() > deadline, interval_s=10.0)
        client._last_request_t = time.monotonic()
        with pytest.raises(ScanCancelled):
            client._pace()

    def test_no_cancel_callback_is_supported(self, tmp_path):
        """CLI path passes no callback; must never raise."""
        client = make_client(tmp_path, None, interval_s=0.1)
        client._last_request_t = time.monotonic()
        client._pace()  # no exception

    def test_fetch_offers_checks_cancel_before_network(self, tmp_path):
        """Cancelled scan must not issue a request even on a cache miss."""
        client = make_client(tmp_path, lambda: True)
        with pytest.raises(ScanCancelled):
            client.fetch_offers("Some League", "divine", ["chaos"])


class TestExceptionTaxonomy:
    def test_cancelled_is_not_a_client_error(self):
        """Cancellation is control flow, not a failure — must not hit error handlers."""
        from poe2arb.client import ClientError

        assert not issubclass(ScanCancelled, ClientError)


class TestInterruptibleSleep:
    """A rate-limit Retry-After can be minutes long; Stop must still work."""

    def test_returns_promptly_when_cancelled(self):
        from poe2arb.client import interruptible_sleep

        started = time.monotonic()
        with pytest.raises(ScanCancelled):
            interruptible_sleep(300.0, lambda: True)
        assert time.monotonic() - started < 1.0

    def test_sleeps_fully_when_not_cancelled(self):
        from poe2arb.client import interruptible_sleep

        started = time.monotonic()
        interruptible_sleep(0.3, lambda: False)
        assert time.monotonic() - started >= 0.25

    def test_no_callback_still_sleeps(self):
        from poe2arb.client import interruptible_sleep

        started = time.monotonic()
        interruptible_sleep(0.2, None)
        assert time.monotonic() - started >= 0.15

    def test_cancel_midway_is_noticed(self):
        from poe2arb.client import interruptible_sleep

        deadline = time.monotonic() + 0.3
        with pytest.raises(ScanCancelled):
            interruptible_sleep(60.0, lambda: time.monotonic() > deadline)


class TestBackoffCancellation:
    def test_429_retry_wait_is_cancellable(self, tmp_path):
        """The exact case that made Stop hang: a 141s Retry-After."""
        import httpx

        from poe2arb.client import _request_with_backoff

        def handler(request):
            return httpx.Response(429, headers={"Retry-After": "300"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        started = time.monotonic()
        with pytest.raises(ScanCancelled):
            _request_with_backoff(client, "GET", "https://x.test", should_cancel=lambda: True)
        assert time.monotonic() - started < 1.0

    def test_cancel_checked_before_issuing_request(self, tmp_path):
        import httpx

        from poe2arb.client import _request_with_backoff

        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ScanCancelled):
            _request_with_backoff(client, "GET", "https://x.test", should_cancel=lambda: True)
        assert calls == []
