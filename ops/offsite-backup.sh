#!/usr/bin/env bash
# 异地备份：只备份数据库 + 上传文件，不备份代码/镜像/构建产物。
# 代码随时可从远程仓库取；配置 rclone 远端后启用；未配置时明确 SKIP，不假装已备份。
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/backups}"
LOG="${LOG:-/home/ubuntu/rubbish-offsite.log}"
ENV_FILE="$(dirname "$0")/offsite.env"
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
REMOTE="${RCLONE_REMOTE:-}"
note(){ printf '[%s] %s\n' "$(date -Is)" "$*" >> "$LOG"; }
if [ -z "$REMOTE" ]; then note "SKIP rclone remote not configured"; exit 0; fi
command -v rclone >/dev/null || { note "FAIL rclone missing"; exit 1; }
db=$(ls -1t "$BACKUP_DIR"/db-*.sql.gz | head -1)
up=$(ls -1t "$BACKUP_DIR"/uploads-*.tar.gz | head -1)
rclone copy "$db" "$REMOTE/rubbish/db/" --checksum
rclone copy "$up" "$REMOTE/rubbish/uploads/" --checksum
rclone check "$db" "$REMOTE/rubbish/db/$(basename "$db")" --size-only
note "offsite ok $(basename "$db") $(basename "$up")"
