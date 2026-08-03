#!/usr/bin/env bash
# =============================================================================
# setup-luks.sh — LUKS2 encrypted partition provisioning for rag-prod-lt01
# Creates encrypted logical volumes for Qdrant and MinIO data directories.
#
# SOC 2 CC6.1 / GDPR Art. 32 / ISO 27001 A.8.24 — Data at rest encryption
#
# Usage:
#   sudo ./setup-luks.sh [--vg-name <vg>] [--qdrant-size <size>] [--minio-size <size>]
#
# Prerequisites:
#   - Ubuntu 24.04 LTS with LVM2 installed
#   - Unallocated disk space or a dedicated partition for the VG
#   - Root/sudo privileges
#
# Idempotent: safe to re-run; skips existing volumes.
# =============================================================================
set -euo pipefail

# --- Defaults ---
VG_NAME="vg-rag"
QDRANT_SIZE="40G"
MINIO_SIZE="30G"
QDRANT_MOUNT="/var/lib/qdrant"
MINIO_MOUNT="/var/lib/minio"
LUKS_CIPHER="aes-xts-plain64"
LUKS_KEY_SIZE=512
LUKS_HASH="sha512"
KEYFILE_DIR="/etc/luks/keys"

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vg-name) VG_NAME="$2"; shift 2 ;;
    --qdrant-size) QDRANT_SIZE="$2"; shift 2 ;;
    --minio-size) MINIO_SIZE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# --- Pre-flight checks ---
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root." >&2
  exit 1
fi

command -v cryptsetup >/dev/null 2>&1 || { echo "ERROR: cryptsetup not found. Install with: apt install cryptsetup" >&2; exit 1; }
command -v lvm >/dev/null 2>&1 || { echo "ERROR: lvm not found. Install with: apt install lvm2" >&2; exit 1; }

# --- Ensure keyfile directory exists ---
mkdir -p "${KEYFILE_DIR}"
chmod 700 "${KEYFILE_DIR}"

# --- Create VG if not present ---
if ! vgs "${VG_NAME}" &>/dev/null; then
  log "Volume group ${VG_NAME} not found. Creating from available PVs..."
  # Auto-detect unpartitioned NVMe or use loop device for pilot
  AVAILABLE_DISK=$(lsblk -dpno NAME,TYPE | awk '$2=="disk" && $1 !~ /loop/ {print $1}' | tail -1)
  if [[ -z "${AVAILABLE_DISK}" ]]; then
    log "WARNING: No unallocated disk found. Creating 80G loop device for pilot."
    LOOP_FILE="/var/lib/rag-luks-backing.img"
    if [[ ! -f "${LOOP_FILE}" ]]; then
      fallocate -l 80G "${LOOP_FILE}"
      chmod 600 "${LOOP_FILE}"
    fi
    AVAILABLE_DISK=$(losetup --find --show "${LOOP_FILE}")
    log "Loop device created: ${AVAILABLE_DISK}"
  fi
  pvcreate "${AVAILABLE_DISK}"
  vgcreate "${VG_NAME}" "${AVAILABLE_DISK}"
  log "Volume group ${VG_NAME} created."
else
  log "Volume group ${VG_NAME} already exists. Skipping creation."
fi

# --- Helper: create encrypted LV ---
create_encrypted_lv() {
  local lv_name="$1"
  local size="$2"
  local mount_point="$3"
  local keyfile="${KEYFILE_DIR}/${lv_name}.key"
  local mapper_name="crypt-${lv_name}"

  if lvs "${VG_NAME}/${lv_name}" &>/dev/null; then
    log "LV ${lv_name} already exists. Skipping."
    # Ensure mounted
    if ! mountpoint -q "${mount_point}"; then
      log "Mounting ${mount_point}..."
      cryptsetup open "/dev/${VG_NAME}/${lv_name}" "${mapper_name}" --key-file "${keyfile}" 2>/dev/null || true
      mount "/dev/mapper/${mapper_name}" "${mount_point}"
    fi
    return 0
  fi

  log "Creating LV ${lv_name} (${size})..."
  lvcreate -L "${size}" -n "${lv_name}" "${VG_NAME}"

  # Generate random keyfile
  log "Generating LUKS keyfile for ${lv_name}..."
  dd if=/dev/urandom of="${keyfile}" bs=64 count=1 2>/dev/null
  chmod 600 "${keyfile}"

  # Format with LUKS2
  log "Formatting ${lv_name} with LUKS2 (cipher: ${LUKS_CIPHER}, key-size: ${LUKS_KEY_SIZE})..."
  cryptsetup luksFormat \
    --type luks2 \
    --cipher "${LUKS_CIPHER}" \
    --key-size "${LUKS_KEY_SIZE}" \
    --hash "${LUKS_HASH}" \
    --key-file "${keyfile}" \
    --batch-mode \
    "/dev/${VG_NAME}/${lv_name}"

  # Open and format filesystem
  cryptsetup open "/dev/${VG_NAME}/${lv_name}" "${mapper_name}" --key-file "${keyfile}"
  mkfs.ext4 -L "${lv_name}" "/dev/mapper/${mapper_name}"

  # Create mount point and mount
  mkdir -p "${mount_point}"
  mount "/dev/mapper/${mapper_name}" "${mount_point}"

  # Add to crypttab for auto-unlock at boot
  if ! grep -q "${mapper_name}" /etc/crypttab 2>/dev/null; then
    echo "${mapper_name} /dev/${VG_NAME}/${lv_name} ${keyfile} luks" >> /etc/crypttab
    log "Added ${mapper_name} to /etc/crypttab"
  fi

  # Add to fstab for auto-mount
  if ! grep -q "${mount_point}" /etc/fstab; then
    echo "/dev/mapper/${mapper_name} ${mount_point} ext4 defaults,noatime,nosuid,nodev 0 2" >> /etc/fstab
    log "Added ${mount_point} to /etc/fstab"
  fi

  log "LV ${lv_name} created, encrypted, and mounted at ${mount_point}."
}

# --- Create volumes ---
create_encrypted_lv "lv-qdrant" "${QDRANT_SIZE}" "${QDRANT_MOUNT}"
create_encrypted_lv "lv-minio" "${MINIO_SIZE}" "${MINIO_MOUNT}"

# --- Set ownership for service users ---
# Qdrant runs as UID 1000 in container; MinIO as UID 1000
chown 1000:1000 "${QDRANT_MOUNT}"
chown 1000:1000 "${MINIO_MOUNT}"
chmod 750 "${QDRANT_MOUNT}"
chmod 750 "${MINIO_MOUNT}"

log "LUKS provisioning complete."
log "  Qdrant data: ${QDRANT_MOUNT} (${QDRANT_SIZE})"
log "  MinIO data:  ${MINIO_MOUNT} (${MINIO_SIZE})"
