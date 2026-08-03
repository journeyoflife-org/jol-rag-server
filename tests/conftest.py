"""Pytest fixtures for JOL RAG Service tests.

Provides test client, mock services, and JWT token generation.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import numpy as np
import pytest
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ["RAG_ENVIRONMENT"] = "test"
os.environ["RAG_JWT_SECRET"] = "test-secret-key-for-unit-tests-only"
os.environ["RAG_JWT_ALGORITHM"] = "HS256"
os.environ["RAG_JWT_ISSUER"] = "jol-rag-pilot"
os.environ["RAG_JWT_AUDIENCE"] = "jol-rag-services"
os.environ["RAG_HMAC_SALT"] = "test-hmac-salt-for-pseudonymisation"
os.environ["RAG_AUDIT_LOG_PATH"] = "/tmp/test-audit.jsonl"
os.environ["RAG_RAW_DOCS_DIR"] = "/tmp/test-raw-docs"
os.environ["QDRANT_HOST"] = "localhost"
os.environ["QDRANT_PORT"] = "6333"
os.environ["QDRANT_API_KEY"] = "test-qdrant-key"
os.environ["MINIO_ENDPOINT"] = "localhost:9000"
os.environ["MINIO_ROOT_USER"] = "test-user"
os.environ["MINIO_ROOT_PASSWORD"] = "test-password"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["OLLAMA_ENDPOINT"] = "http://localhost:11434/v1"

JWT_SECRET = "test-secret-key-for-unit-tests-only"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "jol-rag-pilot"
JWT_AUDIENCE = "jol-rag-services"


def generate_test_token(
    role: str = "admin", sub: str = "test-user-001", expired: bool = False
) -> str:
    """Generate a JWT token for testing."""
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "role": role,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=-1 if expired else 1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@pytest.fixture
def admin_token() -> str:
    """JWT token with admin role."""
    return generate_test_token(role="admin")


@pytest.fixture
def analyst_token() -> str:
    """JWT token with analyst role."""
    return generate_test_token(role="analyst")


@pytest.fixture
def expired_token() -> str:
    """Expired JWT token."""
    return generate_test_token(expired=True)


@pytest.fixture
def auth_headers(admin_token: str) -> dict[str, str]:
    """Authorization headers with admin token."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def analyst_headers(analyst_token: str) -> dict[str, str]:
    """Authorization headers with analyst token."""
    return {"Authorization": f"Bearer {analyst_token}"}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI test client with mocked external services."""
    with (
        patch("app.services.vectorstore.VectorStoreService._get_client") as mock_qdrant,
        patch("app.services.documents.DocumentService._get_minio") as mock_minio,
        patch("app.services.llm.LLMService._get_client") as mock_llm,
        patch("app.services.embeddings._load_model") as mock_model,
        patch("app.services.cache.CacheService._get_redis") as mock_redis,
    ):
        # Configure mocks
        mock_qdrant_client = MagicMock()
        mock_qdrant_client.get_collections.return_value = MagicMock(collections=[])
        mock_qdrant_client.query_points.return_value = MagicMock(points=[])
        mock_qdrant.return_value = mock_qdrant_client

        mock_minio_client = MagicMock()
        mock_minio_client.bucket_exists.return_value = True
        mock_minio.return_value = mock_minio_client

        mock_llm_client = MagicMock()
        mock_llm_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Test answer"))],
            usage=MagicMock(completion_tokens=5),
        )
        mock_llm.return_value = mock_llm_client

        mock_embedding_model = MagicMock()
        mock_embedding_model.encode.return_value = np.array([[0.1] * 384])
        mock_model.return_value = mock_embedding_model

        # Redis cache mock: empty cache, purge finds nothing by default
        mock_redis_client = MagicMock()
        mock_redis_client.get.return_value = None
        mock_redis_client.smembers.return_value = set()
        mock_redis_client.delete.return_value = 0
        mock_redis.return_value = mock_redis_client

        from app.main import app

        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def cleanup_audit_log():
    """Clean up test audit log after each test."""
    yield
    audit_path = "/tmp/test-audit.jsonl"
    if os.path.exists(audit_path):
        os.remove(audit_path)
