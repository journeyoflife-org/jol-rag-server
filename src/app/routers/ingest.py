"""Document ingestion endpoint.

POST /ingest — Parse, chunk, embed, and store a document.
Requires 'admin' role (RBAC).

SOC 2 CC8.1 — Change management (all ingestion is audited)
GDPR Art. 5(1)(c) — Data minimisation (only embeddings stored in vector DB)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import get_audit_logger
from app.auth import TokenPayload, require_permission
from app.config import Settings, get_settings
from app.middleware.rate_limit import role_rate_limit
from app.models import IngestionStatus, IngestRequest, IngestResponse
from app.services.documents import get_document_service
from app.services.pipeline import get_pipeline

router = APIRouter(tags=["ingestion"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a document into the RAG system",
    description=(
        "Parse, chunk, embed, and store a document. "
        "Supports PDF, DOCX, TXT, and HTML formats. "
        "Requires 'admin' role."
    ),
    dependencies=[
        Depends(require_permission("ingest")),
        Depends(role_rate_limit("ingest")),
    ],
)
async def ingest_document(
    body: IngestRequest,
    request: Request,
    user: Annotated[TokenPayload, Depends(require_permission("ingest"))],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IngestResponse:
    """Ingest a document: parse, chunk, embed, store."""
    audit = get_audit_logger()
    client_ip = getattr(request.state, "client_ip", "unknown")
    doc_service = get_document_service()
    pipeline = get_pipeline()

    try:
        # Resolve document content
        if body.content:
            text = body.content
        elif body.file_path:
            raw_bytes, detected_format = doc_service.load_from_filesystem(body.file_path)
            text = doc_service.parse_document(raw_bytes, detected_format)
            # Store raw document in MinIO
            doc_service.store_raw_document(
                document_id=body.document_id,
                content=raw_bytes,
                filename=body.file_path.split("/")[-1],
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either 'content' or 'file_path' must be provided",
            )

        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document content is empty after parsing",
            )

        # Build metadata
        metadata = {
            "title": body.title,
            "format": body.format.value,
            "retention_flag": body.retention_flag,
            "ingested_by": user.sub,
            **body.metadata,
        }

        # Run ingestion pipeline (chunk + embed + upsert)
        chunks_created = pipeline.ingest_document(
            document_id=body.document_id,
            text=text,
            metadata=metadata,
        )

        # Audit log
        audit.log_event(
            action="document.ingest",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=body.document_id,
            client_ip=client_ip,
            outcome="success",
            details={"chunks": chunks_created, "title": body.title},
        )

        return IngestResponse(
            document_id=body.document_id,
            status=IngestionStatus.COMPLETED,
            chunks_created=chunks_created,
            message=f"Document ingested successfully ({chunks_created} chunks)",
            timestamp=datetime.now(UTC),
        )

    except HTTPException:
        raise
    except FileNotFoundError as exc:
        audit.log_event(
            action="document.ingest",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=body.document_id,
            client_ip=client_ip,
            outcome="failure",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {exc}",
        ) from exc
    except Exception as exc:
        audit.log_event(
            action="document.ingest",
            user_id_pseudo=getattr(request.state, "user_id_pseudo", "unknown"),
            resource_id=body.document_id,
            client_ip=client_ip,
            outcome="failure",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        ) from exc
