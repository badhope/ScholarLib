#!/usr/bin/env bash
# 幂等安装：健康检查 5 分钟、预热每日 04:10、备份演练每周日 04:30。
set -euo pipefail
R=/home/ubuntu/rubbish
sudo tee /etc/cron.d/rubbish-automation >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * ubuntu /home/ubuntu/rubbish/ops/site-health.sh >> /home/ubuntu/rubbish-health.log 2>&1
10 4 * * * ubuntu /home/ubuntu/rubbish/ops/site-refresh.sh >> /home/ubuntu/rubbish-refresh.log 2>&1
30 4 * * 0 ubuntu /home/ubuntu/rubbish/ops/backup-verify.sh >> /home/ubuntu/rubbish-backup-verify.log 2>&1
CRON
sudo chmod 644 /etc/cron.d/rubbish-automation
sudo touch /home/ubuntu/rubbish-health.log /home/ubuntu/rubbish-refresh.log /home/ubuntu/rubbish-backup-verify.log
sudo chown ubuntu:ubuntu /home/ubuntu/rubbish-health.log /home/ubuntu/rubbish-refresh.log /home/ubuntu/rubbish-backup-verify.log
echo "installed /etc/cron.d/rubbish-automation"
