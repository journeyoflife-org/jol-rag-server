"""Tests for authentication and RBAC enforcement.

Verifies:
- Unauthenticated requests are rejected (401)
- Expired tokens are rejected (401)
- Invalid tokens are rejected (401)
- Role-based access control is enforced (403)
- Valid tokens grant appropriate access
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import generate_test_token


class TestUnauthenticatedAccess:
    """Verify that unauthenticated requests are rejected."""

    def test_query_without_token_returns_401(self, client: TestClient) -> None:
        """POST /query without Authorization header must return 401."""
        response = client.post("/query", json={"question": "test"})
        assert response.status_code == 401

    def test_ingest_without_token_returns_401(self, client: TestClient) -> None:
        """POST /ingest without Authorization header must return 401."""
        response = client.post(
            "/ingest",
            json={"document_id": "doc-1", "title": "Test", "content": "Hello"},
        )
        assert response.status_code == 401

    def test_admin_delete_without_token_returns_401(self, client: TestClient) -> None:
        """DELETE /admin/documents/{id} without token must return 401."""
        response = client.delete("/admin/documents/doc-1")
        assert response.status_code == 401


class TestExpiredTokens:
    """Verify that expired tokens are rejected."""

    def test_expired_token_returns_401(self, client: TestClient, expired_token: str) -> None:
        """Expired JWT must return 401."""
        headers = {"Authorization": f"Bearer {expired_token}"}
        response = client.post("/query", json={"question": "test"}, headers=headers)
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()


class TestInvalidTokens:
    """Verify that malformed/forged tokens are rejected."""

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        """Random string as token must return 401."""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = client.post("/query", json={"question": "test"}, headers=headers)
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, client: TestClient) -> None:
        """Token signed with wrong secret must return 401."""
        from datetime import UTC, datetime, timedelta

        import jwt as pyjwt

        payload = {
            "sub": "attacker",
            "role": "admin",
            "iss": "jol-rag-pilot",
            "aud": "jol-rag-services",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        forged = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {forged}"}
        response = client.post("/query", json={"question": "test"}, headers=headers)
        assert response.status_code == 401


class TestRBAC:
    """Verify role-based access control enforcement."""

    def test_analyst_cannot_ingest(self, client: TestClient, analyst_headers: dict) -> None:
        """Analyst role must be denied access to /ingest (403)."""
        response = client.post(
            "/ingest",
            json={"document_id": "doc-1", "title": "Test", "content": "Hello"},
            headers=analyst_headers,
        )
        assert response.status_code == 403

    def test_analyst_cannot_delete(self, client: TestClient, analyst_headers: dict) -> None:
        """Analyst role must be denied access to /admin/documents (403)."""
        response = client.delete("/admin/documents/doc-1", headers=analyst_headers)
        assert response.status_code == 403

    def test_analyst_can_query(self, client: TestClient, analyst_headers: dict) -> None:
        """Analyst role must be allowed to access /query."""
        response = client.post(
            "/query",
            json={"question": "What is baptism?"},
            headers=analyst_headers,
        )
        # Should not be 401 or 403 (may be 500 due to mocked services)
        assert response.status_code not in (401, 403)

    def test_unknown_role_returns_403(self, client: TestClient) -> None:
        """Token with unknown role must return 403."""
        token = generate_test_token(role="superuser")
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post("/query", json={"question": "test"}, headers=headers)
        assert response.status_code == 403


class TestHealthEndpointsNoAuth:
    """Health endpoints must not require authentication."""

    def test_health_no_auth(self, client: TestClient) -> None:
        """GET /health must work without authentication."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_metrics_no_auth(self, client: TestClient) -> None:
        """GET /metrics must work without authentication."""
        response = client.get("/metrics")
        assert response.status_code == 200
