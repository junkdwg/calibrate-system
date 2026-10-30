#!/bin/sh
# Production certificate from your company CA (e.g. AD CS).
# Usage: scripts/make_csr.sh calib.company.local     (DNS name recommended; an IP also works)
# 1) run this  2) give certs/server.csr to IT/CA  3) save the signed cert as certs/server.crt
#    (leaf first, then intermediate CA chain in the same file)  4) docker compose restart nginx
set -e
HOST="${1:?usage: make_csr.sh <hostname-or-ip>}"
mkdir -p certs
case "$HOST" in *[!0-9.]*) SAN="DNS:$HOST" ;; *) SAN="IP:$HOST" ;; esac
[ -f certs/server.key ] && cp certs/server.key "certs/server.key.bak.$(date +%Y%m%d%H%M%S)"
openssl req -new -newkey rsa:2048 -nodes -keyout certs/server.key -out certs/server.csr \
  -subj "/CN=$HOST" -addext "subjectAltName=$SAN"
chmod 600 certs/server.key
echo "Created certs/server.csr (send to CA) and a NEW certs/server.key (keep private, never commit)."
