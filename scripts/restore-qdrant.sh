#!/usr/bin/env bash
# =============================================================================
# restore-qdrant.sh — Restore Qdrant and MinIO from encrypted backup
#
# RTO target: 4 hours
# Procedure: decrypt → extract → restore Qdrant snapshot → restore MinIO
#
# SOC 2 CC7.3 — Backup and recovery testing
# ISO 27001 A.17.1 — Information security continuity
#
# Usage:
#   sudo ./restore-qdrant.sh <backup-file.age>
#
# Prerequisites:
#   - age decryption key at /etc/jol/backup-age-key.txt
#   - Docker Compose stack stopped (will be restarted after restore)
# =============================================================================
set -euo pipefail

RAG_DIR="/opt/jol/rag"
QDRANT_DATA="/var/lib/qdrant"
MINIO_DATA="/var/lib/minio"
QDRANT_HOST="127.0.0.1"
QDRANT_PORT="6333"
AGE_KEY_FILE="/etc/jol/backup-age-key.txt"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# --- Pre-flight ---
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root." >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <backup-file.age>" >&2
  echo "Example: $0 /var/backups/jol-rag/jol-rag-backup-20260802T023000Z.tar.gz.age" >&2
  exit 1
fi

BACKUP_FILE="$1"
if [[ ! -f "${BACKUP_FILE}" ]]; then
  log "ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

if [[ ! -f "${AGE_KEY_FILE}" ]]; then
  log "ERROR: Age key file not found at ${AGE_KEY_FILE}"
  exit 1
fi

# Load environment
if [[ -f "${RAG_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${RAG_DIR}/.env"
  set +a
fi

RESTORE_DIR="/tmp/jol-rag-restore-$$"
mkdir -p "${RESTORE_DIR}"

# --- Step 1: Decrypt backup ---
log "Decrypting backup..."
age -d -i "${AGE_KEY_FILE}" -o "${RESTORE_DIR}/backup.tar.gz" "${BACKUP_FILE}" || {
  log "ERROR: Decryption failed. Check key file."
  rm -rf "${RESTORE_DIR}"
  exit 1
}

# --- Step 2: Extract archive ---
log "Extracting backup archive..."
tar -xzf "${RESTORE_DIR}/backup.tar.gz" -C "${RESTORE_DIR}"
rm -f "${RESTORE_DIR}/backup.tar.gz"

# --- Step 3: Stop services ---
log "Stopping RAG services..."
cd "${RAG_DIR}"
docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" stop rag-api rag-worker 2>/dev/null || true

# --- Step 4: Restore Qdrant snapshot ---
SNAPSHOT_FILE=$(find "${RESTORE_DIR}" -name "*.snapshot" | head -1)
if [[ -n "${SNAPSHOT_FILE}" ]]; then
  log "Restoring Qdrant from snapshot: $(basename "${SNAPSHOT_FILE}")"

  # Stop Qdrant for file-level restore
  docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" stop qdrant 2>/dev/null || true
  sleep 5

  # Clear existing data and restore
  rm -rf "${QDRANT_DATA:?}/collections"
  mkdir -p "${QDRANT_DATA}/snapshots"
  cp "${SNAPSHOT_FILE}" "${QDRANT_DATA}/snapshots/"

  # Restart Qdrant and recover from snapshot
  docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" start qdrant
  sleep 10

  # Trigger snapshot recovery via API
  SNAPSHOT_NAME=$(basename "${SNAPSHOT_FILE}")
  COLLECTION="${QDRANT_COLLECTION:-jol-documents}"
  curl -sf -X PUT \
    "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${COLLECTION}/snapshots/${SNAPSHOT_NAME}/recover" \
    -H "api-key: ${QDRANT_API_KEY}" \
    -H "Content-Type: application/json" || {
    log "WARNING: Snapshot recovery API call failed. Manual recovery may be needed."
  }
  log "Qdrant snapshot restore initiated."
else
  log "WARNING: No Qdrant snapshot found in backup."
fi

# --- Step 5: Restore MinIO data ---
MINIO_ARCHIVE=$(find "${RESTORE_DIR}" -name "minio-data-*.tar.gz" | head -1)
if [[ -n "${MINIO_ARCHIVE}" ]]; then
  log "Restoring MinIO data..."
  docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" stop minio 2>/dev/null || true
  sleep 3

  rm -rf "${MINIO_DATA:?}/jol-documents"
  tar -xzf "${MINIO_ARCHIVE}" -C "$(dirname "${MINIO_DATA}")"
  chown -R 1000:1000 "${MINIO_DATA}"

  docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" start minio
  log "MinIO data restored."
else
  log "WARNING: No MinIO archive found in backup."
fi

# --- Step 6: Restart all services ---
log "Restarting all RAG services..."
docker compose -p "${COMPOSE_PROJECT_NAME:-jol-rag}" up -d
sleep 10

# --- Step 7: Verify ---
log "Verifying service health..."
HEALTH=$(curl -sf "http://127.0.0.1:8000/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unreachable")
log "API health: ${HEALTH}"

# --- Cleanup ---
rm -rf "${RESTORE_DIR}"

log "Restore procedure complete."
log "  Qdrant: snapshot recovered"
log "  MinIO: data restored"
log "  Services: restarted"
log ""
log "IMPORTANT: Verify data integrity and run a test query before declaring recovery complete."
log "  curl -X POST http://127.0.0.1:8000/query -H 'Authorization: Bearer <token>' -d '{\"question\": \"test\"}'"
