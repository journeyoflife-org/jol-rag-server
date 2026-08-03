"""RAG pipeline — orchestration of retrieval, reranking, and generation.

Coordinates embedding, vector search, prompt construction, and LLM inference
into a single coherent query pipeline.

SOC 2 CC7.1 — System monitoring (latency tracking)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Histogram

from app.audit import get_logger
from app.config import Settings, get_settings
from app.models import QueryResponse, SourceReference
from app.services.embeddings import get_embedding_service
from app.services.llm import get_llm_service
from app.services.vectorstore import get_vectorstore_service

# --- Prometheus metrics ---
PIPELINE_LATENCY = Histogram(
    "rag_pipeline_duration_seconds",
    "End-to-end RAG pipeline latency",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)
PIPELINE_QUERIES = Counter(
    "rag_pipeline_queries_total",
    "Total RAG pipeline queries",
    ["status"],
)

logger = get_logger()

# System prompt for the LLM — scoped to JOL's mission
SYSTEM_PROMPT = """You are a knowledgeable assistant for the Journey of Life (JOL) platform, \
a Roman Catholic digital mission serving communities across the European Union.

Your role is to answer questions accurately using ONLY the provided context documents. \
If the context does not contain sufficient information, state clearly that you cannot \
answer from the available sources. Do not fabricate information.

Guidelines:
- Cite source documents when referencing specific content.
- Maintain theological accuracy consistent with Catholic teaching.
- Respond in the same language as the question.
- Be concise but thorough.
- If uncertain, acknowledge limitations rather than speculate."""


class RAGPipeline:
    """End-to-end Retrieval-Augmented Generation pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._embeddings = get_embedding_service()
        self._vectorstore = get_vectorstore_service()
        self._llm = get_llm_service()

    def query(
        self,
        question: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        include_sources: bool = True,
    ) -> QueryResponse:
        """Execute the full RAG pipeline.

        Steps:
        1. Embed the query
        2. Retrieve top-k relevant chunks from Qdrant
        3. Construct prompt with context
        4. Generate answer via Ollama LLM
        5. Return structured response with sources

        Args:
            question: Natural language question.
            top_k: Number of context chunks to retrieve.
            filters: Metadata filters for vector search.
            include_sources: Whether to include source references.

        Returns:
            QueryResponse with answer, sources, and metadata.
        """
        start_time = time.perf_counter()

        try:
            # Step 1: Embed query
            query_embedding = self._embeddings.embed_query(question)

            # Step 2: Retrieve relevant chunks
            results = self._vectorstore.search(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=filters,
            )

            # Step 3: Construct prompt
            context_blocks = []
            sources: list[SourceReference] = []

            for i, result in enumerate(results):
                payload = result.get("payload", {})
                text = payload.get("text", "")
                context_blocks.append(
                    f"[Source {i + 1}: {payload.get('title', 'Unknown')}]\n{text}"
                )

                if include_sources:
                    sources.append(
                        SourceReference(
                            document_id=payload.get("document_id", "unknown"),
                            chunk_id=result.get("id", ""),
                            title=payload.get("title", "Unknown"),
                            score=result.get("score", 0.0),
                            content_preview=text[:200],
                        )
                    )

            context = (
                "\n\n---\n\n".join(context_blocks)
                if context_blocks
                else "No relevant context found."
            )

            prompt = f"""Context documents:

{context}

---

Question: {question}

Please provide a comprehensive answer based on the context above."""

            # Step 4: Generate answer
            answer = self._llm.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            PIPELINE_QUERIES.labels(status="success").inc()

            return QueryResponse(
                answer=answer,
                sources=sources if include_sources else [],
                model=self._settings.ollama_model,
                latency_ms=round(elapsed_ms, 2),
                timestamp=datetime.now(UTC),
            )

        except Exception as exc:
            PIPELINE_QUERIES.labels(status="error").inc()
            logger.error("pipeline_query_failed", error=str(exc), question=question[:100])
            raise

    def ingest_document(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Ingest a document: chunk, embed, and store in vector DB.

        Args:
            document_id: Unique document identifier.
            text: Parsed plain text content.
            metadata: Additional metadata (title, source, etc.).

        Returns:
            Number of chunks created and stored.
        """
        from app.services.documents import get_document_service

        doc_service = get_document_service()

        # Chunk the text
        chunks = doc_service.chunk_text(text)
        if not chunks:
            logger.warning("no_chunks_generated", document_id=document_id)
            return 0

        # Generate embeddings
        texts = [c["text"] for c in chunks]
        embeddings = self._embeddings.embed_texts(texts)

        # Upsert to vector store
        count = self._vectorstore.upsert_chunks(
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=metadata,
        )

        logger.info(
            "document_ingested",
            document_id=document_id,
            chunks=count,
            text_length=len(text),
        )
        return count


# Module-level singleton
_pipeline: RAGPipeline | None = None


def get_pipeline() -> RAGPipeline:
    """Return the module-level RAG pipeline singleton."""
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline
