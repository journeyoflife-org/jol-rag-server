"""Admin endpoints — GDPR right-to-erasure and data management.

DELETE /admin/documents/{document_id} — Remove all data for a document.
DELETE /admin/users/{user_id} — Remove all data for a user.

Requires 'admin' role (RBAC).

GDPR Art. 17 — Right to erasure ('right to be forgotten')
GDPR Art. 5(1)(e) — Storage limitation
SOC 2 CC6.1 — Logical access (admin-only operations)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import get_audit_logger
from app.auth import TokenPayload, pseudonymise_user_id, require_permission
from app.config import get_settings
from app.middleware.rate_limit import role_rate_limit
from app.models import DeletionResponse
from app.services.cache import get_cache_service
from app.services.documents import get_document_service
from app.services.vectorstore import get_vectorstore_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete(
    "/documents/{document_id}",
    response_model=DeletionResponse,
    summary="Delete all data for a document (GDPR Art. 17)",
    description=(
        "Removes all vector embeddings, metadata, and raw document storage "
        "for the specified document_id. This operation is irreversible. "
        "Requires 'admin' role."
    ),
    dependencies=[
        Depends(require_permission("delete")),
        Depends(role_rate_limit("admin")),
    ],
)
async def delete_document(
    document_id: str,
    request: Request,
    user: Annotated[TokenPayload, Depends(require_permission("delete"))],
) -> DeletionResponse:
    """Delete all traces of a document (GDPR right to erasure)."""
    audit = get_audit_logger()
    client_ip = getattr(request.state, "client_ip", "unknown")
    vectorstore = get_vectorstore_service()
    doc_service = get_document_service()
    cache = get_cache_service()

    try:
        # Delete embeddings from Qdrant
        deleted_embeddings = vectorstore.delete_by_document(document_id)

        # Delete raw documents from MinIO
        deleted_documents = doc_service.delete_raw_document(document_id)

        # GDPR cascade: purge cached query responses referencing this document
        cache_entries_purged = cache.purge_document(document_id)

        # Audit log — critical compliance event
        audit.log_event(
            action="gdpr.document_delete",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=document_id,
            client_ip=client_ip,
            outcome="success",
            details={
                "deleted_embeddings": deleted_embeddings,
                "deleted_documents": deleted_documents,
                "cache_entries_purged": cache_entries_purged,
                "requested_by": user.sub,
            },
        )

        return DeletionResponse(
            deleted_embeddings=deleted_embeddings,
            deleted_documents=deleted_documents,
            cache_entries_purged=cache_entries_purged,
            status="completed",
            message=(
                f"Document '{document_id}' fully erased ({deleted_embeddings} embeddings, "
                f"{deleted_documents} files, {cache_entries_purged} cache entries)"
            ),
            timestamp=datetime.now(UTC),
        )

    except Exception as exc:
        audit.log_event(
            action="gdpr.document_delete",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=document_id,
            client_ip=client_ip,
            outcome="failure",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deletion failed: {exc}",
        ) from exc


@router.delete(
    "/users/{user_id}",
    response_model=DeletionResponse,
    summary="Delete all data for a user (GDPR Art. 17)",
    description=(
        "Removes all vector embeddings and metadata associated with the "
        "specified user_id. This operation is irreversible. "
        "Requires 'admin' role."
    ),
    dependencies=[
        Depends(require_permission("delete")),
        Depends(role_rate_limit("admin")),
    ],
)
async def delete_user_data(
    user_id: str,
    request: Request,
    user: Annotated[TokenPayload, Depends(require_permission("delete"))],
) -> DeletionResponse:
    """Delete all data associated with a user (GDPR right to erasure)."""
    audit = get_audit_logger()
    client_ip = getattr(request.state, "client_ip", "unknown")
    vectorstore = get_vectorstore_service()
    cache = get_cache_service()

    try:
        deleted_embeddings = vectorstore.delete_by_user(user_id)

        # GDPR cascade: purge cached responses issued to this user.
        # Cache indexes are keyed by pseudonymised ID (GDPR Art. 25).
        try:
            target_pseudo = pseudonymise_user_id(user_id, get_settings())
        except ValueError:
            target_pseudo = user_id
        cache_entries_purged = cache.purge_user(target_pseudo)

        # Audit log — critical compliance event
        audit.log_event(
            action="gdpr.user_delete",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=f"user:{user_id}",
            client_ip=client_ip,
            outcome="success",
            details={
                "deleted_embeddings": deleted_embeddings,
                "cache_entries_purged": cache_entries_purged,
                "requested_by": user.sub,
            },
        )

        return DeletionResponse(
            deleted_embeddings=deleted_embeddings,
            deleted_documents=0,
            cache_entries_purged=cache_entries_purged,
            status="completed",
            message=(
                f"User '{user_id}' data erased ({deleted_embeddings} embeddings, "
                f"{cache_entries_purged} cache entries)"
            ),
            timestamp=datetime.now(UTC),
        )

    except Exception as exc:
        audit.log_event(
            action="gdpr.user_delete",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=f"user:{user_id}",
            client_ip=client_ip,
            outcome="failure",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"User data deletion failed: {exc}",
        ) from exc
