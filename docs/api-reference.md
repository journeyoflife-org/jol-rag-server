# API Reference

Base URL: `http://127.0.0.1:8000` (behind reverse proxy; external access via HTTPS 443)

Interactive docs: `/docs` (Swagger UI), `/redoc` (ReDoc)

## Authentication

All endpoints except `/health`, `/ready`, and `/metrics` require a Bearer JWT token.

```
Authorization: Bearer <token>
```

Token claims: `sub` (user ID), `role` (admin|analyst), `iss`, `aud`, `exp`.

## Endpoints

### GET /health

Liveness probe. No authentication required.

**Response 200:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600.5,
  "timestamp": "2026-08-02T10:00:00Z"
}
```

### GET /ready

Readiness probe. Checks Qdrant, MinIO, and Ollama connectivity.

**Response 200:**
```json
{
  "status": "ready",
  "version": "1.0.0",
  "uptime_seconds": 3600.5,
  "services": {"qdrant": "up", "minio": "up", "ollama": "up"},
  "timestamp": "2026-08-02T10:00:00Z"
}
```

### GET /metrics

Prometheus metrics exposition format. No authentication required.

### POST /ingest

Ingest a document. Requires `admin` role.

**Request:**
```json
{
  "document_id": "doc-2026-001",
  "title": "Catechism of the Catholic Church",
  "content": "Full text content here...",
  "format": "txt",
  "metadata": {"source": "vatican.va", "language": "en"},
  "retention_flag": false
}
```

**Response 201:**
```json
{
  "document_id": "doc-2026-001",
  "status": "completed",
  "chunks_created": 42,
  "message": "Document ingested successfully (42 chunks)",
  "timestamp": "2026-08-02T10:00:00Z"
}
```

### POST /query

Query the RAG pipeline. Requires `analyst` or `admin` role.

**Request:**
```json
{
  "question": "What does the Catechism say about baptism?",
  "top_k": 5,
  "filters": {"language": "en"},
  "include_sources": true
}
```

**Response 200:**
```json
{
  "answer": "According to the Catechism, Baptism is the first sacrament...",
  "sources": [
    {
      "document_id": "doc-2026-001",
      "chunk_id": "abc-123",
      "title": "Catechism of the Catholic Church",
      "score": 0.92,
      "content_preview": "Baptism is the first sacrament of initiation..."
    }
  ],
  "model": "mistral-7b-instruct",
  "latency_ms": 1850.3,
  "timestamp": "2026-08-02T10:00:00Z"
}
```

### DELETE /admin/documents/{document_id}

GDPR Art. 17 — Delete all data for a document. Requires `admin` role.

**Response 200:**
```json
{
  "deleted_embeddings": 42,
  "deleted_documents": 1,
  "status": "completed",
  "message": "Document 'doc-2026-001' fully erased",
  "timestamp": "2026-08-02T10:00:00Z"
}
```

### DELETE /admin/users/{user_id}

GDPR Art. 17 — Delete all data for a user. Requires `admin` role.

**Response 200:**
```json
{
  "deleted_embeddings": 15,
  "deleted_documents": 0,
  "status": "completed",
  "message": "User 'user-123' data erased",
  "timestamp": "2026-08-02T10:00:00Z"
}
```

## Error Responses

| Code | Meaning |
|------|---------|
| 401 | Missing or invalid authentication token |
| 403 | Insufficient role permissions |
| 404 | Resource not found |
| 422 | Validation error (see detail field) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Backend service unavailable (circuit breaker open) |
