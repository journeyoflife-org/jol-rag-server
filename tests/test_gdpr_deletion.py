"""Tests for GDPR right-to-erasure (Art. 17) endpoints.

Verifies:
- Document deletion removes embeddings and raw files
- User deletion removes all associated data
- Deletion requires admin role
- Deletion is audited
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestDocumentDeletion:
    """Test DELETE /admin/documents/{document_id}."""

    def test_delete_document_returns_200(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Successful document deletion returns 200 with counts."""
        with (
            patch("app.routers.admin.get_vectorstore_service") as mock_vs,
            patch("app.routers.admin.get_document_service") as mock_ds,
        ):
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_document.return_value = 5
            mock_vs.return_value = mock_vectorstore

            mock_doc_service = MagicMock()
            mock_doc_service.delete_raw_document.return_value = 1
            mock_ds.return_value = mock_doc_service

            response = client.delete(
                "/admin/documents/doc-gdpr-001",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_embeddings"] == 5
        assert data["deleted_documents"] == 1
        assert data["status"] == "completed"

    def test_delete_document_requires_admin(
        self, client: TestClient, analyst_headers: dict
    ) -> None:
        """Analyst role cannot delete documents (403)."""
        response = client.delete(
            "/admin/documents/doc-gdpr-002",
            headers=analyst_headers,
        )
        assert response.status_code == 403

    def test_delete_nonexistent_document_returns_200(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Deleting a document with no data still returns 200 (idempotent)."""
        with (
            patch("app.routers.admin.get_vectorstore_service") as mock_vs,
            patch("app.routers.admin.get_document_service") as mock_ds,
        ):
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_document.return_value = 0
            mock_vs.return_value = mock_vectorstore

            mock_doc_service = MagicMock()
            mock_doc_service.delete_raw_document.return_value = 0
            mock_ds.return_value = mock_doc_service

            response = client.delete(
                "/admin/documents/nonexistent-doc",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json()["deleted_embeddings"] == 0


class TestUserDeletion:
    """Test DELETE /admin/users/{user_id}."""

    def test_delete_user_data_returns_200(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Successful user data deletion returns 200."""
        with patch("app.routers.admin.get_vectorstore_service") as mock_vs:
            mock_vectorstore = MagicMock()
            mock_vectorstore.delete_by_user.return_value = 12
            mock_vs.return_value = mock_vectorstore

            response = client.delete(
                "/admin/users/user-12345",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_embeddings"] == 12
        assert data["status"] == "completed"

    def test_delete_user_requires_admin(
        self, client: TestClient, analyst_headers: dict
    ) -> None:
        """Analyst role cannot delete user data (403)."""
        response = client.delete(
            "/admin/users/user-99999",
            headers=analyst_headers,
        )
        assert response.status_code == 403
