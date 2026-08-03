"""Embedding service — local sentence-transformers inference.

Uses all-MiniLM-L6-v2 (384-dim) for CPU-friendly, GDPR-compliant embeddings.
No external API calls — all inference runs locally on rag-prod-lt01.

GDPR Art. 32 — Processing security (no data leaves the EU/EEA)
"""

from __future__ import annotations

import time
from functools import lru_cache

import numpy as np
from prometheus_client import Counter, Histogram

from app.audit import get_logger
from app.config import Settings, get_settings

# --- Prometheus metrics ---
EMBEDDING_LATENCY = Histogram(
    "rag_embedding_duration_seconds",
    "Time to generate embeddings",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
EMBEDDING_COUNT = Counter(
    "rag_embeddings_generated_total",
    "Total number of embeddings generated",
)

logger = get_logger()


@lru_cache
def _load_model(model_name: str):
    """Load the sentence-transformers model (cached singleton).

    Lazy-loaded on first use to avoid startup delay if not needed.
    """
    from sentence_transformers import SentenceTransformer

    logger.info("loading_embedding_model", model=model_name)
    start = time.perf_counter()
    model = SentenceTransformer(model_name, device="cpu")
    elapsed = time.perf_counter() - start
    logger.info("embedding_model_loaded", model=model_name, load_time_s=round(elapsed, 2))
    return model


class EmbeddingService:
    """Generate vector embeddings using a local sentence-transformers model."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model_name = self._settings.embedding_model
        self._dimension = self._settings.embedding_dimension

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of text chunks.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each a list of floats).
        """
        if not texts:
            return []

        model = _load_model(self._model_name)

        with EMBEDDING_LATENCY.time():
            embeddings: np.ndarray = model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )

        EMBEDDING_COUNT.inc(len(texts))
        logger.debug("embeddings_generated", count=len(texts), dimension=self._dimension)

        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string.

        Args:
            query: The search query text.

        Returns:
            Embedding vector as a list of floats.
        """
        results = self.embed_texts([query])
        return results[0]


# Module-level singleton
_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return the module-level embedding service singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = EmbeddingService()
    return _service
