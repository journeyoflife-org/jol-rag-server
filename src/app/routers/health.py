"""Health, readiness, and metrics endpoints.

GET /health — Liveness probe (Kubernetes-compatible)
GET /ready — Readiness probe (checks downstream dependencies)
GET /metrics — Prometheus metrics exporter

ISO 27001 A.12.1 — Operational procedures
SOC 2 CC7.1 — System monitoring
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.models import HealthResponse

router = APIRouter(tags=["health"])

# Track application start time for uptime calculation
_start_time = time.monotonic()

APP_VERSION = "1.0.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description=(
        "Returns 200 if the application process is running. Kubernetes liveness probe compatible."
    ),
)
async def health_check() -> HealthResponse:
    """Basic liveness check — no dependency verification."""
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        uptime_seconds=round(time.monotonic() - _start_time, 2),
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description=(
        "Checks connectivity to all downstream services (Qdrant, MinIO, Ollama). "
        "Returns 200 only if all dependencies are reachable. "
        "Kubernetes readiness probe compatible."
    ),
)
async def readiness_check() -> HealthResponse:
    """Deep readiness check — verifies all downstream dependencies."""
    from app.services.documents import get_document_service
    from app.services.llm import get_llm_service
    from app.services.vectorstore import get_vectorstore_service

    services: dict[str, str] = {}

    # Check Qdrant
    vectorstore = get_vectorstore_service()
    services["qdrant"] = "up" if vectorstore.health_check() else "down"

    # Check MinIO
    doc_service = get_document_service()
    services["minio"] = "up" if doc_service.health_check() else "down"

    # Check Ollama LLM
    llm_service = get_llm_service()
    services["ollama"] = "up" if llm_service.health_check() else "down"

    all_healthy = all(v == "up" for v in services.values())

    return HealthResponse(
        status="ready" if all_healthy else "degraded",
        version=APP_VERSION,
        uptime_seconds=round(time.monotonic() - _start_time, 2),
        services=services,
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description="Exposes application metrics in Prometheus exposition format.",
    response_class=PlainTextResponse,
)
async def metrics() -> PlainTextResponse:
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
