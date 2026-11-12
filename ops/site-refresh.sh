#!/usr/bin/env bash
# 每日预热：把首页、列表、最新文章、sitemap/RSS 走一遍，发版后也立即调用。
set -euo pipefail
BASE="${BASE:-https://rubbish.argjiemi.cn}"
LOG="${LOG:-/home/ubuntu/rubbish-refresh.log}"
note(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

for i in $(seq 1 30); do
  curl -fsS -m 5 "$BASE/api/health" >/dev/null 2>&1 && break
  sleep 2
done

for p in / /papers /fun /sitemap.xml /rss.xml /api/health /api/catalog/stats; do
  code=$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_starttransfer}' "$BASE$p" || true)
  note "warm $p $code"
  [ "${code%% *}" = 200 ] || exit 1
done

ids=$(curl -sS -m 20 "$BASE/api/catalog?page=1&page_size=5&sort=created_at&order=desc" \
  | python3 -c 'import sys,json;print(" ".join(str(x["id"]) for x in json.load(sys.stdin).get("data",[])))' 2>/dev/null || true)
for id in $ids; do
  code=$(curl -sS -m 20 -o /dev/null -w '%{http_code} %{time_starttransfer}' "$BASE/catalog/$id" || true)
  note "warm /catalog/$id $code"
  [ "${code%% *}" = 200 ] || exit 1
done
note "refresh done"
