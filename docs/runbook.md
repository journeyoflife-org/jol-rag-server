# RAG Service Operations Runbook

## Service Overview

| Property | Value |
|----------|-------|
| Host | rag-prod-lt01 (10.40.40.10) |
| VLAN | 40 (AI Services) |
| Stack | Docker Compose (`jol-rag` project) |
| App dir | /opt/jol/rag |
| Audit logs | /var/log/jol-rag/audit.jsonl |
| Qdrant data | /var/lib/qdrant (LUKS encrypted) |
| MinIO data | /var/lib/minio (LUKS encrypted) |

## Common Operations

### Check service status

```bash
ssh jol-admin@10.40.40.10  # via bastion ProxyJump
cd /opt/jol/rag
docker compose ps
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s http://127.0.0.1:8000/ready | python3 -m json.tool
```

### View logs

```bash
# Application logs (structured JSON)
docker compose logs -f rag-api --tail 100

# Audit trail
tail -f /var/log/jol-rag/audit.jsonl | python3 -m json.tool

# Worker logs
docker compose logs -f rag-worker --tail 50
```

### Restart services

```bash
# Full stack restart
sudo systemctl restart jol-rag

# Single service
cd /opt/jol/rag
docker compose restart rag-api

# Rebuild after code update
docker compose up -d --build rag-api rag-worker
```

### Deploy code update (via Ansible)

```bash
# From control node
cd ansible/
ansible-playbook -i inventory/production.yml provision-rag.yml --limit rag-prod-lt01
```

## Redis Credential Rotation

Rotate the Redis password whenever it is suspected exposed (see incident
2026-08-07), after personnel change, or on the scheduled rotation cadence.

**Source of truth:** HashiCorp Vault (`secret/data/jol/rag/prod`).
**Transport:** Ansible Vault-encrypted vars (`ansible/group_vars/rag/vault.yml`).

### Procedure

```bash
# 1. One-time: create the encrypted vars file
cp ansible/group_vars/rag/vault.yml.example ansible/group_vars/rag/vault.yml
ansible-vault encrypt ansible/group_vars/rag/vault.yml

# 2. Set the new password (openssl rand -hex 32)
ansible-vault edit ansible/group_vars/rag/vault.yml

# 3. Run the rotation playbook (preflight -> Vault sync -> .env re-render
#    -> ordered restart -> verification -> masked audit record)
make rotate-redis

# 4. Verify evidence on the host
tail -1 /var/log/jol-rag/secrets-rotation.log   # fingerprints only, no secrets
```

### Emergency mode (HashiCorp Vault unreachable)

```bash
ansible-playbook -i ansible/inventory/production.yml ansible/rotate-redis-secret.yml \
  --limit rag-prod-lt01 --ask-vault-pass -e skip_vault_sync=true
# Afterwards, reconcile Vault manually:
vault kv patch secret/data/jol/rag/prod redis_password=<NEW>
```

### Rollback

The playbook backs up the env file before mutating anything:
`/opt/jol/rag/.env.bak.<timestamp>` (mode 0600). To revert, restore the
backup and run `docker compose up -d` in `/opt/jol/rag`, or roll back the
VM snapshot (`qm rollback 100 <snapshot>`).

## Troubleshooting

### Qdrant unreachable

```bash
# Check container
docker compose logs qdrant --tail 50
# Check port
curl -s http://127.0.0.1:6333/healthz
# Check LUKS volume
mountpoint /var/lib/qdrant && echo "mounted" || echo "NOT MOUNTED"
# Remount if needed
sudo cryptsetup open /dev/vg-rag/lv-qdrant crypt-lv-qdrant --key-file /etc/luks/keys/lv-qdrant.key
sudo mount /dev/mapper/crypt-lv-qdrant /var/lib/qdrant
```

### Ollama (LLM) unreachable

```bash
# Test from RAG host
curl -s http://10.30.30.10:11434/v1/models
# Check VLAN routing
ip route get 10.30.30.10
# If unreachable: check firewall on llm-prod-lt01 and Proxmox routing
```

### High query latency

1. Check Grafana dashboard: `rag_pipeline_duration_seconds` p95
2. Identify bottleneck: embedding vs. retrieval vs. LLM generation
3. Check resource usage: `docker stats`
4. If LLM-bound: check GPU utilisation on llm-prod-lt01 (`nvidia-smi`)

### Disk space critical

```bash
df -h /var/lib/qdrant /var/lib/minio
# Emergency: purge old embeddings
docker compose exec rag-api python -c "from workers.ingestion import purge_expired_embeddings; print(purge_expired_embeddings())"
```

## Disaster Recovery

**RPO:** 24 hours (nightly backup at 02:30 UTC)
**RTO:** 4 hours

### Restore procedure

1. Identify latest backup: `ls -lt /var/backups/jol-rag/*.age`
2. Run restore: `sudo /opt/jol/rag/scripts/restore-qdrant.sh /var/backups/jol-rag/<file>.age`
3. Verify: `curl http://127.0.0.1:8000/ready`
4. Run test query to confirm data integrity

### Full VM restore (PBS)

If the entire VM is lost:
1. Restore VM from PBS (VMID 100)
2. Unlock LUKS volumes (keys in /etc/luks/keys on PBS backup)
3. Start services: `sudo systemctl start jol-rag`
4. Verify all endpoints

## Escalation

| Severity | Condition | Action |
|----------|-----------|--------|
| P1 | Service fully down > 5 min | Page on-call, restore from backup |
| P2 | Degraded (latency > 10s) | Investigate, scale resources |
| P3 | Single component down | Restart component, monitor |
| P4 | Non-urgent issue | Create ticket, next sprint |

## Maintenance Windows

- Kernel patching: approved windows only (coordinate with AI team)
- Reboot required for kernel updates
- All changes tracked via ticket and recorded in change log
- No manual production changes except approved emergencies
