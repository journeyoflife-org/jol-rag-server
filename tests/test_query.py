"""Tests for the RAG query pipeline endpoint.

Verifies:
- Successful query returns answer with sources
- Query validation (empty question rejected)
- Service unavailability returns 503
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestQueryEndpoint:
    """Test POST /query endpoint behaviour."""

    def test_query_returns_answer(self, client: TestClient, auth_headers: dict) -> None:
        """Valid query returns 200 with answer and sources."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            from datetime import UTC, datetime

            from app.models import QueryResponse, SourceReference

            mock_pipe = MagicMock()
            mock_pipe.query.return_value = QueryResponse(
                answer="Baptism is the first sacrament of initiation.",
                sources=[
                    SourceReference(
                        document_id="doc-001",
                        chunk_id="chunk-1",
                        title="Catechism",
                        score=0.92,
                        content_preview="Baptism is...",
                    )
                ],
                model="mistral-7b-instruct",
                latency_ms=1234.5,
                timestamp=datetime.now(UTC),
            )
            mock_pipeline.return_value = mock_pipe

            response = client.post(
                "/query",
                json={"question": "What is baptism?", "top_k": 3},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["document_id"] == "doc-001"

    def test_query_empty_question_returns_422(self, client: TestClient, auth_headers: dict) -> None:
        """Empty question string returns 422 validation error."""
        response = client.post(
            "/query",
            json={"question": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_query_missing_question_returns_422(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Missing question field returns 422."""
        response = client.post("/query", json={}, headers=auth_headers)
        assert response.status_code == 422

    def test_query_top_k_validation(self, client: TestClient, auth_headers: dict) -> None:
        """top_k > 20 returns 422 validation error."""
        response = client.post(
            "/query",
            json={"question": "test", "top_k": 100},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_query_service_unavailable_returns_503(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """ConnectionError from backend returns 503."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            mock_pipe = MagicMock()
            mock_pipe.query.side_effect = ConnectionError("Qdrant unavailable")
            mock_pipeline.return_value = mock_pipe

            response = client.post(
                "/query",
                json={"question": "test query"},
                headers=auth_headers,
            )

        assert response.status_code == 503
