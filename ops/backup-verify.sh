#!/usr/bin/env bash
# 每周备份演练：解压校验 + 临时库恢复 + 行数核对 + 上传包可列出。
set -euo pipefail
cd /home/ubuntu/rubbish
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
LOG="${LOG:-/home/ubuntu/rubbish-backup-verify.log}"
DB=rubbish_restore_check
note(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

db=$(ls -1t "$BACKUP_DIR"/db-*.sql.gz | head -1)
up=$(ls -1t "$BACKUP_DIR"/uploads-*.tar.gz | head -1)
note "checking $(basename "$db") / $(basename "$up")"
gzip -t "$db"; tar -tzf "$up" >/dev/null

cleanup(){ docker compose exec -T db psql -U rubbish_legacy -d postgres -c "drop database if exists $DB" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose exec -T db psql -U rubbish_legacy -d postgres -c "drop database if exists $DB" >/dev/null
docker compose exec -T db psql -U rubbish_legacy -d postgres -c "create database $DB" >/dev/null
gunzip -c "$db" | docker compose exec -T db psql -U rubbish_legacy -d "$DB" -v ON_ERROR_STOP=1 >/dev/null
n=$(docker compose exec -T db psql -U rubbish_legacy -d "$DB" -Atc 'select count(*) from resources')
[ "$n" -ge 200 ] || { note "FAIL resources=$n"; exit 1; }
note "restore ok resources=$n"
