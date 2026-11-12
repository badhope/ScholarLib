# RUBBISH 技术债与未完成项收口记录（2026-11-12）

本记录只写“实际做完并验证”的事，以及“不能靠代码伪造、只能保留诚实状态”的边界。线上站点：<https://rubbish.argjiemi.cn>。

## 1. 线上分叉已合回

- 线上 `bd309eb` 之后的 102 个已跟踪修改、88 个未跟踪文件、2 个 stash，已整理为 `server-snapshot-20261112`（`e291dd9`，148 files）。
- 打包 `/home/ubuntu/server-snapshot-20261112.bundle`（58M），scp 回本地后合并为 `merge/server-debt`（`8b12d15`）。
- 55 个冲突逐文件判断，统一保留本地较新线（v5、视觉、telemetry、sections、genre、appeals、page_views、审稿附件、adjudication），合并后后端 73 项相关测试通过、前端 `tsc` 0 错误。
- 合并快照已实际部署，不是只留在本地分支。

## 2. 评分 v5.0 已上线

- 后端 `RUBRIC_VERSION = 5.0`：
  - 学术：选题 20 / 论证 25 / 方法 20 / 证据 20 / 诚信 15；
  - 荒诞：设定 25 / 自洽 20 / 执行 20 / 材料 20 / 文风 15。
- 分区：T1+ 95–100、T1 90–94、Q1 80–89、Q2 70–79、Q3 60–69、Q4 50–59、R 0–49。
- 硬门槛：任一维 <60 封顶 79；任一维 <50 封顶 59；两项及以上 <50 封顶 49；学术论证 <50 封顶 59；荒诞自洽 <50 封顶 59、执行 <50 封顶 69；学术诚信 0 分总分归零。
- 每维必填 `score + reason + evidence`。提交接口按分数段加严：90+ 理由 ≥40 字、证据 ≥60 字；80–89 理由 ≥15、证据 ≥20；80 以下理由 ≥4、证据 ≥10；证据必须含章节/段落/图/表/页/引用/文献/附录/链接之一。
- 前端审稿弹窗逐维显示分数、权重、锚点、`为什么给这个分`、`正文证据`；提交前先按同一门槛拦截，不再出现“哪里都有分”的空泛理由。
- 线上验证：`GET /api/quality/rubric` 返回 `version=5.0`，grades 为 `T1+/T1/Q1–Q4/R`。

## 3. 样稿严格评分与界面证明

- 报告：`review-pack/v5-scorecards-2026-11-12-strict.md`（268 行）。
- 最终分数：226 = 82.6 Q1；225 = 74.9 Q2；94 = 69.9 Q3；55 = 59.4 Q4；没有一篇到 90。
- 界面截图（真实前后端填写，不是静态稿）：
  - `visual-check/review-ui/academic-94-strict.png`（69.9 / Q3，五维 74/70/62/66/80）；
  - `visual-check/review-ui/absurd-225-strict.png`（74.9 / Q2，五维 82/74/78/60/80）；
  - 对应 `-full`、`-part1`、`-part2` 长图与 `.box.json`。
- 实际提交验证：`POST /api/review/assignments/2/submit` 返回 201；`review_reports id=1` 落库 `score=69.9`、`grade=Q3`、五维 `74/70/62/66/80`。

## 4. 配置开关已收口

- 新增 `apps/backend/app/core/site_settings.py`：租户级布尔开关存 `tenants.settings`，与 `review_mode` 同一 JSON；提供 `get_site_flag / get_all_site_flags / set_site_flag`。
- 新增 `GET/PATCH /api/admin/settings/site`，写审计 `admin.settings.site`；后台 `/admin/settings` 新增“注册与题录开关”卡片。
- 注册验证码：`RUBBISH_CAPTCHA_REQUIRED_FOR_REGISTRATION` 默认 False；生产 `.env` 已显式设 `true`，`docker-compose.yml` 已透传，线上 `/api/capabilities` 返回 `true`，不会因部署误关。
- DOI 作者自填：`doi_author_entry_enabled` 开关；关闭后投稿表单隐藏 DOI 输入，已保存 DOI 不删除。
- 调度器：去掉 `STARTUP_DELAY_SECONDS = 10**9` 的假死逻辑，改为 `scheduler_startup_delay_seconds=300`、`scheduler_interval_seconds=21600`，可在 `.env` 调。

## 5. 数据债已回填并复验

生产租户 `ba9a864d-d300-48eb-94da-38e82840aa47`：

| 项 | 回填前 | 动作 | 回填后 |
|---|---:|---|---:|
| `authors_meta` 空 | 246 | 从 `resources.authors` 派生 `name/order/roles`，不补邮箱/机构/ORCID | 0（备份表 `resources_authors_meta_backup_20261112` 246 行） |
| `keywords` 空 | 11 | 把 `tags` 复制到 `keywords` | 0（备份表 `resources_keywords_backup_20261112` 11 行） |
| `reviewed_at` | 无字段 | 新增 029 migration + 索引，从 `submissions.reviewed_at` 按 `resource_id` 回填 | 265/274 有值 |

复验链路：

- `GET /api/catalog?limit=3` → 200；
- `GET /api/catalog/26` → 200，`authors_meta` 三作者 `order/roles` 正常，`keywords` 有值；
- `GET /api/catalog/26/file` → 200，220955 bytes，OOXML（Word）；
- 生产 `alembic_version = 029_resource_reviewed_at`。

不能伪造的项，保留诚实状态：

- `issn` 空 274：ISSN 仍在申请中，站内刊号不等同官方 ISSN；
- `doi` 空 274：DOI 由作者自填或后续注册，不批量生成假 DOI；
- 28 篇“佚名”：投稿表里没有邮箱，不能凭空恢复真实作者；
- 12 篇 <120 字摘要：栏目说明/编者按，不是论文摘要，不强行扩写。

## 6. 视觉/缓存/内容债

- `/about` 删除虚构编委姓名、头衔、机构与“编辑部化名”阵容，改为真实六岗职责（主编/学术编辑/副刊编辑/出版伦理/技术出版/审稿人池），只写职责不写人名；刊史改为真实四段；明确“ISSN 申请中，站内刊号不等同官方 DOI”。
- 新增 `public/favicon.ico`（16/32/48/64），`index.html` 显式 `<link rel="icon">`，线上 `/favicon.ico` 200，`image/vnd.microsoft.icon`。
- `/api/` 响应统一 `Cache-Control: no-store`，避免权限/列表被浏览器 heuristic cache；已加测试。
- `qualityGrade` 从旧十六档 A+–F 改为 v5 `T1+/T1/Q1–Q4/R`，旧 grade 有 `LEGACY_GRADE_MAP` 兜底，分数优先。
- `/policies` 评分口径改为 v5 五维两段式、分区与封顶规则，删除“14 档 A+ 至 F”。

## 7. 测试与构建

- 后端全量：见最终运行结果（本轮重新跑全量，不再只跑分组）。
- 前端：`tsc -b && vite build` 通过；`vitest run` 21 files / 134 tests 通过；`eslint .` 0 errors（6 个既有 hook warning）。
- 前端构建产物：`index-lw5d5Na_.js` / `index-8_PeqTPg.css`。
- 生产已 `docker compose up -d --build app` 重建并启动；线上首页已引用新资产，`/api/health` 200，`/api/catalog?limit=1` 200。

## 8. 仍需外部条件、不能靠代码单独完成

这些不是“没做”，而是必须有外部账号、授权或政策决定，代码侧已留好开关/诚实状态：

- ISSN 正式号、DOI 注册前缀：需要官方受理/注册机构账号；
- SMTP 凭据迁移到 secret、凭据轮换：需要运维授权与新凭据；
- SSH 22 对 Anywhere 开放收紧：需要确认运维入口与防火墙策略；
- 240 个旧 `quality_score` 与 29 条旧 `review_scores` 的历史口径统一：需要编辑部决定“旧分是否重算/是否只展示新审稿报告”，不能擅自改写历史评分；
- 站点定位（真期刊 / 讽刺项目 / 双轨）与荒诞赛道是否加“诚信一票否决”：需要主编拍板，当前按双轨与学术诚信否决执行。

## 9. 回滚点

- 线上代码备份：`/home/ubuntu/backup_app_20261112`；
- 线上静态备份：`apps/backend/prebuilt-static-20261112`；
- 数据备份：`resources_authors_meta_backup_20261112`、`resources_keywords_backup_20261112`；
- 本地分支：`merge/server-debt`（`8b12d15`）、`server-snapshot-20261112`（`e291dd9`）、`feat/rqs-v5`（`3d4f63b`）。

## 10. 2026-11-12 技术侧再收口（本轮）

- **旧页面根因**：HTML 壳无 `Cache-Control`。已给非 API、非 `/assets/`、非 `/covers/` 统一加 `no-cache, must-revalidate`；线上 `/`、`/sitemap.xml` 已复验，静态资源仍 `immutable`。
- **移动端视觉**：Cookie 条移到底部导航上方，`全部接受` 不再被反馈气泡遮挡（Cookie 未处理时反馈气泡 `display:none`）；首页 header/hero 加 `px-4 sm:px-6`，四张数据卡不再贴边。
- **图表性能**：`echart.tsx` 改为运行时按需加载，首页不再请求 `core/charts/components` 约 520K；指标页图表仍正常渲染。
- **字体性能**：按 274 篇题录/摘要 + 全部前端 UI 的 2417 个实际汉字生成单文件子集，`Noto Serif SC` 从首页 46 个分片、约 3.0MB 解码体积降到 2 个文件、约 1.4MB；线上首屏已复验，无缺字。
- **发布链路**：`ops/deploy.sh` 实际跑通“构建→备份旧静态→替换→重启→健康→预热→失败回滚”，并修掉生产 `/tmp` tmpfs 配额坑，中转目录改到 `/home/ubuntu`。
- **自动化**：健康检查 5 分钟、预热每日 04:10、恢复演练每周日 04:30、异地备份每日 04:50；2026-11-12 21:00 定时健康检查实际触发并通过。
- **异地备份边界**：生产已装 `rclone`，`ops/offsite-backup.sh` 与 cron 已就位；无 `RCLONE_REMOTE` 时明确 `SKIP`。当前仍缺对象存储/第二台机器的目标与凭证，不能宣称异地已备份。
- **剩余客观项**：应用冷启动首次 TTFB 约 4.16s，发布脚本已用健康检查+预热兜住真实用户；字体子集未覆盖的极生僻字会回退系统衬线，属预期降级。
