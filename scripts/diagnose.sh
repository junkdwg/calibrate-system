#!/bin/sh
# One-shot diagnosis for restart loops / "unhealthy". Prints no passwords.
# Usage: sh scripts/diagnose.sh > diagnose.txt   (then send diagnose.txt)
get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }
U=$(get POSTGRES_USER); D=$(get POSTGRES_DB); P=$(get POSTGRES_PASSWORD)

echo "##### containers"; docker compose ps -a
for s in db web nginx; do
  echo; echo "##### logs: $s (last 40)"; docker compose logs --tail=40 --no-color "$s" 2>&1
done
echo; echo "##### web health check result"
docker inspect --format '{{json .State.Health}}' "$(docker compose ps -aq web | head -1)" 2>&1 | cut -c1-900

echo; echo "##### DB login with the SAME credentials web uses (TCP, password required)"
docker compose exec -T -e PGPASSWORD="$P" db psql -h 127.0.0.1 -U "$U" -d "$D" -tAc "select 'LOGIN OK as '||current_user||' on '||current_database()" 2>&1

echo; echo "##### DB roles / databases (via local socket, no password needed)"
for r in "$U" postgres calib; do
  [ -n "$r" ] || continue
  if docker compose exec -T db psql -U "$r" -d postgres -tAc "select 'connected as $r'" >/dev/null 2>&1; then
    echo "(using existing role: $r)"
    docker compose exec -T db psql -U "$r" -d postgres -tAc "select 'role: '||rolname||' login='||rolcanlogin||' super='||rolsuper from pg_roles where rolname !~ '^pg_'"
    docker compose exec -T db psql -U "$r" -d postgres -tAc "select 'database: '||datname||' owner='||pg_get_userbyid(datdba) from pg_database where not datistemplate"
    break
  fi
done

echo; echo "##### certs"
ls -l certs 2>&1
command -v openssl >/dev/null 2>&1 && openssl x509 -in certs/server.crt -noout -subject -enddate -ext subjectAltName 2>&1 | head -6
echo; echo "##### .env keys present (values hidden)"; grep -oE '^[A-Z_]+=' .env 2>/dev/null | tr '\n' ' '; echo
