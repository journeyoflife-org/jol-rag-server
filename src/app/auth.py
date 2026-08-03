"""JWT authentication and RBAC authorisation.

Implements OAuth2-compatible JWT validation for the pilot phase.
HS256 for pilot; structure supports RS256/OIDC migration.

SOC 2 CC6.1 — Logical access controls
ISO 27001 A.9.2 — User access management
GDPR Art. 25 — Data protection by design (pseudonymisation)
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings


class Role(str, Enum):
    """User roles with least-privilege access."""

    ADMIN = "admin"
    ANALYST = "analyst"


# Role hierarchy: admin inherits analyst permissions
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {"ingest", "query", "delete", "admin"},
    Role.ANALYST: {"query"},
}

_bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload:
    """Decoded JWT token payload."""

    def __init__(self, sub: str, role: Role, exp: datetime, iss: str, aud: str) -> None:
        self.sub = sub
        self.role = role
        self.exp = exp
        self.iss = iss
        self.aud = aud

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        return datetime.now(UTC) > self.exp


def pseudonymise_user_id(user_id: str, settings: Settings) -> str:
    """HMAC-SHA256 pseudonymisation of user identifiers.

    GDPR Art. 25 — ensures PII is not stored in logs or analytics.
    The salt is a server-side secret; without it, the hash is irreversible.
    """
    if not settings.rag_hmac_salt:
        raise ValueError("HMAC salt not configured — cannot pseudonymise user IDs")
    return hmac.new(
        settings.rag_hmac_salt.encode(),
        user_id.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def decode_token(token: str, settings: Settings) -> TokenPayload:
    """Decode and validate a JWT token.

    Raises:
        HTTPException: If token is invalid, expired, or has wrong issuer/audience.
    """
    try:
        payload = jwt.decode(
            token,
            settings.rag_jwt_secret,
            algorithms=[settings.rag_jwt_algorithm],
            issuer=settings.rag_jwt_issuer,
            audience=settings.rag_jwt_audience,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    role_str = payload.get("role", "")
    try:
        role = Role(role_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unknown role: {role_str}",
        ) from exc

    return TokenPayload(
        sub=payload["sub"],
        role=role,
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        iss=payload["iss"],
        aud=payload["aud"],
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPayload:
    """FastAPI dependency: extract and validate the current user from JWT."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_payload = decode_token(credentials.credentials, settings)

    if token_payload.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach pseudonymised user ID to request state for audit logging
    request.state.user_id_pseudo = pseudonymise_user_id(token_payload.sub, settings)
    request.state.user_role = token_payload.role.value

    return token_payload


def require_permission(permission: str):
    """Dependency factory: enforce RBAC permission check.

    Usage:
        @router.post("/ingest", dependencies=[Depends(require_permission("ingest"))])
    """

    async def _check_permission(
        user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        allowed = ROLE_PERMISSIONS.get(user.role, set())
        if permission not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' lacks permission '{permission}'",
            )
        return user

    return _check_permission
