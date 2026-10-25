#!/usr/bin/env bash
set -e

CERT_DIR="$(dirname "$0")/../nginx/certs"
mkdir -p "$CERT_DIR"

KEY_FILE="$CERT_DIR/deskos.key"
CERT_FILE="$CERT_DIR/deskos.crt"
CONF_FILE="$CERT_DIR/openssl.cnf"

echo "[DeskOS SSL] Generating mDNS SAN certificate for deskos.local, raspberrypi.local, and localhost..."

cat > "$CONF_FILE" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
req_extensions = req_ext
x509_extensions = req_ext
distinguished_name = dn

[dn]
C = IN
ST = DL
L = New Delhi
O = DeskOS
CN = deskos.local

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = deskos.local
DNS.2 = raspberrypi.local
DNS.3 = localhost
IP.1 = 127.0.0.1
IP.2 = 192.168.29.137
IP.3 = 192.168.1.137
EOF

openssl req -x509 -nodes -days 1825 -newkey rsa:2048 \
  -keyout "$KEY_FILE" \
  -out "$CERT_FILE" \
  -config "$CONF_FILE"

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"
rm -f "$CONF_FILE"

echo "[DeskOS SSL] Certificate created successfully at $CERT_DIR"

