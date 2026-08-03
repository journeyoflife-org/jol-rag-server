# Compliance Control Mapping

## SOC 2 Type II

| Control | Requirement | Implementation | Evidence |
|---------|-------------|----------------|----------|
| CC6.1 | Logical access controls | JWT auth, RBAC (admin/analyst), API-key for Qdrant | `src/app/auth.py`, test_auth.py |
| CC6.6 | Boundary protection | UFW firewall, VLAN 40 isolation, rate limiting | `deploy/setup-docker.sh`, `middleware/rate_limit.py` |
| CC7.1 | System monitoring | Prometheus metrics, structured logging, health checks | `monitoring/`, `/metrics` endpoint |
| CC7.2 | Anomaly detection | Audit logging with pseudonymised IDs, alerting rules | `src/app/audit.py`, `prometheus-rag.yml` |
| CC7.3 | Backup and recovery | Daily encrypted backups (age), RPO 24h, RTO 4h | `scripts/backup-qdrant.sh`, `scripts/restore-qdrant.sh` |
| CC8.1 | Change management | All changes via Git PR, Ansible-managed deployment | `deploy/ansible/`, repo governance |

## GDPR (EU 2016/679)

| Article | Requirement | Implementation | Evidence |
|---------|-------------|----------------|----------|
| Art. 5(1)(c) | Data minimisation | Only embeddings + metadata in vector DB; raw docs separate | `services/documents.py`, architecture |
| Art. 5(1)(e) | Storage limitation | 90-day TTL auto-purge (unless retention_flag) | `workers/ingestion.py` purge scheduler |
| Art. 17 | Right to erasure | DELETE /admin/documents/{id}, DELETE /admin/users/{id} | `routers/admin.py`, test_gdpr_deletion.py |
| Art. 25 | Data protection by design | HMAC pseudonymisation, encryption at rest, local inference | `auth.py` pseudonymise, LUKS, MinIO SSE |
| Art. 30 | Records of processing | Append-only JSONL audit log with all required fields | `audit.py`, test_audit.py |
| Art. 32 | Security of processing | AES-256 (LUKS + MinIO SSE), TLS 1.3, RBAC | LUKS setup, reverse proxy, auth |
| Art. 44 | Transfer restriction | All inference local (Ollama EU), no external API calls | Architecture: zero cross-border transfer |

## ISO 27001:2022

| Annex A Control | Requirement | Implementation |
|-----------------|-------------|----------------|
| A.5.15 | Access control | JWT + RBAC, least-privilege roles |
| A.8.2 | Privileged access | Admin-only for ingest/delete; analyst query-only |
| A.8.24 | Use of cryptography | LUKS2, MinIO SSE-S3, age backups, TLS 1.3 |
| A.9.2 | User access management | Role claims in JWT, no hard-coded credentials |
| A.12.1 | Operational procedures | Documented runbook, Ansible automation |
| A.12.4 | Logging and monitoring | Structured JSON audit, Prometheus, Grafana |
| A.12.6 | Technical vulnerability management | Trivy image scanning, pinned dependencies |
| A.13.1 | Network security | VLAN segmentation, UFW deny-by-default |
| A.17.1 | Information security continuity | Backup/restore tested quarterly, RTO 4h |

## Data Residency

| Data Type | Location | Encryption | Retention |
|-----------|----------|------------|-----------|
| Vector embeddings | rag-prod-lt01 (LUKS volume) | AES-XTS-256 (LUKS) | 90 days (auto-purge) |
| Raw documents | rag-prod-lt01 (MinIO, LUKS) | SSE-S3 (AES-256-GCM) | Until deletion request |
| Audit logs | rag-prod-lt01 + PBS backup | age (X25519) for backups | 1 year minimum |
| LLM inference | llm-prod-lt01 (transient) | N/A (not stored) | Not persisted |
| Backups | PBS (10.10.10.30) | age encryption | 30 days rolling |

## Risk Acceptances (Pilot Phase)

| Risk | Mitigation | Review Date |
|------|-----------|-------------|
| No mTLS between internal services | VLAN isolation + API keys; post-pilot mTLS | Post-pilot |
| JWT HS256 (shared secret) | Short expiry (60min); migrate to RS256/OIDC | Post-pilot |
| Single instance (no HA) | PBS VM backup, documented DR procedure | Scale phase |
| No WAF on reverse proxy | Rate limiting + input validation in app | Post-pilot |
