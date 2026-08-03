#!/usr/bin/env bash
# =============================================================================
# generate-mtls-certs.sh — Internal CA + mTLS certificates for the RAG stack
#
# Produces (in OUT_DIR):
#   ca.crt / ca.key                     — internal root CA (keep ca.key offline)
#   qdrant-server.crt / .key            — Qdrant TLS server cert
#   ollama-proxy-server.crt / .key      — nginx mTLS proxy on llm-prod-lt01
#   rag-api-client.crt / .key           — client cert presented by rag-api
#
# Usage:  bash scripts/tls/generate-mtls-certs.sh [OUT_DIR]
# Note:   Never commit the output — OUT_DIR is git-ignored.
# =============================================================================
set -euo pipefail

OUT_DIR="${1:-tls-certs}"
DAYS_CA=3650
DAYS_CERT=365
KEY_BITS=4096

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
cd "$OUT_DIR"

echo "[1/5] Generating internal root CA..."
openssl genrsa -out ca.key "$KEY_BITS"
openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS_CA" \
  -subj "/C=EU/O=Journey of Life/CN=JOL Internal RAG CA" \
  -out ca.crt

gen_cert() {
  local name="$1" cn="$2" san="$3"
  echo "[*] Generating certificate: $name (CN=$cn)"
  openssl genrsa -out "${name}.key" 2048
  openssl req -new -key "${name}.key" \
    -subj "/C=EU/O=Journey of Life/CN=${cn}" \
    -out "${name}.csr"
  cat > "${name}.ext" <<EOF
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=${san}
EOF
  openssl x509 -req -in "${name}.csr" -CA ca.crt -CAkey ca.key \
    -CAcreateserial -days "$DAYS_CERT" -sha256 \
    -extfile "${name}.ext" -out "${name}.crt"
  rm -f "${name}.csr" "${name}.ext"
}

echo "[2/5] Qdrant server certificate..."
gen_cert "qdrant-server" "qdrant" "DNS:qdrant,DNS:localhost,IP:127.0.0.1"

echo "[3/5] Ollama mTLS proxy server certificate (llm-prod-lt01)..."
gen_cert "ollama-proxy-server" "llm-prod-lt01" "DNS:llm-prod-lt01,IP:10.30.30.10"

echo "[4/5] RAG API client certificate..."
gen_cert "rag-api-client" "rag-api-client" "DNS:rag-api"

echo "[5/5] Setting permissions..."
chmod 600 ./*.key
chmod 644 ./*.crt

echo ""
echo "Done. Certificates written to: $(pwd)"
echo "  - Store ca.key offline / in Vault; never on service hosts unencrypted."
echo "  - Deploy server certs + ca.crt to the respective hosts,"
echo "    and rag-api-client.{crt,key} + ca.crt into the rag-api container."
