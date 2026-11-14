# 后端物理分层验收记录（2026-11-14）

## 1. 执行范围

把原先混在 `app/modules/<domain>/` 的模型、业务规则、路由、DTO 物理拆开：

| 层 | 目录 | 文件数 | 职责 |
|---|---|---:|---|
| 基础层 | `app/core/` | 32 | 配置、DB/RLS、租户、安全、日志、限流、邮件、存储、监控 |
| 核心业务层 | `app/domain/` | 17 个领域包 | 实体模型、业务规则、领域服务 |
| 应用编排层 | `app/application/` | 2 | 定时任务、跨领域编排 |
| 接入层 | `app/interfaces/http/` + `app/api/` | 17 个 HTTP 包 + 系统入口 | 路由、请求/响应 DTO、HTTP 依赖 |

领域包：announcements、catalog、comments、doi、export、follows、forum、gamification、ingest、library、notifications、quality、reader、recommendations、release、review、submission。

旧的 `app.modules/<domain>/<file>.py` 全部变成兼容壳，只做 re-export，并带固定 `Compatibility shim` 注释；`app.modules/<domain>/__init__.py` 只保留模块清单。

## 2. 依赖方向检查（代码级强制）

| 检查项 | 结果 |
|---|---|
| `domain` 是否 import `app.api` / `app.interfaces` / `app.modules` / `fastapi` | 0 处 |
| `core` 是否 import `domain` / `interfaces` / 业务模块 | 0 处（`core/modules.py` 组合根例外） |
| `domain` 是否残留 `APIRouter` | 0 处；原 `review/workbench.py` 已移到 `interfaces/http/review/workbench.py` |
| `application` 是否 import `interfaces` | 0 处；`review_reminders` 调度已移入 `application/scheduler.py` |
| 旧 `modules` 下是否还有真实实现 | 0 个；只剩清单与兼容壳 |

CI 中的 `tests/test_architecture_layers.py` 会扫描 AST，逆向依赖直接失败。

## 3. 行为不变证明

- 迁移前后 OpenAPI 都为 **240 条路径**，逐条集合比对 **完全一致**（无新增、无缺失）。
- URL 前缀、数据库表名、请求/响应结构未改。
- 定向回归：`test_architecture_layers`、投稿工作流、审稿工作台、ingest、导出文档、DOCX 模板、等级轴共 **96 passed**。
- 迁移过程中曾出现一次「兼容壳被静态检查误删」：`routes_editor` 的副作用导入被 ruff 当作未使用导入删除，OpenAPI 少 10 条编辑/审稿端点；已改为显式 `import_module`，并新增 `test_submission_editor_routes_are_mounted` 固定这 10 条路径。
- DOCX 刊头 logo 素材未随迁导致首轮 1 failed，已迁到 `app/domain/submission/assets`，`test_docx_template.py` 7/7。
- `ruff check .`、`ruff format --check .`、`mypy app` 全绿。
- 最终全量后端回归：**1155 passed, 1 skipped**（10 分钟），0 failed。

## 4. 分角色验收

| 角色 | 检查内容 | 证据/结果 |
|---|---|---|
| 访客 | 首页、目录、文章详情、论坛、帮助/政策；移动端横向溢出 | 390px 12 个主页面只有首页 406px，已修源码；其余 23 个次级页面 390/390 |
| 作者 | 投稿、文件上传、版本快照、稿件公开、DOCX/PDF 导出 | 投稿工作流与导出测试通过 |
| 审稿人 | 审稿工作台、待审/已审、逾期标记、编辑台 403 | `test_workbench.py` 通过 |
| 编辑/主编 | 四列工作台、审稿人负载、批量指派、冲突检查、提醒 | 工作台单测通过；生产四列数据待指派 0 / 评审中 4 / 待裁决 0 / 已决定 279 |
| 管理员 | 用户、角色、反馈墙、系统健康、资源后台 | 管理端接口与页面烟测通过；反馈墙 open=0 |

## 5. 已知缺口（不冒充已完成）

1. `app/api/` 的系统级路由（auth、admin、health、OIDC）仍独立于 `app/interfaces/http/`，属于接入层的系统入口分区，未并入 `interfaces/http/system`。
2. `app/models/__init__.py` 仍是身份/租户内核大文件，尚未按 identity/tenant/audit 再拆。
3. `domain` 已不依赖 FastAPI，但部分业务异常仍复用 `core` 抛出的 HTTP 400/404 语义；还没有独立的 `DomainError` 体系。
4. 前端仍是 `routes/components/hooks` 组织，没有按领域建 `features` 层；页面直接取数的问题还在。
5. 1706 的「卡片内指派审稿人」只在代码与单测级验证；生产待指派队列为 0，无法在空队列上真实点击。
6. 生产没有纯 `editor_in_chief` 且 `is_admin=false` 的账号，主编最小权限链路仍是代码级兜底。
7. CNKI/CrossCheck 真查重、SMTP 真发信、第三方图片审核仍缺外部账号或预算。
8. 全站英文翻译、全量无障碍审计未做。
9. 首页移动端溢出修复已提交，但**未部署生产**。
