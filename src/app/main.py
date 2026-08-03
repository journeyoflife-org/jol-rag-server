"""JOL RAG Service — FastAPI application entrypoint.

Production-ready Retrieval-Augmented Generation API for the Journey of Life
platform. Serves document ingestion, semantic query, and GDPR data management.

Compliance: SOC 2 Type II / GDPR (EU 2016/679) / ISO 27001:2022
Deployment: rag-prod-lt01 (10.40.40.10), VLAN 40, Ubuntu 24.04 LTS
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.audit import _configure_structlog, get_logger
from app.config import get_settings
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import admin, health, ingest, query


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialise and teardown resources."""
    settings = get_settings()
    _configure_structlog(settings)
    logger = get_logger()

    logger.info(
        "rag_service_starting",
        environment=settings.rag_environment,
        qdrant_host=settings.qdrant_host,
        ollama_endpoint=settings.ollama_endpoint,
        embedding_model=settings.embedding_model,
    )

    # Ensure Qdrant collection exists
    try:
        from app.services.vectorstore import get_vectorstore_service

        vectorstore = get_vectorstore_service()
        vectorstore.ensure_collection()
    except Exception as exc:
        logger.warning("qdrant_init_deferred", error=str(exc))

    yield

    logger.info("rag_service_stopping")


# --- Application factory ---
app = FastAPI(
    title="JOL RAG Service",
    description=(
        "Production-ready Retrieval-Augmented Generation API for the "
        "Journey of Life (JOL) Roman Catholic Digital Mission Platform. "
        "Pilot deployment: Lithuania (rag-prod-lt01)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --- Middleware (order matters: outermost first) ---
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS: restrict to internal origins only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://10.40.40.0/24"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# --- Routers ---
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(admin.router)
