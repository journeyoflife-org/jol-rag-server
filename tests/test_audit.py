"""Tests for audit logging compliance.

Verifies:
- Audit events are generated for all API actions
- User IDs are pseudonymised (HMAC-SHA256)
- Audit records contain required fields (timestamp, action, user, IP, resource)
- Audit log is append-only JSONL format
- Credentials are masked in stdout and JSONL output (SOC 2 CC6.1)
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

    def test_query_generates_audit_event(self, client: TestClient, auth_headers: dict) -> None:
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
            json.loads(line) for line in lines if json.loads(line).get("outcome") == "failure"
        ]
        assert len(failure_events) >= 1, "No failure audit event recorded"


class TestPseudonymisation:
    """Verify user IDs are HMAC-pseudonymised in audit logs."""

    def test_user_id_is_not_plaintext(self, client: TestClient, auth_headers: dict) -> None:
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
        assert (
            "test-user-001" not in content
        ), "Raw user ID found in audit log — pseudonymisation failure!"

    def test_user_id_is_hex_hash(self, client: TestClient, auth_headers: dict) -> None:
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

    def test_audit_record_has_required_fields(self, client: TestClient, auth_headers: dict) -> None:
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


class TestCredentialMasking:
    """Verify credentials are redacted from log output (SOC 2 CC6.1 / GDPR Art. 32).

    Regression coverage for the 2026-08-07 REDIS_URL exposure incident:
    secrets must never reach stdout logs or the append-only audit JSONL.
    """

    def test_url_embedded_credentials_are_redacted(self) -> None:
        """REDIS_URL-style values must be replaced with [REDACTED_URL]."""
        from app.audit import _mask_secrets_processor

        event = {
            "event": "cache_connect_failed",
            "url": "redis://:super-secret-password@redis:6379/0",
        }
        masked = _mask_secrets_processor(None, "error", event)

        assert "super-secret-password" not in json.dumps(masked)
        assert masked["url"] == "[REDACTED_URL]"

    def test_known_secret_key_names_are_redacted(self) -> None:
        """Fields named like secrets must be masked regardless of value shape."""
        from app.audit import _mask_secrets_processor

        event = {
            "event": "config_loaded",
            "redis_url": "redis://redis:6379/0",  # no credential, still masked
            "jwt_secret": "eyJhbGciOiJIUzI1NiJ9.payload",
            "qdrant_api_key": "qd-12345",
        }
        masked = _mask_secrets_processor(None, "info", event)

        assert masked["redis_url"] == "[REDACTED]"
        assert masked["jwt_secret"] == "[REDACTED]"
        assert masked["qdrant_api_key"] == "[REDACTED]"

    def test_nested_details_dict_is_masked(self) -> None:
        """URL credentials inside nested metadata dicts must also be caught."""
        from app.audit import _mask_event_dict

        event = {
            "event": "upsert_failed",
            "details": {"error": "cannot reach redis://:leaked-pw@redis:6379/0"},
        }
        masked = _mask_event_dict(event)

        assert "leaked-pw" not in json.dumps(masked)
        assert masked["details"]["error"] == "[REDACTED_URL]"

    def test_non_secret_values_pass_through(self) -> None:
        """Masking must not corrupt operational (non-secret) log fields."""
        from app.audit import _mask_secrets_processor

        event = {
            "event": "query_executed",
            "document_id": "doc-123",
            "status": 200,
            "path": "/query",
        }
        masked = _mask_secrets_processor(None, "info", event)

        assert masked["document_id"] == "doc-123"
        assert masked["status"] == 200
        assert masked["path"] == "/query"

    def test_audit_jsonl_write_path_masks_credentials(self) -> None:
        """AuditLogger.log_event must mask secrets before writing the JSONL file."""
        from app.audit import AuditLogger

        audit = AuditLogger()
        audit.log_event(
            action="test.masking",
            user_id_pseudo="abc123def456",
            resource_id="res-1",
            client_ip="10.0.0.1",
            details={"url": "redis://:file-leak-secret@redis:6379/0"},
        )

        content = Path(AUDIT_LOG_PATH).read_text()
        assert "file-leak-secret" not in content
        event = json.loads(content.splitlines()[-1])
        assert event["details"]["url"] == "[REDACTED_URL]"
