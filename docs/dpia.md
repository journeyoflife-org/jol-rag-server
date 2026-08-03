# DPIA — JOL RAG Service

**Data Protection Impact Assessment** (GDPR Art. 35)

| Field | Value |
|---|---|
| Controller | Journey of Life (jol-admin) |
| System | RAG service on rag-prod-lt01 (10.40.40.10) |
| Repository | JourneyOfLife/jol-rag-server |
| Status | Pilot — approved for internal use |
| Last review | 2026-08-02 |
| Next review | 2027-02-02 (or on material change) |

## 1. Processing Description

The RAG service ingests organisational documents (catechism texts,
internal policies), generates vector embeddings locally, and answers
authenticated staff queries by retrieving relevant chunks and generating
answers with a locally hosted LLM (Ollama on llm-prod-lt01).

- **Data subjects**: platform staff (API users) and document authors.
- **Data categories**: document content, pseudonymised user identifiers
  (HMAC-SHA256 truncated to 16 hex chars), audit metadata (timestamps,
  IPs in operational logs only).
- **Purpose**: internal knowledge retrieval; legal basis Art. 6(1)(f)
  legitimate interest (internal operations), balanced against minimal
  personal data processing.

## 2. Necessity & Proportionality

- No direct identifiers stored in the vector DB or audit trail (pseudonymisation, Art. 25).
- Embeddings are derived from organisational documents, not personal profiles.
- Storage limitation: embeddings auto-purge after 90 days unless a
  retention flag is set (Art. 5(1)(e)); cached answers expire in 15 minutes.
- Access limited to two roles (admin, analyst) via JWT + RBAC.

## 3. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Unauthorised access to documents | Low | High | JWT/RBAC, mTLS, UFW, key-only SSH |
| Personal data leak via logs | Low | Medium | Pseudonymisation, no raw IDs in audit events |
| Data retention beyond necessity | Low | Medium | 90-day TTL purge scheduler, retention flags |
| Erasure request not fully honoured | Low | High | Cascade deletion (Qdrant → MinIO → cache) + verification counts + audit |
| Cross-border transfer | None | — | All processing on EU-based on-prem hardware |
| Vector inversion re-identification | Low | Low | Embeddings of organisational texts; model runs locally |

## 4. Measures & Safeguards

- Encryption at rest: LUKS volumes for Qdrant/MinIO data.
- Encryption in transit: mTLS between services (internal CA).
- Erasure: `DELETE /admin/documents/{id}` and `DELETE /admin/users/{id}`
  cascade across vector store, object storage, and query cache, with
  counts returned to the caller and recorded in the append-only audit log.
- Audit: JSONL audit log, append-only (`chattr +a`), shipped to SIEM.
- Backups: nightly, age-encrypted, stored off-box (PBS + local copies).

## 5. Residual Risks & Acceptance

Residual risk assessed as **LOW**. Accepted by the controller for the
pilot phase. Material changes (new data categories, external LLM APIs,
public exposure) require re-assessment before deployment.
