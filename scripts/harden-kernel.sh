#!/usr/bin/env bash
# =============================================================================
# harden-kernel.sh — Kernel and OS hardening for rag-prod-lt01
# Applies CIS Benchmark recommendations, AppArmor, and auditd rules.
#
# CIS Ubuntu 24.04 Benchmark — Sections 3.x (Network), 5.x (Access Control)
# SOC 2 CC6.6 — Boundary protection
# ISO 27001 A.13.1 — Network security management
#
# Usage:
#   sudo ./harden-kernel.sh
#
# Idempotent: safe to re-run.
# =============================================================================
set -euo pipefail

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: This script must be run as root." >&2
  exit 1
fi

# --- Kernel parameter hardening (sysctl) ---
log "Applying kernel hardening via sysctl..."
SYSCTL_FILE="/etc/sysctl.d/99-jol-rag-hardening.conf"
cat > "${SYSCTL_FILE}" <<'EOF'
# JOL RAG Host — Kernel Hardening
# CIS Ubuntu 24.04 Benchmark / SOC 2 CC6.6

# --- Network Security ---
# Enable TCP SYN cookies (mitigate SYN flood)
net.ipv4.tcp_syncookies = 1
# Disable ICMP redirect acceptance
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
# Disable source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
# Log martian packets
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
# Ignore ICMP broadcast requests
net.ipv4.icmp_echo_ignore_broadcasts = 1
# Ignore bogus ICMP error responses
net.ipv4.icmp_ignore_bogus_error_responses = 1
# Enable reverse path filtering
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
# Disable IPv6 (not used in VLAN 40)
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1

# --- Memory Protection ---
# Full ASLR randomisation
kernel.randomize_va_space = 2
# Restrict kernel pointer exposure
kernel.kptr_restrict = 2
# Restrict dmesg access
kernel.dmesg_restrict = 1
# Restrict perf access
kernel.perf_event_paranoid = 3

# --- Filesystem ---
# Restrict core dumps
fs.suid_dumpable = 0
# Increase file descriptor limits
fs.file-max = 655360
fs.nr_open = 655360

# --- Virtual Memory ---
vm.swappiness = 10
vm.overcommit_memory = 0
EOF

sysctl --system >/dev/null 2>&1
log "sysctl hardening applied: ${SYSCTL_FILE}"

# --- AppArmor enforcement ---
log "Ensuring AppArmor is in enforce mode..."
if command -v aa-enforce >/dev/null 2>&1; then
  aa-enforce /etc/apparmor.d/* 2>/dev/null || true
  systemctl enable apparmor
  systemctl restart apparmor
  log "AppArmor enforced."
else
  log "WARNING: AppArmor tools not found. Install with: apt install apparmor-utils"
fi

# --- auditd configuration ---
log "Configuring auditd rules for RAG data directories..."
AUDIT_RULES="/etc/audit/rules.d/jol-rag.rules"
cat > "${AUDIT_RULES}" <<'EOF'
# JOL RAG — Audit rules for compliance (SOC 2 CC7.2 / ISO 27001 A.12.4)

# Monitor access to encrypted data directories
-w /var/lib/qdrant -p rwxa -k rag_qdrant_data
-w /var/lib/minio -p rwxa -k rag_minio_data

# Monitor Docker socket access
-w /var/run/docker.sock -p rwxa -k rag_docker_socket

# Monitor RAG application directory
-w /opt/jol/rag -p wa -k rag_app_changes

# Monitor audit log integrity (detect tampering)
-w /var/log/jol-rag -p wa -k rag_audit_tamper

# Monitor LUKS key material
-w /etc/luks/keys -p rwxa -k rag_luks_keys

# Monitor environment/secrets file
-w /opt/jol/rag/.env -p rwxa -k rag_secrets

# Monitor privilege escalation
-w /usr/bin/sudo -p x -k rag_priv_esc
-w /etc/sudoers -p wa -k rag_sudoers_change

# Monitor user/group changes
-w /etc/passwd -p wa -k rag_identity
-w /etc/shadow -p wa -k rag_identity
-w /etc/group -p wa -k rag_identity

# Monitor cron changes
-w /etc/crontab -p wa -k rag_cron
-w /var/spool/cron -p wa -k rag_cron
EOF

# Reload audit rules
if systemctl is-active auditd >/dev/null 2>&1; then
  augenrules --load >/dev/null 2>&1
  systemctl restart auditd
  log "auditd rules loaded: ${AUDIT_RULES}"
else
  systemctl enable auditd
  systemctl start auditd
  augenrules --load >/dev/null 2>&1
  log "auditd started and rules loaded."
fi

# --- Disable unnecessary kernel modules ---
log "Blacklisting unnecessary kernel modules..."
MODULES_FILE="/etc/modprobe.d/jol-rag-hardening.conf"
cat > "${MODULES_FILE}" <<'EOF'
# CIS Benchmark — Disable unused filesystem drivers
install cramfs /bin/false
install freevxfs /bin/false
install jffs2 /bin/false
install hfs /bin/false
install hfsplus /bin/false
install udf /bin/false
# Disable unused network protocols
install dccp /bin/false
install sctp /bin/false
install rds /bin/false
install tipc /bin/false
EOF
log "Kernel module blacklist applied: ${MODULES_FILE}"

# --- Set restrictive umask ---
log "Setting default umask to 027..."
if ! grep -q "^umask 027" /etc/login.defs; then
  sed -i 's/^umask.*/umask 027/' /etc/login.defs
fi

# --- Verify ---
log "Hardening complete. Summary:"
log "  sysctl: ${SYSCTL_FILE}"
log "  auditd: ${AUDIT_RULES}"
log "  modules: ${MODULES_FILE}"
log "  AppArmor: $(aa-status --enabled 2>/dev/null && echo 'enforced' || echo 'check manually')"
