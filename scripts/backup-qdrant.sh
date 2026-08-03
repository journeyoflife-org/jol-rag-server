#!/usr/bin/env bash
# =============================================================================
# backup-qdrant.sh — Encrypted backup of Qdrant data and MinIO documents
# Creates Qdrant snapshot + MinIO mirror, encrypts with age, stores off-site.
#
# RPO: 24h (runs nightly via cron at 02:30 UTC)
# RTO: 4h (see restore-qdrant.sh)
#
# SOC 2 CC7.3 — Backup and recovery
# ISO 27001 A.12.3 — Information backup
# GDPR Art. 32 — Security of processing (encrypted backups)
#
# Usage:
#   sudo ./backup-qdrant.sh [--output-dir /path]
#
# Prerequisites:
#   - age encryption tool installed (apt install age)
#   - Docker Compose stack running
#   - QDRANT_API_KEY in /opt/jol/rag/.env
# =============================================================================
set -euo pipefail

# --- Configuration ---
RAG_DIR="/opt/jol/rag"
BACKUP_DIR="/var/backups/jol-rag"
RETENTION_DAYS=30
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
QDRANT_HOST="127.0.0.1"
QDRANT_PORT="6333"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) BACKUP_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# --- Pre-flight ---
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root." >&2
  exit 1
fi

# Load environment
if [[ -f "${RAG_DIR}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${RAG_DIR}/.env"
  set +a
fi

# Check for age encryption key
AGE_KEY_FILE="/etc/jol/backup-age-key.txt"
if [[ ! -f "${AGE_KEY_FILE}" ]]; then
  log "ERROR: Age key file not found at ${AGE_KEY_FILE}"
  log "Generate with: age-keygen -o ${AGE_KEY_FILE}"
  exit 1
fi
AGE_RECIPIENT=$(grep "public key:" "${AGE_KEY_FILE}" | awk '{print $NF}')

mkdir -p "${BACKUP_DIR}"
WORK_DIR="${BACKUP_DIR}/work-${TIMESTAMP}"
mkdir -p "${WORK_DIR}"

# --- Step 1: Qdrant snapshot ---
log "Creating Qdrant snapshot..."
SNAPSHOT_RESPONSE=$(curl -sf -X POST \
  "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${QDRANT_COLLECTION:-jol-documents}/snapshots" \
  -H "api-key: ${QDRANT_API_KEY}" \
  -H "Content-Type: application/json" 2>/dev/null) || {
  log "ERROR: Failed to create Qdrant snapshot"
  rm -rf "${WORK_DIR}"
  exit 1
}

SNAPSHOT_NAME=$(echo "${SNAPSHOT_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['name'])" 2>/dev/null)
log "Snapshot created: ${SNAPSHOT_NAME}"

# Download snapshot
curl -sf \
  "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${QDRANT_COLLECTION:-jol-documents}/snapshots/${SNAPSHOT_NAME}" \
  -H "api-key: ${QDRANT_API_KEY}" \
  -o "${WORK_DIR}/qdrant-snapshot-${TIMESTAMP}.snapshot" || {
  log "ERROR: Failed to download Qdrant snapshot"
  rm -rf "${WORK_DIR}"
  exit 1
}

# --- Step 2: MinIO data backup ---
log "Backing up MinIO document storage..."
MINIO_DATA="/var/lib/minio"
if [[ -d "${MINIO_DATA}" ]]; then
  tar -czf "${WORK_DIR}/minio-data-${TIMESTAMP}.tar.gz" \
    -C "$(dirname "${MINIO_DATA}")" "$(basename "${MINIO_DATA}")" 2>/dev/null
  log "MinIO data archived."
else
  log "WARNING: MinIO data directory not found at ${MINIO_DATA}"
fi

# --- Step 3: Backup audit logs ---
log "Backing up audit logs..."
AUDIT_LOG_DIR="/var/log/jol-rag"
if [[ -d "${AUDIT_LOG_DIR}" ]]; then
  tar -czf "${WORK_DIR}/audit-logs-${TIMESTAMP}.tar.gz" \
    -C "$(dirname "${AUDIT_LOG_DIR}")" "$(basename "${AUDIT_LOG_DIR}")" 2>/dev/null
  log "Audit logs archived."
fi

# --- Step 4: Encrypt backup ---
log "Encrypting backup with age..."
ARCHIVE_NAME="jol-rag-backup-${TIMESTAMP}.tar.gz"
tar -czf "${WORK_DIR}/${ARCHIVE_NAME}" -C "${WORK_DIR}" . --exclude="${ARCHIVE_NAME}"

age -r "${AGE_RECIPIENT}" \
  -o "${BACKUP_DIR}/${ARCHIVE_NAME}.age" \
  "${WORK_DIR}/${ARCHIVE_NAME}"

# Remove unencrypted work directory
rm -rf "${WORK_DIR}"
log "Encrypted backup: ${BACKUP_DIR}/${ARCHIVE_NAME}.age"

# --- Step 5: Cleanup old backups ---
log "Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "*.age" -mtime "+${RETENTION_DAYS}" -delete
REMAINING=$(find "${BACKUP_DIR}" -name "*.age" | wc -l)
log "Retention cleanup complete. ${REMAINING} backups remaining."

# --- Step 6: Verify backup integrity ---
BACKUP_SIZE=$(stat -c%s "${BACKUP_DIR}/${ARCHIVE_NAME}.age" 2>/dev/null || echo "0")
if [[ "${BACKUP_SIZE}" -lt 1024 ]]; then
  log "ERROR: Backup file suspiciously small (${BACKUP_SIZE} bytes). Investigate."
  exit 1
fi

log "Backup complete."
log "  File: ${BACKUP_DIR}/${ARCHIVE_NAME}.age"
log "  Size: $(numfmt --to=iec "${BACKUP_SIZE}")"
log "  Encryption: age (X25519)"
log "  Retention: ${RETENTION_DAYS} days"
