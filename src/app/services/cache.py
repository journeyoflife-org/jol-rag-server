"""Query cache service — Redis-backed with GDPR cascade purge.

Caches RAG query responses to reduce LLM load. Maintains secondary
indexes (per document, per pseudonymised user) so GDPR Art. 17 erasure
can cascade into cached data.

All operations are fault-tolerant: a Redis outage degrades gracefully
(cache miss / zero purge count) and is logged — it never blocks the
primary deletion of authoritative data in Qdrant/MinIO.

GDPR Art. 17 — Right to erasure (cached data included)
SOC 2 CC6.1 — Logical access (pseudonymised keys only)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from prometheus_client import Counter

from app.audit import get_logger
from app.config import Settings, get_settings

# --- Prometheus metrics ---
CACHE_HITS = Counter("rag_cache_hits_total", "Query cache hits")
CACHE_MISSES = Counter("rag_cache_misses_total", "Query cache misses")
CACHE_PURGED = Counter(
    "rag_cache_entries_purged_total",
    "Cache entries purged (GDPR erasure or TTL)",
    ["reason"],
)

# Key prefixes — namespaced to avoid collisions in shared Redis
_QUERY_PREFIX = "rag:query:"
_DOC_INDEX_PREFIX = "rag:idx:doc:"
_USER_INDEX_PREFIX = "rag:idx:user:"

logger = get_logger()


class CacheService:
    """Redis-backed query cache with GDPR cascade purge."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._redis = None

    def _get_redis(self):
        """Lazy-initialise the Redis connection."""
        if self._redis is None:
            import redis as redis_lib

            self._redis = redis_lib.from_url(
                self._settings.redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis

    @staticmethod
    def query_cache_key(question: str, top_k: int, filters: dict[str, Any] | None) -> str:
        """Deterministic cache key for a query (content-addressed)."""
        digest_input = json.dumps(
            {"question": question, "top_k": top_k, "filters": filters or {}},
            sort_keys=True,
        )
        digest = hashlib.sha256(digest_input.encode()).hexdigest()[:32]
        return f"{_QUERY_PREFIX}{digest}"

    def get_cached_query(self, cache_key: str) -> dict[str, Any] | None:
        """Return cached response dict or None (miss or failure)."""
        if not self._settings.rag_cache_enabled:
            return None
        try:
            raw = self._get_redis().get(cache_key)
            if raw is None:
                CACHE_MISSES.inc()
                return None
            CACHE_HITS.inc()
            return json.loads(raw)
        except Exception as exc:
            logger.warning("cache_get_failed", error=str(exc))
            return None

    def set_cached_query(
        self,
        cache_key: str,
        response: dict[str, Any],
        document_ids: list[str],
        user_id_pseudo: str | None = None,
    ) -> None:
        """Cache a query response and update secondary indexes.

        Args:
            cache_key: Content-addressed cache key.
            response: Serialised QueryResponse.
            document_ids: Source document IDs referenced (for GDPR index).
            user_id_pseudo: Pseudonymised requesting user (for GDPR index).
        """
        if not self._settings.rag_cache_enabled:
            return
        try:
            redis = self._get_redis()
            ttl = self._settings.rag_cache_ttl_seconds
            redis.set(cache_key, json.dumps(response), ex=ttl)
            # Secondary indexes for GDPR cascade purge (same TTL)
            for doc_id in document_ids:
                redis.sadd(f"{_DOC_INDEX_PREFIX}{doc_id}", cache_key)
                redis.expire(f"{_DOC_INDEX_PREFIX}{doc_id}", ttl)
            if user_id_pseudo:
                redis.sadd(f"{_USER_INDEX_PREFIX}{user_id_pseudo}", cache_key)
                redis.expire(f"{_USER_INDEX_PREFIX}{user_id_pseudo}", ttl)
        except Exception as exc:
            logger.warning("cache_set_failed", error=str(exc))

    def _purge_index(self, index_key: str) -> int:
        """Delete all cache keys referenced by an index set, then the set."""
        redis = self._get_redis()
        members = redis.smembers(index_key)
        purged = 0
        for member in members:
            key = member.decode() if isinstance(member, bytes) else str(member)
            purged += int(redis.delete(key) or 0)
        redis.delete(index_key)
        return purged

    def purge_document(self, document_id: str) -> int:
        """GDPR Art. 17 — purge all cached responses referencing a document.

        Returns:
            Number of cache entries purged (0 on failure — logged, never raised).
        """
        try:
            purged = self._purge_index(f"{_DOC_INDEX_PREFIX}{document_id}")
            if purged:
                CACHE_PURGED.labels(reason="gdpr_document").inc(purged)
                logger.info(
                    "cache_purged_for_document",
                    document_id=document_id,
                    entries=purged,
                )
            return purged
        except Exception as exc:
            logger.error(
                "cache_purge_failed",
                document_id=document_id,
                error=str(exc),
            )
            return 0

    def purge_user(self, user_id_pseudo: str) -> int:
        """GDPR Art. 17 — purge all cached responses issued to a user.

        Args:
            user_id_pseudo: Pseudonymised user identifier (HMAC-derived).

        Returns:
            Number of cache entries purged (0 on failure — logged, never raised).
        """
        try:
            purged = self._purge_index(f"{_USER_INDEX_PREFIX}{user_id_pseudo}")
            if purged:
                CACHE_PURGED.labels(reason="gdpr_user").inc(purged)
                logger.info(
                    "cache_purged_for_user",
                    user_id_pseudo=user_id_pseudo,
                    entries=purged,
                )
            return purged
        except Exception as exc:
            logger.error(
                "cache_purge_failed",
                user_id_pseudo=user_id_pseudo,
                error=str(exc),
            )
            return 0


# Module-level singleton
_service: CacheService | None = None


def get_cache_service() -> CacheService:
    """Return the module-level cache service singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = CacheService()
    return _service
