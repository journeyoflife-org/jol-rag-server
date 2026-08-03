"""Document service — parsing, chunking, and MinIO storage.

Supports PDF, DOCX, TXT, and HTML formats.
Raw documents stored in MinIO with SSE-S3 encryption.
Only embeddings and metadata are stored in the vector DB (data minimisation).

GDPR Art. 5(1)(c) — Data minimisation
GDPR Art. 32 — Encryption of personal data
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from prometheus_client import Counter

from app.audit import get_logger
from app.config import Settings, get_settings

# --- Prometheus metrics ---
DOCUMENTS_INGESTED = Counter(
    "rag_documents_ingested_total",
    "Total documents ingested",
    ["format"],
)

logger = get_logger()


class DocumentService:
    """Document parsing, chunking, and encrypted storage."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._minio_client = None

    def _get_minio(self):
        """Lazy-initialise MinIO client."""
        if self._minio_client is None:
            from minio import Minio

            self._minio_client = Minio(
                self._settings.minio_endpoint,
                access_key=self._settings.minio_root_user,
                secret_key=self._settings.minio_root_password,
                secure=self._settings.minio_use_ssl,
            )
            # Ensure bucket exists
            if not self._minio_client.bucket_exists(self._settings.minio_bucket_documents):
                self._minio_client.make_bucket(self._settings.minio_bucket_documents)
                logger.info("minio_bucket_created", bucket=self._settings.minio_bucket_documents)
        return self._minio_client

    def parse_document(self, content: bytes, format: str) -> str:
        """Parse a document into plain text.

        Args:
            content: Raw file bytes.
            format: One of 'pdf', 'docx', 'txt', 'html'.

        Returns:
            Extracted plain text.

        Raises:
            ValueError: If format is unsupported.
        """
        if format == "txt":
            return content.decode("utf-8", errors="replace")

        if format == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)

        if format == "docx":
            from docx import Document

            doc = Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)

        if format == "html":
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer"]):
                element.decompose()
            return soup.get_text(separator="\n", strip=True)

        raise ValueError(f"Unsupported document format: {format}")

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[dict[str, Any]]:
        """Split text into overlapping chunks.

        Uses a recursive character splitter approach with paragraph/sentence
        boundaries for semantic coherence.

        Args:
            text: The full document text.
            chunk_size: Maximum characters per chunk (default from settings).
            chunk_overlap: Character overlap between chunks (default from settings).

        Returns:
            List of dicts with 'text' and 'chunk_index' keys.
        """
        size = chunk_size or self._settings.chunk_size
        overlap = chunk_overlap or self._settings.chunk_overlap

        if not text.strip():
            return []

        chunks: list[dict[str, Any]] = []
        # Split by paragraphs first, then by sentences within paragraphs
        paragraphs = text.split("\n\n")
        current_chunk = ""
        chunk_index = 0

        for paragraph in paragraphs:
            paragraph_text = paragraph.strip()
            if not paragraph_text:
                continue

            if len(current_chunk) + len(paragraph_text) + 2 <= size:
                current_chunk = f"{current_chunk}\n\n{paragraph_text}".strip()
            else:
                # Save current chunk if non-empty
                if current_chunk:
                    chunks.append({"text": current_chunk, "chunk_index": chunk_index})
                    chunk_index += 1

                # Handle paragraphs larger than chunk_size
                if len(paragraph_text) > size:
                    # Split by sentences
                    sentences = paragraph_text.replace(". ", ".\n").split("\n")
                    current_chunk = ""
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) + 1 <= size:
                            current_chunk = f"{current_chunk} {sentence}".strip()
                        else:
                            if current_chunk:
                                chunks.append({"text": current_chunk, "chunk_index": chunk_index})
                                chunk_index += 1
                            # Hard split if single sentence exceeds chunk_size
                            if len(sentence) > size:
                                for i in range(0, len(sentence), size - overlap):
                                    sub = sentence[i : i + size]
                                    chunks.append({"text": sub, "chunk_index": chunk_index})
                                    chunk_index += 1
                                current_chunk = ""
                            else:
                                current_chunk = sentence
                # Apply overlap from previous chunk
                elif chunks and overlap > 0:
                    prev_text = chunks[-1]["text"]
                    overlap_text = prev_text[-overlap:] if len(prev_text) > overlap else ""
                    current_chunk = f"{overlap_text}\n\n{paragraph_text}".strip()
                else:
                    current_chunk = paragraph_text

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append({"text": current_chunk, "chunk_index": chunk_index})

        return chunks

    def store_raw_document(
        self,
        document_id: str,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store raw document in MinIO with server-side encryption.

        Args:
            document_id: Unique document identifier.
            content: Raw file bytes.
            filename: Original filename.
            content_type: MIME type.

        Returns:
            Object path in MinIO.
        """
        client = self._get_minio()
        object_name = f"{document_id}/{filename}"

        client.put_object(
            self._settings.minio_bucket_documents,
            object_name,
            io.BytesIO(content),
            length=len(content),
            content_type=content_type,
        )

        logger.info("document_stored", document_id=document_id, object=object_name)
        return object_name

    def delete_raw_document(self, document_id: str) -> int:
        """Delete all objects for a document_id prefix (GDPR Art. 17).

        Returns:
            Number of objects deleted.
        """
        client = self._get_minio()
        prefix = f"{document_id}/"
        objects = client.list_objects(
            self._settings.minio_bucket_documents, prefix=prefix, recursive=True
        )

        count = 0
        for obj in objects:
            client.remove_object(self._settings.minio_bucket_documents, obj.object_name)
            count += 1

        if count > 0:
            logger.info("raw_documents_deleted", document_id=document_id, count=count)
        return count

    def load_from_filesystem(self, file_path: str) -> tuple[bytes, str]:
        """Load a document from the raw_docs directory.

        Args:
            file_path: Relative path within the raw_docs directory.

        Returns:
            Tuple of (file bytes, detected format).

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file extension is unsupported.
        """
        base_dir = Path(self._settings.rag_raw_docs_dir)
        full_path = (base_dir / file_path).resolve()

        # Security: prevent path traversal
        if not str(full_path).startswith(str(base_dir.resolve())):
            raise ValueError("Path traversal detected — access denied")

        if not full_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        content = full_path.read_bytes()
        suffix = full_path.suffix.lower().lstrip(".")

        format_map = {"pdf": "pdf", "docx": "docx", "txt": "txt", "html": "html", "htm": "html"}
        if suffix not in format_map:
            raise ValueError(f"Unsupported file extension: .{suffix}")

        return content, format_map[suffix]

    def health_check(self) -> bool:
        """Check MinIO connectivity."""
        try:
            client = self._get_minio()
            client.list_buckets()
            return True
        except Exception:
            return False


# Module-level singleton
_service: DocumentService | None = None


def get_document_service() -> DocumentService:
    """Return the module-level document service singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = DocumentService()
    return _service
