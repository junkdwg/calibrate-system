#!/bin/sh
# Usage: scripts/make_cert.sh calib.company.local   (or the server IP, e.g. 192.168.1.50)
set -e
HOST="${1:?usage: make_cert.sh <hostname-or-ip>}"
mkdir -p certs
case "$HOST" in
  *[!0-9.]*) SAN="DNS:$HOST" ;;
  *)         SAN="IP:$HOST" ;;
esac
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout certs/server.key -out certs/server.crt \
  -subj "/CN=$HOST" -addext "subjectAltName=$SAN"
chmod 600 certs/server.key
echo "Created certs/server.crt and certs/server.key for $HOST"
