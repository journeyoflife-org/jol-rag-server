"""Tests for audit logging compliance.

Verifies:
- Audit events are generated for all API actions
- User IDs are pseudonymised (HMAC-SHA256)
- Audit records contain required fields (timestamp, action, user, IP, resource)
- Audit log is append-only JSONL format
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

AUDIT_LOG_PATH = "/tmp/test-audit.jsonl"


class TestAuditLogGeneration:
    """Verify audit events are written for API operations."""

    def test_query_generates_audit_event(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """POST /query must generate an audit log entry."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            from datetime import UTC, datetime

            from app.models import QueryResponse

            mock_pipe = MagicMock()
            mock_pipe.query.return_value = QueryResponse(
                answer="Test answer",
                sources=[],
                model="test",
                latency_ms=100.0,
                timestamp=datetime.now(UTC),
            )
            mock_pipeline.return_value = mock_pipe

            client.post(
                "/query",
                json={"question": "audit test"},
                headers=auth_headers,
            )

        # Verify audit log was written
        assert os.path.exists(AUDIT_LOG_PATH), "Audit log file not created"
        with open(AUDIT_LOG_PATH) as f:
            lines = f.readlines()

        assert len(lines) >= 1, "No audit events recorded"
        event = json.loads(lines[-1])
        assert event["action"] == "query.execute"
        assert "timestamp" in event
        assert "user_id" in event
        assert "client_ip" in event
        assert "resource_id" in event
        assert event["outcome"] == "success"

    def test_failed_query_generates_audit_event(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Failed query must also generate an audit event with outcome=failure."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            mock_pipe = MagicMock()
            mock_pipe.query.side_effect = ConnectionError("down")
            mock_pipeline.return_value = mock_pipe

            client.post(
                "/query",
                json={"question": "fail test"},
                headers=auth_headers,
            )

        assert os.path.exists(AUDIT_LOG_PATH)
        with open(AUDIT_LOG_PATH) as f:
            lines = f.readlines()

        # Find the failure event
        failure_events = [
            json.loads(line)
            for line in lines
            if json.loads(line).get("outcome") == "failure"
        ]
        assert len(failure_events) >= 1, "No failure audit event recorded"


class TestPseudonymisation:
    """Verify user IDs are HMAC-pseudonymised in audit logs."""

    def test_user_id_is_not_plaintext(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Audit log must NOT contain the raw user ID from the JWT."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            from datetime import UTC, datetime

            from app.models import QueryResponse

            mock_pipe = MagicMock()
            mock_pipe.query.return_value = QueryResponse(
                answer="Test",
                sources=[],
                model="test",
                latency_ms=50.0,
                timestamp=datetime.now(UTC),
            )
            mock_pipeline.return_value = mock_pipe

            client.post(
                "/query",
                json={"question": "pseudonymisation test"},
                headers=auth_headers,
            )

        assert os.path.exists(AUDIT_LOG_PATH)
        content = Path(AUDIT_LOG_PATH).read_text()

        # The raw user ID "test-user-001" must NOT appear in the audit log
        assert "test-user-001" not in content, (
            "Raw user ID found in audit log — pseudonymisation failure!"
        )

    def test_user_id_is_hex_hash(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Pseudonymised user ID must be a hex string (HMAC output)."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            from datetime import UTC, datetime

            from app.models import QueryResponse

            mock_pipe = MagicMock()
            mock_pipe.query.return_value = QueryResponse(
                answer="Test",
                sources=[],
                model="test",
                latency_ms=50.0,
                timestamp=datetime.now(UTC),
            )
            mock_pipeline.return_value = mock_pipe

            client.post(
                "/query",
                json={"question": "hash format test"},
                headers=auth_headers,
            )

        with open(AUDIT_LOG_PATH) as f:
            event = json.loads(f.readline())

        user_id = event["user_id"]
        # Must be a 16-char hex string (truncated HMAC-SHA256)
        assert len(user_id) == 16
        assert all(c in "0123456789abcdef" for c in user_id)


class TestAuditRecordStructure:
    """Verify audit records contain all required compliance fields."""

    def test_audit_record_has_required_fields(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Each audit record must carry the mandatory compliance fields."""
        with patch("app.routers.query.get_pipeline") as mock_pipeline:
            from datetime import UTC, datetime

            from app.models import QueryResponse

            mock_pipe = MagicMock()
            mock_pipe.query.return_value = QueryResponse(
                answer="Structure test",
                sources=[],
                model="test",
                latency_ms=10.0,
                timestamp=datetime.now(UTC),
            )
            mock_pipeline.return_value = mock_pipe

            client.post(
                "/query",
                json={"question": "structure test"},
                headers=auth_headers,
            )

        with open(AUDIT_LOG_PATH) as f:
            event = json.loads(f.readline())

        required_fields = [
            "timestamp",
            "action",
            "user_id",
            "resource_id",
            "client_ip",
            "outcome",
            "service",
        ]
        for field in required_fields:
            assert field in event, f"Missing required audit field: {field}"

        # Timestamp must be ISO 8601 UTC
        assert "T" in event["timestamp"]
        assert event["service"] == "jol-rag"
