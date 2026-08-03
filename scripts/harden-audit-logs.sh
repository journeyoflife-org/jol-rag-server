#!/usr/bin/env bash
# =============================================================================
# harden-audit-logs.sh — Make RAG audit logs append-only (immutability)
#
# Applies the ext4 append-only attribute to the audit JSONL file and its
# directory so that no process (even root) can truncate or rewrite history
# without first clearing the attribute — an intentional, auditable act.
#
# SOC 2 CC7.2 — Protection of audit logs from tampering
# ISO 27001 A.12.4.2 — Protection of log information
#
# Usage (on rag-prod-lt01):  sudo bash scripts/harden-audit-logs.sh
# =============================================================================
set -euo pipefail

AUDIT_DIR="${RAG_AUDIT_LOG_DIR:-/var/log/jol-rag}"
AUDIT_FILE="$AUDIT_DIR/audit.jsonl"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo)." >&2
  exit 1
fi

mkdir -p "$AUDIT_DIR"

# Dedicated service user owns the file; nobody else may write
chown root:jol-rag "$AUDIT_DIR" 2>/dev/null || chown root:root "$AUDIT_DIR"
chmod 750 "$AUDIT_DIR"

touch "$AUDIT_FILE"
chmod 640 "$AUDIT_FILE"

# Append-only: blocks truncate/delete/modify of existing content
chattr +a "$AUDIT_FILE"
chattr +a "$AUDIT_DIR"

# Rotation note: to rotate, an operator must explicitly:
#   sudo chattr -a "$AUDIT_DIR" "$AUDIT_FILE"
#   mv + compress + age-encrypt, then re-apply this script.

echo "Audit hardening applied:"
lsattr -d "$AUDIT_DIR"
lsattr "$AUDIT_FILE"
echo "Audit log is now append-only. See docs/runbook.md for rotation procedure."
