"""Structured audit logging for compliance.

Every access, modification, and administrative action is logged with:
- Pseudonymised user identity (HMAC-SHA256)
- Client IP address
- Action performed
- UTC timestamp (ISO 8601)
- Resource identifier
- Outcome (success/failure)

SOC 2 CC6.1 — Credential masking in log output
SOC 2 CC7.1 / CC7.2 — Monitoring and alerting
ISO 27001 A.12.4 — Logging and monitoring
GDPR Art. 30 — Records of processing activities
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.config import Settings, get_settings

# --- Credential masking (SOC 2 CC6.1 / GDPR Art. 32) ---

# Matches scheme://user:password@host patterns
_CRED_URL_RE = re.compile(
    r"(redis(?:s)?|amqp(?:s)?|http(?:s)?|mongodb(?:\+srv)?|mysql|postgresql)" r"://[^@\s]+@[^@\s]*",
    re.IGNORECASE,
)

# Known secret key names — values are masked in any log event
_SECRET_KEYS = frozenset(
    {
        "redis_url",
        "database_url",
        "elasticsearch_url",
        "jwt_secret",
        "hmac_salt",
        "minio_root_password",
        "qdrant_api_key",
        "redis_password",
        "minio_encryption_key",
        "api_key",
        "password",
        "secret",
    }
)

# Fields that are structurally safe to recurse into (metadata dicts)
_SAFE_RECURSE_KEYS = frozenset({"details", "extra", "metadata", "payload"})


def _mask_secret_value(value: str) -> str:
    """Redact credential patterns within a string value."""
    if _CRED_URL_RE.search(value):
        return _CRED_URL_RE.sub("[REDACTED_URL]", value)
    return value


def _mask_event_dict(
    event_dict: dict[str, Any],
    *,
    top_level: bool = True,
) -> dict[str, Any]:
    """Recursively mask secrets in a structlog event dict.

    At the top level, known secret key names have their values replaced.
    Nested dicts are only traversed for URL-pattern credentials (field
    names are not checked to avoid false positives in payload data).
    """
    for key in list(event_dict):
        val = event_dict[key]
        if isinstance(val, str):
            if top_level and key.lower() in _SECRET_KEYS:
                event_dict[key] = "[REDACTED]"
            else:
                masked = _mask_secret_value(val)
                if masked != val:
                    event_dict[key] = "[REDACTED_URL]"
        elif isinstance(val, dict) and (top_level or key in _SAFE_RECURSE_KEYS):
            _mask_event_dict(val, top_level=False)
    return event_dict


def _mask_secrets_processor(
    _logger: Any,
    _method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that redacts credentials before serialisation.

    Catches:
    - Known secret field names (``redis_url``, ``jwt_secret``, etc.)
    - URL-embedded credentials (``redis://:pass@host``)

    SOC 2 CC6.1 / GDPR Art. 32 — prevents credential leakage in logs.
    """
    return _mask_event_dict(event_dict)


def _configure_structlog(settings: Settings) -> None:
    """Configure structlog for JSON output to stdout and audit file."""
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _mask_secrets_processor,  # Redact credentials before rendering
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

        # Mask credentials before writing to append-only audit file
        masked_record = _mask_event_dict(dict(record))

        # Write to audit file (append-only)
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(masked_record, ensure_ascii=False) + "\n")
        except OSError:
            # Fallback: log to stdout if file write fails (already masked)
            self._logger.error("audit_write_failed", record=masked_record)

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
