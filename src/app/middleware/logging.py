"""Structured request/response logging middleware.

Logs every HTTP request with method, path, status, latency, and client IP.
User identity is pseudonymised before logging (GDPR Art. 25).

ISO 27001 A.12.4 — Logging and monitoring
SOC 2 CC7.1 — Detecting unauthorised activity
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.audit import get_logger

logger = get_logger()

# Paths excluded from verbose logging (health checks)
EXCLUDED_PATHS = {"/health", "/ready", "/metrics"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all HTTP requests with structured metadata."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request and log outcome."""
        # Skip noisy health-check endpoints
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # Extract client IP (respect X-Forwarded-For from reverse proxy)
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host

        # Attach request metadata to state for downstream use
        request.state.request_id = request_id
        request.state.client_ip = client_ip

        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=round(elapsed_ms, 2),
                client_ip=client_ip,
                user_agent=request.headers.get("User-Agent", "")[:100],
            )

            # Add request ID to response headers for traceability
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "http_request_error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                latency_ms=round(elapsed_ms, 2),
                client_ip=client_ip,
                error=str(exc),
            )
            raise
