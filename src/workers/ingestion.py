"""Background ingestion worker — async document processing.

Consumes ingestion jobs from Redis queue and processes documents:
parse, chunk, embed, and upsert to Qdrant.

Also handles GDPR-mandated auto-purge of embeddings older than 90 days
(unless retention_flag is set).

GDPR Art. 5(1)(e) — Storage limitation
SOC 2 CC7.1 — Automated processing monitoring
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import UTC, datetime, timedelta

from app.audit import _configure_structlog, get_logger
from app.config import get_settings

logger = get_logger()

# Graceful shutdown flag
_shutdown = False


def _signal_handler(signum: int, frame) -> None:  # noqa: ANN001
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown  # noqa: PLW0603
    logger.info("worker_shutdown_requested", signal=signum)
    _shutdown = True


def purge_expired_embeddings() -> int:
    """Remove embeddings older than the configured TTL (90 days).

    Respects retention_flag — documents flagged for retention are exempt.
    GDPR Art. 5(1)(e) — Storage limitation principle.

    Returns:
        Number of embeddings purged.
    """
    from qdrant_client.models import (
        DatetimeRange,
        FieldCondition,
        Filter,
    )

    from app.services.vectorstore import get_vectorstore_service

    settings = get_settings()
    vectorstore = get_vectorstore_service()
    client = vectorstore._get_client()

    cutoff = datetime.now(UTC) - timedelta(days=settings.rag_embedding_ttl_days)

    # Find points created before cutoff AND without retention flag
    filter_cond = Filter(
        must=[
            FieldCondition(
                key="created_at",
                range=DatetimeRange(lt=cutoff.isoformat()),
            ),
            FieldCondition(
                key="retention_flag",
                match={"value": False},
            ),
        ]
    )

    try:
        count_result = client.count(
            collection_name=settings.qdrant_collection,
            count_filter=filter_cond,
        )
        count = count_result.count

        if count > 0:
            client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=filter_cond,
            )
            logger.info(
                "embeddings_purged",
                count=count,
                cutoff_date=cutoff.isoformat(),
                ttl_days=settings.rag_embedding_ttl_days,
            )
        return count
    except Exception as exc:
        logger.error("purge_failed", error=str(exc))
        return 0


def process_queue() -> None:
    """Main worker loop: consume and process ingestion jobs from Redis."""
    import redis as redis_lib
    from rq import Queue, Worker

    settings = get_settings()

    # Connect to Redis
    conn = redis_lib.from_url(settings.redis_url)
    queue = Queue("ingestion", connection=conn)

    logger.info(
        "worker_started",
        queue="ingestion",
        redis_url=settings.redis_url.split("@")[-1],  # Don't log password
    )

    # Start RQ worker
    worker = Worker([queue], connection=conn)
    worker.work(with_scheduler=False, logging_level="INFO")


def run_purge_scheduler(interval_hours: int = 6) -> None:
    """Run periodic purge of expired embeddings.

    Args:
        interval_hours: Hours between purge runs.
    """
    logger.info("purge_scheduler_started", interval_hours=interval_hours)

    while not _shutdown:
        try:
            purged = purge_expired_embeddings()
            if purged > 0:
                logger.info("scheduled_purge_complete", purged=purged)
        except Exception as exc:
            logger.error("scheduled_purge_error", error=str(exc))

        # Sleep in small increments to allow graceful shutdown
        for _ in range(interval_hours * 3600):
            if _shutdown:
                break
            time.sleep(1)


def main() -> None:
    """Entry point for the ingestion worker container."""
    settings = get_settings()
    _configure_structlog(settings)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("ingestion_worker_booting", environment=settings.rag_environment)

    try:
        process_queue()
    except KeyboardInterrupt:
        logger.info("worker_interrupted")
    except Exception as exc:
        logger.error("worker_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        logger.info("worker_stopped")


if __name__ == "__main__":
    main()
