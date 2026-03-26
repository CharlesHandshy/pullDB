"""Unit tests for pulldb.infra.rate_limit.RateLimiter.

Covers:
  _get_client_ip  — X-Forwarded-For priority, client.host fallback, unknown
  check           — allow under limit, block at limit, Retry-After header,
                    sliding-window expiry, multi-IP isolation
  __call__        — delegates to check (FastAPI DI interface)
  thread-safety   — concurrent requests from the same IP

HCA Layer: shared (tests)
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from pulldb.infra.rate_limit import RateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    ip: str = "10.0.0.1",
    forwarded_for: str | None = None,
) -> MagicMock:
    """Build a minimal Starlette Request mock."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    req.headers = headers
    return req


# ---------------------------------------------------------------------------
# _get_client_ip
# ---------------------------------------------------------------------------


class TestGetClientIp:
    def test_uses_leftmost_x_forwarded_for(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = _make_request(ip="10.0.0.1", forwarded_for="1.2.3.4, 5.6.7.8")
        assert limiter._get_client_ip(req) == "1.2.3.4"

    def test_strips_whitespace_from_forwarded_for(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = _make_request(forwarded_for="  9.9.9.9  , 10.0.0.1")
        assert limiter._get_client_ip(req) == "9.9.9.9"

    def test_falls_back_to_client_host_when_no_header(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = _make_request(ip="192.168.1.100")
        assert limiter._get_client_ip(req) == "192.168.1.100"

    def test_returns_unknown_when_no_client_and_no_header(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = MagicMock()
        req.client = None
        req.headers = {}
        assert limiter._get_client_ip(req) == "unknown"

    def test_single_ip_in_forwarded_for(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = _make_request(forwarded_for="203.0.113.5")
        assert limiter._get_client_ip(req) == "203.0.113.5"


# ---------------------------------------------------------------------------
# check — within limit
# ---------------------------------------------------------------------------


class TestCheckAllowsUnderLimit:
    def test_single_request_passes(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        req = _make_request()
        limiter.check(req)  # should not raise

    def test_requests_up_to_limit_minus_one_pass(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        req = _make_request()
        for _ in range(2):
            limiter.check(req)  # 2 of 3 — still OK

    def test_exactly_at_limit_raises(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        req = _make_request()
        for _ in range(3):
            limiter.check(req)  # fill bucket
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(req)  # 4th request — over limit
        assert exc_info.value.status_code == 429

    def test_limit_of_one_allows_first_blocks_second(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter.check(req)
        with pytest.raises(HTTPException):
            limiter.check(req)


# ---------------------------------------------------------------------------
# check — 429 details
# ---------------------------------------------------------------------------


class TestCheck429Details:
    def test_raises_http_429(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter.check(req)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(req)
        assert exc_info.value.status_code == 429

    def test_retry_after_header_present(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter.check(req)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(req)
        assert "Retry-After" in exc_info.value.headers
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert 1 <= retry_after <= 61

    def test_retry_after_at_least_1(self) -> None:
        """Even if window is almost expired, Retry-After must be >= 1."""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        req = _make_request()
        # Fill bucket with a timestamp that is almost about to expire
        now = time.monotonic()
        with patch("pulldb.infra.rate_limit.time") as mock_time:
            mock_time.monotonic.return_value = now
            limiter.check(req)
            # Advance almost to window boundary (0.99s into a 1s window)
            mock_time.monotonic.return_value = now + 0.99
            with pytest.raises(HTTPException) as exc_info:
                limiter.check(req)
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert retry_after >= 1

    def test_detail_message_contains_retry_seconds(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter.check(req)
        with pytest.raises(HTTPException) as exc_info:
            limiter.check(req)
        assert "Try again in" in exc_info.value.detail


# ---------------------------------------------------------------------------
# check — sliding window expiry
# ---------------------------------------------------------------------------


class TestCheckSlidingWindow:
    def test_expired_requests_do_not_count(self) -> None:
        """Requests older than window_seconds must not count against the limit."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req = _make_request()
        now = time.monotonic()

        with patch("pulldb.infra.rate_limit.time") as mock_time:
            # t=0: two requests — fill bucket
            mock_time.monotonic.return_value = now
            limiter.check(req)
            limiter.check(req)

            # t=61: window has passed — old entries expire, new requests allowed
            mock_time.monotonic.return_value = now + 61
            limiter.check(req)  # should not raise

    def test_partially_expired_window_enforces_remaining(self) -> None:
        """Only requests still inside the window count."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        req = _make_request()
        now = time.monotonic()

        with patch("pulldb.infra.rate_limit.time") as mock_time:
            # t=0: 2 requests
            mock_time.monotonic.return_value = now
            limiter.check(req)
            limiter.check(req)

            # t=61: those 2 expire; 1 new request passes
            mock_time.monotonic.return_value = now + 61
            limiter.check(req)

            # t=61: 1 more request passes (2 total in window)
            limiter.check(req)

            # t=61: 3rd request in this new window passes (limit=3)
            limiter.check(req)

            # t=61: 4th request in new window should fail
            with pytest.raises(HTTPException):
                limiter.check(req)


# ---------------------------------------------------------------------------
# check — multi-IP isolation
# ---------------------------------------------------------------------------


class TestCheckMultiIpIsolation:
    def test_different_ips_tracked_independently(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req_a = _make_request(ip="10.0.0.1")
        req_b = _make_request(ip="10.0.0.2")

        limiter.check(req_a)  # fills bucket for IP A
        limiter.check(req_b)  # IP B has a separate bucket — should not raise

    def test_exhausted_ip_does_not_block_other_ips(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        req_a = _make_request(ip="1.1.1.1")
        req_b = _make_request(ip="2.2.2.2")

        limiter.check(req_a)
        limiter.check(req_a)  # exhaust IP A

        with pytest.raises(HTTPException):
            limiter.check(req_a)

        # IP B unaffected
        limiter.check(req_b)
        limiter.check(req_b)


# ---------------------------------------------------------------------------
# __call__ — FastAPI DI interface
# ---------------------------------------------------------------------------


class TestCallInterface:
    def test_call_delegates_to_check(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        req = _make_request()
        # __call__ should not raise for first request
        result = limiter(req)
        assert result is None  # returns None like check()

    def test_call_raises_429_when_limit_exceeded(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        req = _make_request()
        limiter(req)  # first call fills bucket
        with pytest.raises(HTTPException) as exc_info:
            limiter(req)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_requests_from_same_ip_do_not_corrupt_bucket(self) -> None:
        """No assertion error or KeyError under concurrent access from 10 threads."""
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        req = _make_request(ip="10.0.0.1")
        errors: list[Exception] = []

        def _do_request() -> None:
            try:
                limiter.check(req)
            except HTTPException:
                pass  # 429 is acceptable
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_do_request) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected exceptions: {errors}"

    def test_concurrent_requests_count_correctly(self) -> None:
        """Exactly max_requests succeed; the rest raise 429."""
        max_req = 20
        limiter = RateLimiter(max_requests=max_req, window_seconds=60)
        req = _make_request(ip="10.1.2.3")
        successes = 0
        failures = 0
        lock = threading.Lock()

        def _request() -> None:
            nonlocal successes, failures
            try:
                limiter.check(req)
                with lock:
                    successes += 1
            except HTTPException:
                with lock:
                    failures += 1

        threads = [threading.Thread(target=_request) for _ in range(max_req + 10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert successes == max_req
        assert failures == 10
