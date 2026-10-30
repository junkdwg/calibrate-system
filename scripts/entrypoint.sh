#!/bin/sh
set -e

python - <<'PY'
import os, sys, time
import psycopg

if not os.environ.get("POSTGRES_DB"):
    sys.exit(0)  # SQLite/dev mode

kw = dict(dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
          password=os.environ["POSTGRES_PASSWORD"], host=os.environ.get("POSTGRES_HOST", "db"),
          port=os.environ.get("POSTGRES_PORT", "5432"), connect_timeout=3)
last = ""
for _ in range(30):                      # wait up to ~60 s for the database
    try:
        psycopg.connect(**kw).close()
        sys.exit(0)
    except psycopg.OperationalError as e:
        last = str(e).strip()
        if "authentication failed" in last or "does not exist" in last:
            break                        # waiting will not help
        time.sleep(2)

print("\n==== DATABASE CONNECTION FAILED ====", file=sys.stderr)
print(last, file=sys.stderr)
if "authentication failed" in last or "does not exist" in last:
    print("""
POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB in .env do not match the EXISTING database volume.
Postgres only reads these values when the volume is created the first time; changing .env later
does NOT change the database. Fix (keeps your data): create/alter the role inside the db container, e.g.
  docker compose exec db psql -U <old_user> -d postgres -c "CREATE ROLE <new_user> LOGIN PASSWORD '<pw>' SUPERUSER"
or put the original values back in .env. See README > Troubleshooting.
""", file=sys.stderr)
time.sleep(15)                           # slow the restart loop so logs stay readable
sys.exit(1)
PY

python manage.py migrate --noinput
python manage.py setup_roles
python manage.py collectstatic --noinput
exec "$@"
