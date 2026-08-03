"""Locust load test — RAG API (target: 100 concurrent users).

Run against a staging environment (never production):

    locust -f load/locustfile.py --host http://staging-rag:8000 \
        --users 100 --spawn-rate 5 --run-time 10m --headless

Provide a valid JWT via RAG_TEST_TOKEN (analyst role for /query,
admin role for /ingest scenarios).

SOC 2 CC8.1 — Capacity validation before production changes
"""

from __future__ import annotations

import os
import random

from locust import FastHttpUser, between, task

QUESTIONS = [
    "What does the Catechism say about baptism?",
    "Summarise the liturgical calendar seasons.",
    "What are the sacraments of initiation?",
    "Explain the examination of conscience.",
    "What is the Rite of Christian Initiation of Adults?",
]


class RAGAnalystUser(FastHttpUser):
    """Simulates analyst query traffic (dominant workload)."""

    wait_time = between(1, 3)
    abstract = False

    def on_start(self) -> None:
        token = os.environ.get("RAG_TEST_TOKEN", "")
        self.client.headers = {"Authorization": f"Bearer {token}"}

    @task(9)
    def query(self) -> None:
        self.client.post(
            "/query",
            json={
                "question": random.choice(QUESTIONS),
                "top_k": 5,
            },
            name="/query",
        )

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")


class RAGAdminUser(FastHttpUser):
    """Simulates sporadic admin ingestion traffic."""

    wait_time = between(10, 30)
    weight = 1

    def on_start(self) -> None:
        token = os.environ.get("RAG_ADMIN_TOKEN", "")
        self.client.headers = {"Authorization": f"Bearer {token}"}

    @task
    def ingest(self) -> None:
        doc_no = random.randint(1, 100_000)
        self.client.post(
            "/ingest",
            json={
                "document_id": f"load-test-{doc_no}",
                "title": "Load test document",
                "content": "Load testing content. " * 20,
                "format": "txt",
            },
            name="/ingest",
        )
