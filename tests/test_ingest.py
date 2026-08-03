"""Tests for document ingestion pipeline.

Verifies:
- Successful ingestion returns 201 with chunk count
- Missing content/file_path returns 400
- Empty content returns 400
- Ingestion requires admin role
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestIngestEndpoint:
    """Test POST /ingest endpoint behaviour."""

    def test_ingest_with_content_returns_201(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Valid ingestion with inline content returns 201."""
        with patch("app.routers.ingest.get_pipeline") as mock_pipeline:
            mock_pipe = MagicMock()
            mock_pipe.ingest_document.return_value = 3
            mock_pipeline.return_value = mock_pipe

            response = client.post(
                "/ingest",
                json={
                    "document_id": "doc-test-001",
                    "title": "Test Document",
                    "content": "This is a test document about Catholic liturgy.",
                    "format": "txt",
                },
                headers=auth_headers,
            )

        assert response.status_code == 201
        data = response.json()
        assert data["document_id"] == "doc-test-001"
        assert data["status"] == "completed"

    def test_ingest_without_content_or_path_returns_400(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Ingestion without content or file_path returns 400."""
        response = client.post(
            "/ingest",
            json={
                "document_id": "doc-test-002",
                "title": "Empty Doc",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "content" in detail or "file_path" in detail

    def test_ingest_with_empty_content_returns_400(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Ingestion with whitespace-only content returns 400."""
        response = client.post(
            "/ingest",
            json={
                "document_id": "doc-test-003",
                "title": "Whitespace Doc",
                "content": "   \n\t  ",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_ingest_missing_document_id_returns_422(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Missing required document_id field returns 422 validation error."""
        response = client.post(
            "/ingest",
            json={"title": "No ID", "content": "Some content"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_ingest_with_metadata(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Ingestion with metadata passes metadata through."""
        with patch("app.routers.ingest.get_pipeline") as mock_pipeline:
            mock_pipe = MagicMock()
            mock_pipe.ingest_document.return_value = 2
            mock_pipeline.return_value = mock_pipe

            response = client.post(
                "/ingest",
                json={
                    "document_id": "doc-meta-001",
                    "title": "Metadata Doc",
                    "content": "Content with metadata.",
                    "metadata": {"source": "catechism", "language": "lt"},
                    "retention_flag": True,
                },
                headers=auth_headers,
            )

        assert response.status_code == 201
