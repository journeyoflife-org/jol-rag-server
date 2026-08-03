#!/usr/bin/env bash
# =============================================================================
# ingest-docs.sh — CLI batch document ingestion tool
# Scans a directory for documents and ingests them via the RAG API.
#
# Usage:
#   ./ingest-docs.sh [--dir /data/raw_docs] [--api http://127.0.0.1:8000] [--token <jwt>]
#
# Supported formats: .pdf, .docx, .txt, .html
# =============================================================================
set -euo pipefail

# --- Defaults ---
DOCS_DIR="/data/raw_docs"
API_URL="http://127.0.0.1:8000"
TOKEN=""
DRY_RUN=false

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) DOCS_DIR="$2"; shift 2 ;;
    --api) API_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--dir <path>] [--api <url>] [--token <jwt>] [--dry-run]"
      echo ""
      echo "Options:"
      echo "  --dir      Directory to scan for documents (default: /data/raw_docs)"
      echo "  --api      RAG API base URL (default: http://127.0.0.1:8000)"
      echo "  --token    JWT authentication token (required)"
      echo "  --dry-run  List files without ingesting"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# --- Validate ---
if [[ ! -d "${DOCS_DIR}" ]]; then
  log "ERROR: Documents directory not found: ${DOCS_DIR}"
  exit 1
fi

if [[ -z "${TOKEN}" ]] && [[ "${DRY_RUN}" == "false" ]]; then
  log "ERROR: --token is required for ingestion. Use --dry-run to list files only."
  exit 1
fi

# --- Discover documents ---
log "Scanning ${DOCS_DIR} for documents..."
FILES=$(find "${DOCS_DIR}" -type f \( -name "*.pdf" -o -name "*.docx" -o -name "*.txt" -o -name "*.html" \) | sort)
FILE_COUNT=$(echo "${FILES}" | grep -c . || true)
log "Found ${FILE_COUNT} document(s)."

if [[ "${FILE_COUNT}" -eq 0 ]]; then
  log "No documents to process."
  exit 0
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "${FILES}"
  exit 0
fi

# --- Ingest each document ---
SUCCESS=0
FAILED=0

while IFS= read -r filepath; do
  filename=$(basename "${filepath}")
  relative_path="${filepath#"${DOCS_DIR}"/}"
  extension="${filename##*.}"

  # Map extension to format
  case "${extension}" in
    pdf) format="pdf" ;;
    docx) format="docx" ;;
    txt) format="txt" ;;
    html|htm) format="html" ;;
    *) continue ;;
  esac

  # Generate document ID from path hash
  doc_id="doc-$(echo "${relative_path}" | md5sum | cut -c1-12)"
  title="${filename%.*}"

  log "Ingesting: ${relative_path} (${format}, id: ${doc_id})"

  if RESPONSE=$(curl -sf -X POST "${API_URL}/ingest" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
      \"document_id\": \"${doc_id}\",
      \"title\": \"${title}\",
      \"file_path\": \"${relative_path}\",
      \"format\": \"${format}\",
      \"metadata\": {\"source\": \"batch_ingest\", \"original_path\": \"${relative_path}\"}
    }" 2>/dev/null); then
    CHUNKS=$(echo "${RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('chunks_created',0))" 2>/dev/null || echo "?")
    log "  OK: ${CHUNKS} chunks created"
    SUCCESS=$((SUCCESS + 1))
  else
    log "  FAILED: ${relative_path}"
    FAILED=$((FAILED + 1))
  fi

  # Rate limiting: small delay between requests
  sleep 0.5

done <<< "${FILES}"

# --- Summary ---
log ""
log "Batch ingestion complete."
log "  Total: ${FILE_COUNT}"
log "  Success: ${SUCCESS}"
log "  Failed: ${FAILED}"

if [[ ${FAILED} -gt 0 ]]; then
  exit 1
fi
