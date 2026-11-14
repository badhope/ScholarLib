# Architecture

Rubbish 的架构契约文档。每个模块都要遵守,偏离即 bug。

## 一句话概括

Rubbish 是一个**模块化、多租户的学术期刊发表平台**:核心只持有身份、租户、角色、模块注册表;每个领域能力(投稿、审稿、阅读、订阅、推荐...)都作为独立模块在启动时挂载到核心。

## 两层模型

```
┌─────────────────────────────────────────────────────────────┐
│                    前端 SPA  (apps/frontend)                  │
│   核心外壳  +  各启用模块贡献的 UI 路由 chunk                    │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP / SSE / WebSocket
┌──────────────────────────┴──────────────────────────────────┐
│                    后端 API  (apps/backend)                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  core:  租户 · 身份 · 角色 · 模块注册表 · admin · 部署    │ │
│  └───────────────────────┬─────────────────────────────────┘ │
│                          │ 启动时按依赖顺序加载                  │
│  ┌──────────┬────────────┴───────────┬──────────┬───────────┐ │
│  │ catalog  │ submission │ review  │ reader   │ export    │ │
│  ├──────────┼────────────┼─────────┼──────────┼───────────┤ │
│  │ follows  │ library    │ ingest  │recomm.   │notif.     │ │
│  ├──────────┼────────────┼─────────┼──────────┼───────────┤ │
│  │gamificat.│announcem.  │ quality │          │           │ │
│  └──────────┴────────────┴─────────┴──────────┴───────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   PostgreSQL 17      Redis (规划中)     object storage (规划中)
   (主库 + RLS)       (缓存 + 限流)       (PDF、上传文件)
```

## 物理分层（2026-11 起）

架构不再只靠 `app/modules/<name>/` 把模型、服务、路由混在一个包里。真实代码按依赖方向分到四层：

```text
apps/backend/app/
├── core/               基础层：配置、DB、安全、租户、日志、限流、邮件、存储
├── domain/             核心业务层：实体模型、业务规则、领域服务
│   ├── catalog/ submission/ review/ notifications/ gamification/
│   └── ... 共 17 个领域包
├── application/        应用编排层：跨领域后台任务、定时调度
│   ├── scheduler.py
│   └── ...
├── interfaces/http/    接入层：路由、请求/响应 DTO、HTTP 依赖
│   ├── catalog/ submission/ review/ ... 共 17 个 HTTP 包
│   └── system/ （预留：系统级 API）
├── api/                系统级 HTTP 入口（auth、admin、health、OIDC 等）
├── models/             身份/租户内核模型与共享 Base
└── modules/            组合清单 + 兼容壳（不再是业务实现所在地）
```

### 依赖方向（CI 强制）

| 层 | 可以依赖 | 禁止依赖 |
|---|---|---|
| `core` 基础层 | 第三方库、`app.models` | `domain` / `application` / `interfaces` / 业务 `modules` |
| `domain` 核心业务层 | `core`、`app.models`、同层领域 | `api` / `interfaces` / `modules` |
| `application` 应用编排层 | `core`、`domain` | `interfaces` |
| `interfaces` 接入层 | `core`、`domain`、`application` | 反向被内层依赖 |

唯一例外是 `core/modules.py`：它是组合根，负责加载模块清单。`tests/test_architecture_layers.py` 会在 CI 中扫描 AST，发现反向依赖即失败。

### 兼容策略

- 旧 `app.modules.<domain>.<file>` 路径保留为**只做 re-export 的兼容壳**，注释固定以 `Compatibility shim` 开头。
- `app.modules.<domain>/__init__.py` 保留模块清单（名称、版本、依赖、router），它不是业务实现。
- 迁移不改变 URL、数据库表名、OpenAPI 路径；迁移前后 OpenAPI 240 条路径逐条比对一致。
- 新增业务代码一律写进 `app/domain` 与 `app/interfaces/http`，不再往 `app/modules` 里放实现。

## 核心层(core)负责什么

核心层刻意保持最小,只承担每个学术期刊站点都需要的"地基":

1. **租户** — 每个领域表都带 `tenant_id`。单租户部署只有一行 + `RUBBISH_TENANCY_MODE=single`;多租户部署通过 host-header 解析租户并按 `tenant_id` 隔离数据。**单租户模式已实现**,多租户模式(host-header → tenant 查找表)尚未实现(`TenantContextMiddleware._resolve_tenant` 默认返回 `None` 即 default-deny)。

2. **身份与访问** — 本地用户账号(已实现)、按租户隔离的角色 + 权限模型(已实现)、短时 access token + httpOnly cookie refresh(已实现)。邮件验证 + 密码重置(无状态签名 token 绑定 `token_version`,已实现)。OIDC SSO via authlib(Google / GitHub / Generic / Keycloak,已实现,通过环境变量配置)。邮件发送走可插拔 sender(console dev / SMTP relay for Mailgun / SendGrid / SES / Postmark,已实现)。

3. **模块注册表** — 后端启动时按依赖顺序加载 `app/modules/<name>/` 下的每个模块,每个模块声明自己的名字、依赖、模型、路由、admin hooks。核心按拓扑序挂载并运行各自的迁移,前端通过 `/api/modules` 端点知道渲染哪些 UI。

4. **admin shell** — `app.api.admin` 提供按租户隔离的 admin REST API:用户列表 + 启用/停用、审计日志。React SPA 在 `/admin` 下展示。角色/权限编辑、模块启停尚未实现。

5. **部署** — Docker Compose(dev + prod)、Caddy TLS、Alembic 迁移在容器启动时执行、structlog JSON 日志、health 端点上报模块加载状态。详见 [docs/integrations.md](integrations.md) 的 SMTP + OIDC + Crossref/arXiv 接入。


## 身份体系 3.0（1.9.0 起）

**身份管权限，积分只是荣誉。** 这是等级系统唯一需要记住的一句话。

- **四层身份**（`ladder.py`，代码即口径）：读者（注册即得）→ 作者
  （确认当版《投稿规范》，合规动作而非门槛）→ 审稿人（编辑部授予）→
  编辑（提拔）。映射到后端 `require_reader` / `require_author` /
  `require_reviewer` / `require_editor`，不存在"等级到了权限没到"的错位。
- **XP 是荣誉统计**：只回答"参与了多少"，不决定任何权限。评论、阅读
  列表、关注这些社交动作不再有积分门槛——拦真实读者没有收益。
- `require_level(n)` 保留为废弃别名：内部按身份序号判定，防止遗漏调用点
  回退到积分模型。
- 审稿人申请、27 枚成就、每日签到保留；签到与积分只出现在个人页，
  不再出现在任何权限路径上。

## 双赛道（track）

`submissions.track` 与 `resources.track`（serious / absurd，CHECK 约束 +
复合索引，迁移 013）。投稿时作者必选——赛道是写作意图的声明，不是质量
评级；目录公开面按赛道筛选，统计分赛道报（`by_track`），详情页展示赛道
徽章。历史数据全部落 `serious`（保守侧：误标正经稿为荒诞的伤害更大）。

## 质量评分与公告（1.0.0 起）

- **gamification** — 四层身份、XP 台账（`user_xp_events`，唯一约束保证
  幂等）、成就定义（`badges.py`，27 枚）；投稿门禁绑定
  `rules_ack_version`，规范改版后旧确认自动失效。
- **announcements** — 单表 + 发布窗口；公开只读 `/api/announcements/active`，
  管理员 CRUD 带审计。首访卡由前端 localStorage 记忆。
- **quality** — RQS v1.0 评分口径（`rubric.py`）：四类稿件画像各自一套
  维度权重（合计 100），等级带 A+/A/B/C/D。评分由离线流水线写入
  `resources.quality_*`，运行时只读；口径公开在 `/api/quality/rubric`。

## 模块长什么样

模块是 `app/modules/<name>/` 下一个自包含的包,固定形态:

```
app/modules/<name>/
├── __init__.py            # 通过 ModuleManifest 注册到核心
├── models.py             # SQLAlchemy 模型,全部带 tenant_id
├── schemas.py            # Pydantic 请求/响应类型
├── routes.py             # FastAPI router,挂载在 /api/<name>
├── services.py           # 业务逻辑(跨模块复用时才写)
└── (tests 在 apps/backend/tests/test_<name>.py)
```

模块之间**默认不互相 import**;若需跨模块调用,必须在 `ModuleManifest.dependencies` 中声明。核心在启动时检查依赖图,有环或缺依赖会拒绝启动。

## 租户隔离与迁移

- 每个领域表都有非空 `tenant_id` 列,带索引。
- **双层隔离防御**:
  - **Layer 1 应用层**:每个 SELECT/UPDATE/DELETE 都显式追加 `Model.tenant_id == require_tenant_id()`(或 `current_user.tenant_id`)。漏写过滤是 bug。
  - **Layer 2 数据库层**:PostgreSQL RLS。`app.core.db.get_db` 在每个事务 BEGIN 时 `SET LOCAL app.current_tenant_id = :tid`(通过 `after_begin` 事件监听器),即使应用层漏写过滤,数据库也会拒掉跨租户行。SQLite 测试环境跳过 RLS(SQLite 没有 RLS),所以应用层过滤是强制的,由 `tests/test_rls_isolation.py` 在 PostgreSQL 17 上验证。
- 迁移文件在 `apps/backend/alembic/versions/`,每个模块一份,编号 `NNN_<module>_module.py`。共享的 `target_metadata = Base.metadata`(见 `alembic/env.py`)会自动检测新模块表,因为每个模块都从 `app.models` 导入 `Base`。
- 单租户模式 = 多租户模式里只有一行;没有独立代码路径,没有 `if single_tenant` 分支。

## 前端组合

`apps/frontend/` 下是一个单 SPA。技术栈:React 19 + TypeScript + Vite 7 + Tailwind CSS v4 + TanStack Router v1(file-based + autoCodeSplitting)+ TanStack Query v5 + Zustand(auth store)+ shadcn/ui。

覆盖全部 10 个领域模块:catalog 列表/详情/创建、reader(PDF 嵌入 + 进度 + 历史)、submissions(作者 + admin 审稿)、ingest(BibTeX/RIS/CSV 解析 + Crossref/arXiv 抓取)、library(阅读列表 CRUD + 增删条目)、notifications、recommendations、admin(用户 + 审计日志)。Auth 流程覆盖登录/注册/登出、邮件验证、密码重置、OIDC SSO 回调。一个镜像同时打包后端 + 前端,版本不会漂移。

## 我们选择不做的事

- **不做插件市场**:模块在本仓库内 vendored。第三方模块通过 fork 仓库安装,我们不跑 registry。
- **不做 per-module 数据库**:所有模块共享租户的 PostgreSQL,跨模块 join 仍然可行。
- **不做 per-module 独立前端**:一个 SPA、一个 bundle、一次部署。模块 UI 是路由 chunk,不是独立 app。
- **不做事件总线**:跨模块通信走显式 service 方法,不走 pub/sub 层。submission 模块要通知 follows 模块,直接调用 service,不发消息。

## 参考

- [README.md](../README.md) — 项目概览与路线图
- [docs/integrations.md](integrations.md) — SMTP 邮件 + OIDC SSO + Crossref/arXiv 接入指南
