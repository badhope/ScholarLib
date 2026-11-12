#!/usr/bin/env bash
# 一条命令发布：构建 → 备份容器内旧静态 → 替换 → 重启 → 健康检查 → 预热。
set -euo pipefail
HOST="${HOST:-rubbish}"
REPO="${REPO:-/home/ubuntu/rubbish}"
cd "$(dirname "$0")/../apps/frontend"
npm run build
tar czf /tmp/rubbish-dist.tgz -C dist .
scp -q /tmp/rubbish-dist.tgz "$HOST:/tmp/rubbish-dist.tgz"
ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
REPO="${REPO:-/home/ubuntu/rubbish}"
stamp=$(date +%Y%m%d-%H%M%S)
rm -rf /tmp/rubbish-newstatic && mkdir -p /tmp/rubbish-newstatic
tar xzf /tmp/rubbish-dist.tgz -C /tmp/rubbish-newstatic
docker exec rubbish-app-1 rm -rf "/app/static.bak-$stamp" || true
docker cp rubbish-app-1:/app/static "/tmp/static-rollback-$stamp"
docker cp /tmp/rubbish-newstatic/. rubbish-app-1:/app/static/
docker restart rubbish-app-1 >/dev/null
sleep 8
if ! bash "$REPO/ops/site-health.sh"; then
  echo "health failed, rolling back"
  docker cp "/tmp/static-rollback-$stamp/." rubbish-app-1:/app/static/
  docker restart rubbish-app-1 >/dev/null
  exit 1
fi
bash "$REPO/ops/site-refresh.sh"
# 只保留最近 3 份容器内静态备份
docker exec rubbish-app-1 sh -c 'ls -1dt /app/static.bak-* 2>/dev/null | tail -n +4 | xargs -r rm -rf'
echo "deployed $stamp"
REMOTE
