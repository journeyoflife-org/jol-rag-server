# =============================================================================
# Dockerfile — JOL RAG API Service
# Multi-stage build with hardened runtime.
#
# SOC 2 CC8.1 / CIS Docker Benchmark — minimal attack surface
# Trivy scan: docker scout cves or trivy image <image>
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-download embedding model into a portable HF cache.
# Eliminates runtime dependency on HuggingFace Hub availability — if the
# model is not in the local cache the library attempts a download, but
# with the bake this only happens after an explicit model upgrade.
#
# Ref: P2 finding — Deployment Record rag-prod-lt01 2026-08-07
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN HF_HOME=/tmp/model-cache \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# --- Stage 2: Runtime ---
FROM python:3.12-slim AS runtime

# Security: create non-root user
RUN groupadd -r ragapp && useradd -r -g ragapp -d /app -s /sbin/nologin ragapp

# Install only runtime system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get purge -y --auto-remove

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy baked embedding model cache (eliminates HuggingFace runtime dependency)
COPY --from=builder /tmp/model-cache /app/.cache/huggingface

# Copy application source
COPY app/ ./app/
COPY workers/ ./workers/

# Create directories for logs and temp files
RUN mkdir -p /var/log/rag /tmp/rag && \
    chown -R ragapp:ragapp /app /var/log/rag /tmp/rag

# Point HuggingFace libs at the baked cache directory.
# docker-compose may override via environment: if a different cache is needed.
ENV HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface

# Switch to non-root user
USER ragapp

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with uvicorn
ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app", \
            "--host", "0.0.0.0", "--port", "8000", \
            "--workers", "2", "--loop", "uvloop", \
            "--access-log", "--log-level", "info"]
