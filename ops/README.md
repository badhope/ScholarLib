# 运维自动化

| 脚本 | 频率 | 作用 |
|---|---|---|
| `site-health.sh` | 每 5 分钟 | HTTP、HTML `no-cache`、API、stats、备份≤36h、磁盘≤85%、三容器 |
| `site-refresh.sh` | 每日 04:10 | 首页/论文/副刊/sitemap/RSS/API + 最新 5 篇预热 |
| `backup-verify.sh` | 每周日 04:30 | 解压校验、临时库恢复、resources 行数核对 |
| `deploy.sh` | 手动/CI | 构建、容器内旧静态备份、替换、重启、健康检查、预热、失败回滚 |
| `offsite-backup.sh` | 每日 04:50 | rclone 异地备份；无远端时明确 SKIP，配置 `RCLONE_REMOTE` 后自动生效 |
| `install-automation.sh` | 一次性 | 幂等写 `/etc/cron.d/rubbish-automation` |

日志：`/home/ubuntu/rubbish-health.log`、`rubbish-refresh.log`、`rubbish-backup-verify.log`。

## 异地备份启用方式

生产机已安装 `rclone`。拿到对象存储或另一台服务器的凭证后，在 `/home/ubuntu/rubbish/ops/offsite.env` 写：

```bash
RCLONE_REMOTE=rubbish-cos:rubbish-backups
```

并确保运行 `offsite-backup.sh` 的用户能读到该环境变量；脚本会复制最新 DB 与上传包并做 size 校验。
未配置时每日 04:50 只记录 `SKIP`，不会伪装成已备份。
