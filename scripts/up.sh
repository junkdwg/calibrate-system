#!/bin/sh
# Safe start: checks the things that caused restart loops, then starts the stack.
set -e
fail() { echo "ERROR: $1" >&2; exit 1; }

[ -f .env ] || fail ".env not found (cp .env.example .env and edit it)"
grep -q "change-me" .env && fail ".env still contains 'change-me' placeholders"
[ -f certs/server.crt ] && [ -f certs/server.key ] || fail "certs/server.crt or server.key missing -> run: scripts/make_cert.sh <host-or-ip>"

if command -v openssl >/dev/null 2>&1; then
  openssl x509 -in certs/server.crt -noout -checkend 2592000 >/dev/null 2>&1 || echo "WARNING: certificate expires within 30 days (or is invalid)" >&2
  openssl x509 -in certs/server.crt -noout -ext subjectAltName 2>/dev/null | grep -q "DNS:\|IP" \
    || echo "WARNING: certificate has no subjectAltName (browsers will reject it). Recreate with scripts/make_cert.sh" >&2
fi

docker compose up -d --build
docker compose ps
