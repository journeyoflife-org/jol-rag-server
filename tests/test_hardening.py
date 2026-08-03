"""Tests for security hardening: per-role rate limits and GDPR cache cascade.

Verifies:
- Per-user rate limiting returns 429 when scope capacity is exhausted
- Token bucket semantics (capacity, refill keying)
- GDPR deletion responses include cache_entries_purged field
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.middleware.rate_limit import _ROLE_LIMITERS, TokenBucket


@pytest.fixture
def small_admin_bucket():
    """Replace the admin-scope limiter with a tiny bucket; restore after."""
    original = _ROLE_LIMITERS.get("admin")
    _ROLE_LIMITERS["admin"] = TokenBucket(capacity=2, refill_rate=0.0)
    yield
    if original is None:
        _ROLE_LIMITERS.pop("admin", None)
    else:
        _ROLE_LIMITERS["admin"] = original


class TestTokenBucket:
    """Unit tests for the token bucket primitive."""

    def test_allows_up_to_capacity(self) -> None:
        """Requests up to capacity pass; the next is rejected."""
        bucket = TokenBucket(capacity=3, refill_rate=0.0)
        assert all(bucket.allow("user-a") for _ in range(3))
        assert not bucket.allow("user-a")

    def test_keys_are_independent(self) -> None:
        """Exhausting one key does not affect another."""
        bucket = TokenBucket(capacity=1, refill_rate=0.0)
        assert bucket.allow("user-a")
        assert not bucket.allow("user-a")
        assert bucket.allow("user-b")


class TestPerUserRoleLimiting:
    """Integration tests for the role_rate_limit dependency."""

    def test_admin_endpoint_returns_429_when_exhausted(
        self, client: TestClient, auth_headers: dict, small_admin_bucket: None
    ) -> None:
        """Third admin deletion within the window is rate limited (429)."""
        with (
            patch("app.routers.admin.get_vectorstore_service") as mock_vs,
            patch("app.routers.admin.get_document_service") as mock_ds,
        ):
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_document.return_value = 1
            mock_vs.return_value = mock_vectorstore

            mock_doc_service = MagicMock()
            mock_doc_service.delete_raw_document.return_value = 1
            mock_ds.return_value = mock_doc_service

            for _ in range(2):
                ok = client.delete("/admin/documents/doc-rate-001", headers=auth_headers)
                assert ok.status_code == 200

            limited = client.delete("/admin/documents/doc-rate-001", headers=auth_headers)

        assert limited.status_code == 429
        assert limited.headers.get("Retry-After") == "60"

    def test_unauthenticated_requests_not_subject_to_role_limit(self, client: TestClient) -> None:
        """Missing token yields 401/403 from auth, never 429."""
        response = client.delete("/admin/documents/doc-rate-002")
        assert response.status_code in (401, 403)


class TestGDPRCacheCascade:
    """GDPR deletion must report cache purge counts."""

    def test_document_deletion_reports_cache_purge(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Deletion response includes cache_entries_purged field."""
        with (
            patch("app.routers.admin.get_vectorstore_service") as mock_vs,
            patch("app.routers.admin.get_document_service") as mock_ds,
        ):
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_document.return_value = 3
            mock_vs.return_value = mock_vectorstore

            mock_doc_service = MagicMock()
            mock_doc_service.delete_raw_document.return_value = 1
            mock_ds.return_value = mock_doc_service

            response = client.delete("/admin/documents/doc-cache-001", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "cache_entries_purged" in data
        assert data["cache_entries_purged"] == 0

    def test_user_deletion_reports_cache_purge(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """User erasure response includes cache_entries_purged field."""
        with patch("app.routers.admin.get_vectorstore_service") as mock_vs:
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_user.return_value = 4
            mock_vs.return_value = mock_vectorstore

            response = client.delete("/admin/users/user-cache-1", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "cache_entries_purged" in data
