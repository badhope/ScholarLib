#!/usr/bin/env bash
# 站点实时健康检查：HTTP、HTML 缓存头、API、备份新鲜度、磁盘、容器。
set -uo pipefail
BASE="${BASE:-https://rubbish.argjiemi.cn}"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
LOG="${LOG:-/home/ubuntu/rubbish-health.log}"
fail=0
note(){ printf '[%s] %s\n' "$(date -Is)" "$*" >> "$LOG"; }
bad(){ fail=1; note "FAIL $*"; }

code=000
for i in $(seq 1 5); do
  code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$BASE/" || echo 000)
  [ "$code" = 200 ] && break
  sleep 3
done
[ "$code" = 200 ] || bad "home=$code"
curl -sS -m 15 -D - -o /dev/null "$BASE/" | grep -qi 'cache-control: no-cache' || bad "html cache-control missing"
code=000
for i in $(seq 1 5); do
  code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$BASE/api/health" || echo 000)
  [ "$code" = 200 ] && break
  sleep 3
done
[ "$code" = 200 ] || bad "health=$code"
total=0
for i in $(seq 1 5); do
  total=$(curl -sS -m 15 "$BASE/api/catalog/stats" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total",0))' 2>/dev/null || echo 0)
  [ "${total:-0}" -ge 200 ] && break
  sleep 3
done
[ "${total:-0}" -ge 200 ] || bad "stats total=$total"

db=$(ls -1t "$BACKUP_DIR"/db-*.sql.gz 2>/dev/null | head -1)
up=$(ls -1t "$BACKUP_DIR"/uploads-*.tar.gz 2>/dev/null | head -1)
for f in "$db" "$up"; do
  [ -n "$f" ] && [ -f "$f" ] || { bad "backup missing"; continue; }
  age=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 3600 ))
  [ "$age" -le 36 ] || bad "stale backup $(basename "$f") ${age}h"
done

disk=$(df -P / | awk 'NR==2{gsub("%","",$5);print $5}')
[ "$disk" -le 85 ] || bad "disk ${disk}%"
for c in rubbish-app-1 rubbish-db-1 rubbish-caddy-1; do
  st=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
  [ "$st" = running ] || bad "$c=$st"
done

[ "$fail" -eq 0 ] && note "OK home=200 stats=$total backup=${db##*/} disk=${disk}%"
exit "$fail"
