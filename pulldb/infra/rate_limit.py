"""In-process per-IP sliding-window rate limiter for auth endpoints.

Uses a sliding window algorithm: counts requests within the last N seconds.
Thread-safe via ``threading.Lock``. No external dependencies (no Redis).

Designed for internal-tool auth endpoints where the universe of client IPs
is small and bounded — not suitable as a general-purpose CDN-scale limiter.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status


logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window per-IP rate limiter usable as a FastAPI dependency.

    Maintains a per-IP deque of request timestamps.  On each call, evicts
    timestamps older than ``window_seconds`` then checks the remaining count
    against ``max_requests``.  Raises HTTP 429 with a ``Retry-After`` header
    when the limit is exceeded.

    Example — applied as a FastAPI route dependency::

        _login_limiter = RateLimiter(max_requests=10, window_seconds=60, name="login")

        @app.post("/api/auth/login")
        async def login(
            _: None = Depends(_login_limiter),
            ...
        ) -> ...:
            ...

    Args:
        max_requests: Maximum requests allowed from one IP within the window.
        window_seconds: Sliding window length in seconds.
        name: Label used in log messages (e.g. ``"login"``, ``"register"``).
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
        name: str = "endpoint",
    ) -> None:
        """Initialise the limiter with the given parameters."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, honouring ``X-Forwarded-For`` from a trusted proxy.

        Takes the *leftmost* entry from ``X-Forwarded-For`` (the original
        client address as set by the first proxy in the chain).  Falls back
        to ``request.client.host`` if the header is absent.

        Args:
            request: The incoming Starlette request.

        Returns:
            Best-effort client IP string; ``"unknown"`` if unavailable.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> None:
        """Apply the rate limit to *request*.

        Evicts expired timestamps, then either records the new request or
        raises HTTP 429 with a ``Retry-After`` header calculated from when
        the oldest in-window request will expire.

        Args:
            request: The incoming FastAPI/Starlette request.

        Raises:
            HTTPException: 429 Too Many Requests when the per-IP limit is exceeded.
        """
        ip = self._get_client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            if ip not in self._buckets:
                self._buckets[ip] = deque()
            bucket = self._buckets[ip]

            # Evict timestamps outside the sliding window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                # Time until the oldest request ages out of the window
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                logger.warning(
                    "rate_limit_exceeded ip=%s endpoint=%s count=%d limit=%d retry_after=%ds",
                    ip,
                    self.name,
                    len(bucket),
                    self.max_requests,
                    retry_after,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)

    def __call__(self, request: Request) -> None:
        """FastAPI dependency interface — called automatically by the DI system."""
        self.check(request)
