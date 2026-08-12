"""Vector store service — Qdrant client with resilience patterns.

Implements circuit breaker and exponential backoff for fault tolerance.
API-key authentication for access control.

SOC 2 CC7.1 — System monitoring
ISO 27001 A.12.6 — Technical vulnerability management
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Histogram
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.audit import get_logger
from app.config import Settings, get_settings

# --- Prometheus metrics ---
QDRANT_LATENCY = Histogram(
    "rag_qdrant_operation_duration_seconds",
    "Qdrant operation latency",
    ["operation"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
QDRANT_ERRORS = Counter(
    "rag_qdrant_errors_total",
    "Total Qdrant operation errors",
    ["operation"],
)

logger = get_logger()


class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    States: CLOSED (normal) -> OPEN (failing) -> HALF_OPEN (testing).
    """

    def __init__(self, threshold: int = 5, timeout: float = 60.0) -> None:
        self._threshold = threshold
        self._timeout = timeout
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"

    @property
    def state(self) -> str:
        """Return current circuit state, transitioning OPEN -> HALF_OPEN if timeout elapsed."""
        if self._state == "open":
            if time.monotonic() - self._last_failure_time > self._timeout:
                self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call; open circuit if threshold exceeded."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._threshold:
            self._state = "open"
            logger.warning(
                "circuit_breaker_opened",
                failures=self._failure_count,
                timeout_s=self._timeout,
            )

    def allow_request(self) -> bool:
        """Check if a request is allowed through the circuit."""
        state = self.state
        if state == "closed":
            return True
        if state == "half_open":
            return True  # Allow one test request
        return False


class VectorStoreService:
    """Qdrant vector database operations with resilience."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: QdrantClient | None = None
        self._circuit = CircuitBreaker(
            threshold=self._settings.circuit_breaker_threshold,
            timeout=self._settings.circuit_breaker_timeout,
        )

    def _get_client(self) -> QdrantClient:
        """Lazy-initialise Qdrant client.

        When internal TLS is enabled the REST transport uses HTTPS and
        verifies the server certificate against the internal CA. Otherwise
        HTTPS is explicitly disabled: qdrant-client silently upgrades to
        HTTPS whenever an API key is supplied, which breaks connections to
        plaintext endpoints (SSL WRONG_VERSION_NUMBER).
        """
        if self._client is None:
            kwargs: dict[str, Any] = {
                "host": self._settings.qdrant_host,
                "port": self._settings.qdrant_port,
                "api_key": self._settings.qdrant_api_key or None,
                "timeout": 30,
            }
            if self._settings.rag_internal_tls_enabled:
                kwargs["https"] = True
                if self._settings.rag_tls_ca_cert:
                    kwargs["verify"] = str(self._settings.rag_tls_ca_cert)
            else:
                kwargs["https"] = False
            self._client = QdrantClient(**kwargs)
        return self._client

    def ensure_collection(self) -> None:
        """Create the collection if it does not exist (idempotent)."""
        client = self._get_client()
        collections = [c.name for c in client.get_collections().collections]
        if self._settings.qdrant_collection not in collections:
            client.create_collection(
                collection_name=self._settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=self._settings.embedding_dimension,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "collection_created",
                collection=self._settings.qdrant_collection,
                dimension=self._settings.embedding_dimension,
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def upsert_chunks(
        self,
        document_id: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Upsert document chunks with embeddings into Qdrant.

        Args:
            document_id: Parent document identifier.
            chunks: List of chunk dicts with 'text' and 'chunk_index' keys.
            embeddings: Corresponding embedding vectors.
            metadata: Additional metadata to store with each point.

        Returns:
            Number of points upserted.
        """
        if not self._circuit.allow_request():
            QDRANT_ERRORS.labels(operation="upsert").inc()
            raise ConnectionError("Circuit breaker is open — Qdrant unavailable")

        client = self._get_client()
        now = datetime.now(UTC).isoformat()

        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{chunk['chunk_index']}"))
            payload = {
                "document_id": document_id,
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "title": metadata.get("title", "") if metadata else "",
                "created_at": now,
                "retention_flag": metadata.get("retention_flag", False) if metadata else False,
                **(metadata or {}),
            }
            points.append(PointStruct(id=point_id, vector=embedding, payload=payload))

        try:
            with QDRANT_LATENCY.labels(operation="upsert").time():
                client.upsert(
                    collection_name=self._settings.qdrant_collection,
                    points=points,
                )
            self._circuit.record_success()
            logger.info("chunks_upserted", document_id=document_id, count=len(points))
            return len(points)
        except Exception as exc:
            self._circuit.record_failure()
            QDRANT_ERRORS.labels(operation="upsert").inc()
            logger.error("upsert_failed", document_id=document_id, error=str(exc))
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors in the collection.

        Args:
            query_embedding: The query vector.
            top_k: Number of results to return.
            filters: Metadata filters to apply.

        Returns:
            List of result dicts with 'id', 'score', 'payload' keys.
        """
        if not self._circuit.allow_request():
            QDRANT_ERRORS.labels(operation="search").inc()
            raise ConnectionError("Circuit breaker is open — Qdrant unavailable")

        client = self._get_client()

        qdrant_filter = None
        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        try:
            with QDRANT_LATENCY.labels(operation="search").time():
                results = client.query_points(
                    collection_name=self._settings.qdrant_collection,
                    query=query_embedding,
                    limit=top_k,
                    query_filter=qdrant_filter,
                    with_payload=True,
                )
            self._circuit.record_success()
            return [
                {
                    "id": str(point.id),
                    "score": point.score,
                    "payload": point.payload,
                }
                for point in results.points
            ]
        except Exception as exc:
            self._circuit.record_failure()
            QDRANT_ERRORS.labels(operation="search").inc()
            logger.error("search_failed", error=str(exc))
            raise

    def delete_by_document(self, document_id: str) -> int:
        """Delete all points for a given document_id (GDPR Art. 17).

        Returns:
            Number of points deleted.
        """
        client = self._get_client()
        filter_cond = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        )

        # Count before deletion for audit
        count_result = client.count(
            collection_name=self._settings.qdrant_collection,
            count_filter=filter_cond,
        )
        count = count_result.count

        if count > 0:
            client.delete(
                collection_name=self._settings.qdrant_collection,
                points_selector=filter_cond,
            )
            logger.info("document_embeddings_deleted", document_id=document_id, count=count)

        return count

    def delete_by_user(self, user_id: str) -> int:
        """Delete all points associated with a user_id (GDPR Art. 17).

        Returns:
            Number of points deleted.
        """
        client = self._get_client()
        filter_cond = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])

        count_result = client.count(
            collection_name=self._settings.qdrant_collection,
            count_filter=filter_cond,
        )
        count = count_result.count

        if count > 0:
            client.delete(
                collection_name=self._settings.qdrant_collection,
                points_selector=filter_cond,
            )
            logger.info("user_embeddings_deleted", user_id=user_id, count=count)

        return count

    def health_check(self) -> bool:
        """Check Qdrant connectivity."""
        try:
            client = self._get_client()
            client.get_collections()
            return True
        except Exception:
            return False


# Module-level singleton
_service: VectorStoreService | None = None


def get_vectorstore_service() -> VectorStoreService:
    """Return the module-level vector store service singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = VectorStoreService()
    return _service
