#!/bin/sh
# Daily DB backup. Cron example:  0 2 * * * cd /opt/calib-system && scripts/backup.sh
set -e
mkdir -p backups
. ./.env
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "backups/calib_$(date +%F).sql.gz"
find backups -name 'calib_*.sql.gz' -mtime +30 -delete
