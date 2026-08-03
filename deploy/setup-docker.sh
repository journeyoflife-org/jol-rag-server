#!/usr/bin/env bash
# =============================================================================
# setup-docker.sh — Docker CE + Compose v2 installation for rag-prod-lt01
# Idempotent: safe to re-run on Ubuntu 24.04 LTS.
#
# SOC 2 CC8.1 — Approved, version-pinned software installation
# CIS Docker Benchmark — hardened daemon configuration
#
# Usage:
#   sudo ./setup-docker.sh
# =============================================================================
set -euo pipefail

DOCKER_VERSION="5:27.5.1-1~ubuntu.24.04~noble"
COMPOSE_VERSION="v2.32.4"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# --- Pre-flight ---
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root." >&2
  exit 1
fi

source /etc/os-release
if [[ "${VERSION_ID}" != "24.04" ]]; then
  log "WARNING: Expected Ubuntu 24.04, got ${VERSION_ID}. Proceeding anyway."
fi

# --- Install prerequisites ---
log "Installing prerequisites..."
apt-get update -qq
apt-get install -y -qq \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  apparmor-utils \
  auditd \
  >/dev/null 2>&1

# --- Add Docker GPG key and repository ---
DOCKER_KEYRING="/etc/apt/keyrings/docker.asc"
if [[ ! -f "${DOCKER_KEYRING}" ]]; then
  log "Adding Docker GPG key..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "${DOCKER_KEYRING}"
  chmod a+r "${DOCKER_KEYRING}"
fi

DOCKER_REPO="/etc/apt/sources.list.d/docker.list"
ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [arch=${ARCH} signed-by=${DOCKER_KEYRING}] https://download.docker.com/linux/ubuntu ${CODENAME} stable" > "${DOCKER_REPO}"

# --- Install Docker CE ---
apt-get update -qq
if dpkg -s docker-ce &>/dev/null; then
  log "Docker CE already installed: $(docker --version)"
else
  log "Installing Docker CE ${DOCKER_VERSION}..."
  apt-get install -y -qq \
    "docker-ce=${DOCKER_VERSION}" \
    "docker-ce-cli=${DOCKER_VERSION}" \
    containerd.io \
    docker-buildx-plugin \
    >/dev/null 2>&1
  log "Docker CE installed: $(docker --version)"
fi

# --- Install Docker Compose v2 plugin ---
COMPOSE_DIR="/usr/local/lib/docker/cli-plugins"
COMPOSE_BIN="${COMPOSE_DIR}/docker-compose"
if [[ -f "${COMPOSE_BIN}" ]] && docker compose version 2>/dev/null | grep -q "${COMPOSE_VERSION}"; then
  log "Docker Compose ${COMPOSE_VERSION} already installed."
else
  log "Installing Docker Compose ${COMPOSE_VERSION}..."
  mkdir -p "${COMPOSE_DIR}"
  curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
    -o "${COMPOSE_BIN}"
  chmod +x "${COMPOSE_BIN}"
  log "Docker Compose installed: $(docker compose version)"
fi

# --- Harden Docker daemon (CIS Docker Benchmark) ---
DAEMON_JSON="/etc/docker/daemon.json"
log "Configuring Docker daemon hardening..."
cat > "${DAEMON_JSON}" <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "live-restore": true,
  "userland-proxy": false,
  "no-new-privileges": true,
  "default-ulimits": {
    "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 }
  },
  "icc": false,
  "userns-remap": ""
}
EOF

# --- Configure Docker service hardening (systemd override) ---
SYSTEMD_OVERRIDE="/etc/systemd/system/docker.service.d"
mkdir -p "${SYSTEMD_OVERRIDE}"
cat > "${SYSTEMD_OVERRIDE}/hardening.conf" <<'EOF'
# CIS Docker Benchmark — systemd hardening
[Service]
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/docker /var/run
EOF

# --- Restart Docker to apply configuration ---
log "Restarting Docker daemon..."
systemctl daemon-reload
systemctl enable docker
systemctl restart docker

# --- Add jol-admin to docker group ---
if id "jol-admin" &>/dev/null; then
  usermod -aG docker jol-admin
  log "Added jol-admin to docker group."
fi

# --- Verify installation ---
log "Verification:"
log "  Docker: $(docker --version)"
log "  Compose: $(docker compose version)"
log "  Daemon config: ${DAEMON_JSON}"
log "Docker installation complete."
