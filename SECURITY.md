# Security Policy — jol-rag-server

## Scope

This policy covers the JOL RAG service: the FastAPI application, the
ingestion worker, and its dedicated data plane (Qdrant, MinIO, Redis) on
`rag-prod-lt01` (10.40.40.10, VLAN 40).

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.x     | :white_check_mark: |

## Reporting a Vulnerability

**Do not open public issues for security vulnerabilities.**

- Email: `security@journeyoflife.org` (PGP key published on the JOL website)
- Response target: acknowledgement within **48 h**, initial triage within **5 business days**
- Coordinated disclosure window: **90 days** by default

Please include: reproduction steps, affected component (API / worker /
data store / deployment), and any evidence. Do not include personal data
in reports (GDPR Art. 5(1)(c)).

## Security Controls Summary

| Control | Implementation | Framework mapping |
|---|---|---|
| Authentication | JWT (HS256 pilot, RS256/OIDC roadmap) | SOC 2 CC6.1 |
| Authorisation | RBAC (admin / analyst), least privilege | ISO 27001 A.9.2 |
| Transport security | mTLS between services (internal CA) | ISO 27001 A.13.2 |
| Secrets | Vault injection, no secrets in repo | SOC 2 CC6.1 |
| Audit logging | Append-only JSONL, SIEM shipping | SOC 2 CC7.2 |
| Rate limiting | Per-IP + per-user, role-aware scopes | SOC 2 CC6.6 |
| Data protection | HMAC pseudonymisation, LUKS at rest | GDPR Art. 25/32 |
| Vulnerability mgmt | Trivy image scan + pip-audit in CI | ISO 27001 A.12.6 |
| Erasure | GDPR Art. 17 cascade (Qdrant/MinIO/cache) | GDPR Art. 17 |

## Secrets Policy

- Never commit secrets, keys, or certificates (enforced via `.gitignore` and CI review).
- All runtime secrets are injected from HashiCorp Vault
  (`scripts/vault-inject-secrets.sh`); `.env.example` contains placeholders only.
- Rotation cadence: JWT signing key and HMAC salt every 90 days
  (see `docs/runbook.md`), TLS certificates yearly.

## Incident Response

Follow the JOL incident response runbook. RAG-specific steps
(isolation, backup restore, audit log review) are in `docs/runbook.md`.
