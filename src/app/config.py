"""Application configuration via environment variables.

All secrets are injected via environment variables — never hard-coded.
SOC 2 CC6.1 / ISO 27001 A.8.24 — Secrets management.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the RAG service.

    All values are sourced from environment variables prefixed with RAG_
    or unprefixed for service-specific settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    rag_environment: str = "production"
    rag_log_level: str = "INFO"
    rag_audit_log_path: Path = Path("/var/log/rag/audit.jsonl")
    rag_raw_docs_dir: Path = Path("/data/raw_docs")

    # --- JWT Authentication ---
    rag_jwt_secret: str = ""
    rag_jwt_algorithm: str = "HS256"
    rag_jwt_issuer: str = "jol-rag-pilot"
    rag_jwt_audience: str = "jol-rag-services"
    rag_jwt_expiry_minutes: int = 60

    # --- HMAC Pseudonymisation (GDPR Art. 25) ---
    rag_hmac_salt: str = ""

    # --- Qdrant ---
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_collection: str = "jol-documents"

    # --- Embedding Model ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # --- LLM (Ollama) ---
    ollama_endpoint: str = "http://10.30.30.10:11434/v1"
    ollama_model: str = "mistral-7b-instruct"
    ollama_timeout: int = 120
    ollama_max_tokens: int = 2048
    ollama_temperature: float = 0.3

    # --- MinIO ---
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = ""
    minio_root_password: str = ""
    minio_bucket_documents: str = "jol-documents"
    minio_use_ssl: bool = False

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"

    # --- Rate Limiting (global, per client IP) ---
    rag_rate_limit_requests: int = 100
    rag_rate_limit_window_seconds: int = 60

    # --- Rate Limiting (per authenticated user, per role scope) ---
    rag_rate_limit_query_per_min: int = 100
    rag_rate_limit_ingest_per_min: int = 10
    rag_rate_limit_admin_per_min: int = 20

    # --- Internal mTLS (service-to-service) ---
    rag_internal_tls_enabled: bool = False
    rag_tls_ca_cert: Path | None = None
    rag_tls_client_cert: Path | None = None
    rag_tls_client_key: Path | None = None

    # --- Query Cache (Redis) ---
    rag_cache_enabled: bool = True
    rag_cache_ttl_seconds: int = 900

    # --- GDPR Compliance ---
    rag_embedding_ttl_days: int = 90
    rag_deletion_grace_period_days: int = 30

    # --- Chunking ---
    chunk_size: int = 512
    chunk_overlap: int = 50

    # --- Resilience ---
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
