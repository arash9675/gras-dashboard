#!/bin/sh
# Nightly database backup: a compressed pg_dump of the running stack, keeping
# the last 14 days. Run it from the repository folder, for example from cron:
#
#   15 3 * * * cd /home/ubuntu/GRAS && ./ops/backup.sh >> backups/backup.log 2>&1
#
# Restore one with:
#   docker compose exec -T db pg_restore -U gras -d gras --clean --if-exists < backups/gras-YYYY-MM-DD.dump
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
# Only the two names we need; .env may hold JSON that a shell cannot source.
POSTGRES_USER=$(sed -n "s/^POSTGRES_USER=//p" .env 2>/dev/null)
POSTGRES_DB=$(sed -n "s/^POSTGRES_DB=//p" .env 2>/dev/null)
out="backups/gras-$(date +%F).dump"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-gras}" -d "${POSTGRES_DB:-gras}" -Fc > "$out.tmp"
mv "$out.tmp" "$out"
find backups -name 'gras-*.dump' -mtime +14 -delete
echo "$(date -Is) backup written: $out ($(du -h "$out" | cut -f1))"
