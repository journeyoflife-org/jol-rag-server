"""Token-bucket rate limiter middleware.

Protects against abuse and ensures fair resource allocation.
Configurable via environment variables.

SOC 2 CC6.6 — Boundary protection
ISO 27001 A.13.1 — Network security management
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import get_settings

# Paths excluded from rate limiting
EXCLUDED_PATHS = {"/health", "/ready", "/metrics"}


class TokenBucket:
    """Simple token-bucket rate limiter per client IP."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_time)

    def allow(self, key: str) -> bool:
        """Check if a request from the given key is allowed."""
        now = time.monotonic()

        if key not in self._buckets:
            self._buckets[key] = (self._capacity - 1, now)
            return True

        tokens, last_time = self._buckets[key]
        elapsed = now - last_time

        # Refill tokens based on elapsed time
        tokens = min(self._capacity, tokens + elapsed * self._refill_rate)

        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True

        self._buckets[key] = (tokens, now)
        return False

    def cleanup(self, max_age: float = 300.0) -> None:
        """Remove stale entries older than max_age seconds."""
        now = time.monotonic()
        stale = [k for k, (_, t) in self._buckets.items() if now - t > max_age]
        for k in stale:
            del self._buckets[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply token-bucket rate limiting per client IP."""

    def __init__(self, app, **kwargs) -> None:  # noqa: ANN001
        super().__init__(app, **kwargs)
        settings = get_settings()
        capacity = settings.rag_rate_limit_requests
        window = settings.rag_rate_limit_window_seconds
        refill_rate = capacity / window  # tokens per second
        self._bucket = TokenBucket(capacity=capacity, refill_rate=refill_rate)
        self._last_cleanup = time.monotonic()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Check rate limit before processing request."""
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # Periodic cleanup of stale entries
        now = time.monotonic()
        if now - self._last_cleanup > 60:
            self._bucket.cleanup()
            self._last_cleanup = now

        # Identify client
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host
        key = client_ip or "unknown"

        if not self._bucket.allow(key):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please retry later.",
                    "error_code": "RATE_LIMITED",
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


# --- Per-user, role-aware rate limiting (FastAPI dependency) ---
#
# Applied after authentication so limits are keyed on the pseudonymised
# user identity rather than shared client IPs (NAT, load balancers).
# Defaults: 100 queries/min, 10 ingests/min, 20 admin ops/min.

_ROLE_LIMITERS: dict[str, TokenBucket] = {}


def _scope_capacity(scope: str) -> int:
    """Resolve the per-minute capacity for a rate-limit scope."""
    settings = get_settings()
    capacities = {
        "query": settings.rag_rate_limit_query_per_min,
        "ingest": settings.rag_rate_limit_ingest_per_min,
        "admin": settings.rag_rate_limit_admin_per_min,
    }
    return capacities.get(scope, settings.rag_rate_limit_requests)


def _get_scope_limiter(scope: str) -> TokenBucket:
    """Return (creating if needed) the token bucket for a scope."""
    if scope not in _ROLE_LIMITERS:
        capacity = _scope_capacity(scope)
        _ROLE_LIMITERS[scope] = TokenBucket(
            capacity=capacity,
            refill_rate=capacity / 60.0,
        )
    return _ROLE_LIMITERS[scope]


def role_rate_limit(scope: str):
    """Dependency factory: per-user rate limit for an endpoint scope.

    Must be declared AFTER the authentication dependency so that
    ``request.state.user_id_pseudo`` is populated.

    Usage:
        dependencies=[
            Depends(require_permission("query")),
            Depends(role_rate_limit("query")),
        ]
    """

    async def _enforce(request: Request) -> None:
        bucket = _get_scope_limiter(scope)
        key = getattr(request.state, "user_id_pseudo", None)
        if not key:  # Fallback for unauthenticated edge cases
            key = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if not key and request.client:
                key = request.client.host
            key = f"ip:{key or 'unknown'}"

        if not bucket.allow(f"{scope}:{key}"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Per-user rate limit exceeded. Please retry later.",
                headers={"Retry-After": "60"},
            )

    return _enforce
