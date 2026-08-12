# Formal Risk Acceptance — RA-2026-001: Loki Log-Shipping Staged (Audit F-03)

| Field                  | Value                                                        |
|------------------------|--------------------------------------------------------------|
| **Risk ID**            | RA-2026-001                                                  |
| **Source**             | Production audit `rag-prod-lt01-audit-20260812.md`, finding F-03 (HIGH) |
| **Accepted by**        | Journey of Life — Platform Owner (jol-admin)                 |
| **Acceptance date**    | 2026-08-13                                                   |
| **Review date**        | 2026-11-13 (90 days) or at Loki deployment, whichever first  |
| **Frameworks**         | SOC 2 Type II CC7.2 / GDPR Art. 30 & 32 / ISO 27001:2022 A.8.15 |

## Risk Statement

Centralised log shipping (promtail → Loki) for `rag-prod-lt01` is not
operational. The Loki endpoint has never been deployed; promtail was
installed staged and deliberately remains inactive. Application, audit,
and system logs therefore exist only on the host (journald +
`/var/log/jol-rag/`), creating a single point of loss for log evidence
and delaying cross-host correlation during incident response.

## Rationale for Acceptance

1. **No Loki backend exists in the estate** — shipping cannot be
   enabled without deploying the receiving endpoint, which is out of
   scope of the RAG repository and not scheduled in the pilot phase.
2. **Loki is reclassified as a staged external dependency** (owner
   decision 2026-08-12, recorded in the deployment record amendment
   for audit F-03), analogous to the pre-restoration treatment of the
   Ollama dependency.
3. The pilot operates a single RAG instance on a dedicated VLAN
   segment; the absence of centralised shipping does not prevent
   detection — it delays off-host correlation only.

## Compensating Controls (verified)

| Control | Evidence |
|---------|----------|
| Local journald retention with persistent storage | `journalctl --disk-usage`, `Storage=persistent` |
| Application audit trail on disk, append-only | `/var/log/jol-rag/audit.jsonl` (HMAC-pseudonymised) |
| Log integrity monitoring via AIDE | Nightly `aide --check` (cron 04:15) + `dailyaidecheck.timer` |
| Log file rotation & permission hardening | `/etc/logrotate.d/jol-rag`; 0640 ownership (audit F-06/F-09 fixed) |
| VM-level backup of all log volumes | vzdump nightly `job-vm100-nightly` + PBS (audit F-01 fixed) |

## Residual Risk

- Loss of host-local logs (disk failure below backup granularity)
  eliminates the only evidence copy between backup intervals (RPO ≤ 24 h).
- Cross-host correlation (e.g., with llm-prod-lt01) is manual until a
  Loki or equivalent endpoint is deployed.

**Classification of residual risk:** LOW–MEDIUM for the pilot phase
(single tenant, internal-only network, VM backups cover log volumes).

## Conditions & Reversal Triggers

This acceptance is revoked, and Loki shipping must be deployed, when any
of the following occurs:

1. A second RAG instance or any additional production service joins
   VLAN 40 (multi-host correlation becomes mandatory).
2. A compliance sampling request requires centrally-queryable log
   evidence (SOC 2 Type II window).
3. An incident occurs where host-local evidence is insufficient.

## References

- Audit report: `/mnt/agents/output/rag-prod-lt01-audit-20260812.md`
  (F-03 row; Remediation Results section)
- Deployment record: `docs/deployments/2026-08-07-rag-prod-lt01.md`
  (Loki closure criterion amendment, 2026-08-12)
- Risk register entry: `docs/compliance-mapping.md`, Risk Acceptances table
