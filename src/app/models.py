"""Pydantic request/response schemas for the RAG API.

OpenAPI 3.0 compatible — all models are auto-documented by FastAPI.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# --- Enums ---


class DocumentFormat(str, Enum):
    """Supported document formats for ingestion."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    HTML = "html"


class IngestionStatus(str, Enum):
    """Status of a document ingestion job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# --- Request Models ---


class IngestRequest(BaseModel):
    """Request to ingest a document into the RAG system."""

    document_id: str = Field(
        ...,
        description="Unique document identifier (UUID recommended)",
        min_length=1,
        max_length=256,
        examples=["doc-2026-001"],
    )
    title: str = Field(
        ...,
        description="Human-readable document title",
        min_length=1,
        max_length=512,
    )
    content: str | None = Field(
        None,
        description="Raw text content (alternative to file upload)",
    )
    file_path: str | None = Field(
        None,
        description="Path to file in the raw_docs directory",
    )
    format: DocumentFormat = Field(
        default=DocumentFormat.TXT,
        description="Document format for parsing",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (source, author, language, etc.)",
    )
    retention_flag: bool = Field(
        default=False,
        description="If true, exempt from 90-day auto-purge (GDPR Art. 5(1)(e))",
    )


class QueryRequest(BaseModel):
    """Request to query the RAG pipeline."""

    question: str = Field(
        ...,
        description="Natural language question",
        min_length=1,
        max_length=2048,
        examples=["What does the Catechism say about baptism?"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of context chunks to retrieve",
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata filters for vector search",
    )
    include_sources: bool = Field(
        default=True,
        description="Include source document references in response",
    )


class DeletionRequest(BaseModel):
    """GDPR Art. 17 — Right to erasure request."""

    document_id: str | None = Field(
        None,
        description="Delete all embeddings and metadata for this document",
    )
    user_id: str | None = Field(
        None,
        description="Delete all data associated with this user",
    )
    reason: str = Field(
        default="gdpr_request",
        description="Reason for deletion (audit trail)",
    )


# --- Response Models ---


class IngestResponse(BaseModel):
    """Response from document ingestion."""

    document_id: str
    status: IngestionStatus
    chunks_created: int = 0
    message: str = ""
    timestamp: datetime


class SourceReference(BaseModel):
    """Reference to a source document chunk used in generation."""

    document_id: str
    chunk_id: str
    title: str
    score: float
    content_preview: str = Field(max_length=200)


class QueryResponse(BaseModel):
    """Response from the RAG query pipeline."""

    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0
    timestamp: datetime


class DeletionResponse(BaseModel):
    """Response from GDPR deletion operation."""

    deleted_embeddings: int = 0
    deleted_documents: int = 0
    cache_entries_purged: int = 0
    status: str = "completed"
    message: str = ""
    timestamp: datetime


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    uptime_seconds: float
    services: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_code: str = "INTERNAL_ERROR"
    timestamp: datetime
