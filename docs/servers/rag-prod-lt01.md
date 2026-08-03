# rag-prod-lt01

| Field              | Value                                      |
|--------------------|--------------------------------------------|
| **Hostname**       | rag-prod-lt01                              |
| **Role**           | rag                                        |
| **Environment**    | prod                                       |
| **VLAN**           | 40                                         |
| **Static IP**      | 10.40.40.10                                |
| **OS**             | Ubuntu 24.04 LTS (VM)                      |
| **Owner**          | jol-admin                                  |
| **Purpose**        | RAG services, vector databases, document indexing, embeddings |
| **SSH Policy**     | key-only                                   |
| **Backup Enabled** | yes                                        |
| **Monitoring**     | yes (node-exporter)                        |
| **VMID**           | 100                                        |
| **Hypervisor**     | pve-prod-hv01                              |

## Role Description

Retrieval-Augmented Generation server hosting vector databases (Qdrant),
document indexing pipelines, and embedding services. Memory-intensive
workloads requiring 24 GB RAM allocation.

## Resources

| Resource | Allocation |
|----------|-----------|
| vCPU     | 4         |
| RAM      | 24 GB     |
| Disk     | 100 GB (NVMe thin) |

## Network

- VLAN 40 — AI Services segment (10.40.40.0/24)
- Gateway: 10.40.40.1 (Proxmox NAT bridge)
- Ollama access: 10.30.30.10:11434 (VLAN 30, routed)
- Ingress restricted to internal service mesh and bastion only

## SSH Policy

- Password authentication **disabled**
- Key-only access via centrally managed SSH keys
- Root login disabled; administrative access via `jol-admin` + sudo
- Idle session timeout: 15 minutes

## Firewall Ports

| Port | Service        | Access       |
|------|----------------|--------------|
| 22   | SSH            | bastion only |
| 8000 | RAG API        | internal     |
| 6333 | Qdrant         | internal     |
| 9100 | node-exporter  | monitoring   |

## Backup Policy

- VM-level backup via PBS (nightly)
- RPO: 24 h | RTO: 4 h

## Monitoring Expectations

- Node-level metrics: CPU, memory, disk, network via node-exporter
- Alerting: host unreachable > 2 min, disk > 90 %, memory > 95 %
- Log shipping to centralised logging stack

## RAG Stack (Docker Compose)

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| rag-api | custom (FastAPI) | 127.0.0.1:8000 | RAG query/ingest API |
| rag-worker | custom (Python) | none | Async ingestion worker |
| qdrant | qdrant/qdrant:v1.14.1 | 127.0.0.1:6333 | Vector database |
| minio | minio/minio:latest | 127.0.0.1:9000 | Encrypted document storage |
| redis | redis:7-alpine | 127.0.0.1:6379 | Task queue broker |

## Dependencies

- **LLM Inference**: Ollama on llm-prod-lt01 (10.30.30.10:11434, VLAN 30)
- **Embedding Model**: sentence-transformers/all-MiniLM-L6-v2 (local, CPU)
- **Encryption**: LUKS2 volumes for /var/lib/qdrant and /var/lib/minio
- **Backups**: age-encrypted snapshots to /var/backups/jol-rag + PBS VM backup

## Compliance

- SOC 2 Type II / GDPR (EU 2016/679) / ISO 27001:2022
- Audit logging: /var/log/jol-rag/audit.jsonl (append-only, HMAC-pseudonymised)
- GDPR Art. 17: deletion API for documents and users
- GDPR Art. 5(1)(e): 90-day embedding TTL with auto-purge
- See: `docs/compliance-mapping.md` (this repository)

## Maintenance Notes

- Kernel patching during approved maintenance windows only
- Reboot required for kernel updates — schedule with AI team
- All changes tracked via ticket and recorded in change log
- Deployment via Ansible: `ansible-playbook -i ansible/inventory/production.yml ansible/provision-rag.yml`
