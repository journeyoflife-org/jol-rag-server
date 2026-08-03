"""Structured audit logging for compliance.

Every access, modification, and administrative action is logged with:
- Pseudonymised user identity (HMAC-SHA256)
- Client IP address
- Action performed
- UTC timestamp (ISO 8601)
- Resource identifier
- Outcome (success/failure)

SOC 2 CC7.1 / CC7.2 — Monitoring and alerting
ISO 27001 A.12.4 — Logging and monitoring
GDPR Art. 30 — Records of processing activities
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.config import Settings, get_settings


def _configure_structlog(settings: Settings) -> None:
    """Configure structlog for JSON output to stdout and audit file."""
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return a configured structured logger."""
    return structlog.get_logger("jol-rag")


class AuditLogger:
    """Append-only audit trail writer.

    Writes JSONL records to the configured audit log path.
    Each record is immutable once written (append-only file).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log_path = Path(self._settings.rag_audit_log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = get_logger()

    def log_event(
        self,
        action: str,
        user_id_pseudo: str,
        resource_id: str,
        client_ip: str,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Write an audit event to the append-only log.

        Args:
            action: The action performed (e.g., "document.ingest", "query.execute").
            user_id_pseudo: HMAC-pseudonymised user identifier.
            resource_id: Identifier of the affected resource.
            client_ip: Client IP address from the request.
            outcome: "success" or "failure".
            details: Additional structured metadata.
        """
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "user_id": user_id_pseudo,
            "resource_id": resource_id,
            "client_ip": client_ip,
            "outcome": outcome,
            "service": "jol-rag",
            "environment": self._settings.rag_environment,
        }
        if details:
            record["details"] = details

        # Write to audit file (append-only)
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # Fallback: log to stdout if file write fails
            self._logger.error("audit_write_failed", record=record)

        # Also emit via structlog for centralised log shipping
        self._logger.info(
            "audit",
            audit_action=action,
            audit_user=user_id_pseudo,
            audit_resource=resource_id,
            audit_outcome=outcome,
        )


# Module-level singleton
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Return the module-level audit logger singleton."""
    global _audit_logger  # noqa: PLW0603
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
