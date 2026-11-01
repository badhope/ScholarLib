# Rubbish 上线部署指南

> 代码状态：backend 644 tests / coverage 84%，frontend 100 tests，ruff/mypy/tsc 全绿；
> CI 7 jobs（backend / migrations / frontend / e2e / precommit / security / docker-build 镜像门禁）。
> 安全加固（TOTP 重放防线、GDPR 恢复可达性、2FA 租户过滤）见 CHANGELOG，commit `114f8d1`。

> **本文档定位**：面向「自建一套」的部署者（开源示例用途），从零拉起一套属于你自己的
> Rubbish 实例。生产实例 rubbish.argjiemi.cn 的日常运维（备份/恢复/看门狗/更新）有独立的
> 运维手册，不在本文展开；两者共用同一套 compose 编排与镜像。

## 架构总览（推荐方案）

| 组件 | 推荐服务 | 说明 |
|---|---|---|
| 前端 SPA | **Cloudflare Pages** | 或走"单端口模式"由后端直接托管（见方案 B） |
| 后端 FastAPI | **Railway / Render / Fly.io / VPS** | ⚠️ Cloudflare Workers **跑不了** Python SQLAlchemy+asyncpg，后端必须落在一个能跑 Python 的宿主上 |
| PostgreSQL | **Neon / Supabase**（免费档可用） | 必须 PG：RLS 第二层隔离只在 PG 生效 |
| 文件存储（PDF） | **Cloudflare R2**（S3 兼容） | `storage.py` 已支持 S3 后端 + 预签名直链，R2 免出流量费 |

```
用户 ── Cloudflare DNS/CDN ──┬── Pages（前端静态）
                             └── 后端容器（Railway/Render/Fly）
                                    ├── Neon PostgreSQL（数据 + RLS）
                                    └── R2（PDF 等文件，预签名直链下载）
```

## 方案 A：前后端分离（CF Pages + 后端 PaaS）

1. **数据库**：Neon 建库 → 拿到连接串，改写成
   `postgresql+asyncpg://user:pass@host/db`。
2. **跑迁移**（必须，RLS 策略在迁移里）：
   `cd apps/backend && RUBBISH_DATABASE_URL=<连接串> uv run alembic upgrade head`
3. **后端**：Railway/Render 新建服务，用后端 Dockerfile
   （`docker build -f apps/backend/Dockerfile .`，构建上下文为仓库根），环境变量：

   | 变量 | 值 |
   |---|---|
   | `RUBBISH_DATABASE_URL` | PG 连接串 |
   | `RUBBISH_ENVIRONMENT` | `production` |
   | `RUBBISH_SECRET_KEY` | `python -c "import secrets;print(secrets.token_hex(32))"` |
   | `RUBBISH_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
   | `RUBBISH_ADMIN_PASSWORD` | ≥12 位强密码 |
   | `RUBBISH_ALLOWED_HOSTS` | 后端域名，如 `api.example.com` |
   | `RUBBISH_CORS_ORIGINS` | 前端域名，如 `https://rubbish.pages.dev` |
   | R2（可选）：`RUBBISH_STORAGE_BACKEND=s3` + S3 endpoint/key/secret/bucket | 指向 R2 的 S3 兼容端点 |

4. **前端**：CF Pages 连 Git 仓库，Root directory = `apps/frontend`，
   构建命令 `npm run build`，输出 `dist`；构建环境变量
   `VITE_API_URL=https://<后端域名>/api`。
5. **域名**：Cloudflare DNS 给后端加 CNAME → PaaS 分配的地址；开启代理（橙云）。

## 方案 B：单端口一体化（最省事）

后端容器直接托管前端静态文件（`RUBBISH_STATIC_DIR` 已内置于
Dockerfile），一个服务搞定，前端走同源 `/api`，**无需 CORS**：

1. 按方案 A 步骤 1-3 部署后端容器（Dockerfile 已把 `dist/` 打进镜像并设好
   `RUBBISH_STATIC_DIR`）。
2. Cloudflare DNS 把主域名指向该服务即可；前端不用单独部署。
3. 本地预览同款行为：`cd apps/backend && PORT=8000 uv run python deploy_server.py`。

> 方案 B 静态托管由 FastAPI 提供，无 CF 边缘缓存；流量大时可再加 CF 前置 CDN。

## 方案 C：VPS 单机全家桶 ⭐ 平台数最少、功能最完整

一台 VPS 跑全部（PostgreSQL + 后端 + 前端 + HTTPS），`docker-compose.yml` 已备好：

1. VPS 装 Docker + Compose v2，克隆仓库
2. `cp .env.example .env` → 填好 `SITE_DOMAIN` / `POSTGRES_PASSWORD` / 三个密钥（生成命令在文件注释里）
3. DNS A 记录：你的域名 → VPS IP
4. `docker compose up -d --build`
5. 验证：`curl https://$SITE_DOMAIN/api/health`

内置能力：Caddy 自动 HTTPS（Let's Encrypt，无需手工证书）、`alembic upgrade head` 随启动自动执行（RLS 就位）、`pgdata`/`uploads` 持久卷（数据与上传的 PDF 重启不丢）。功能 100% 完整：RLS、pg_trgm 搜索、文件持久、无冷启动、无平台配额。

成本参考：Hetzner CX22 / 腾讯云轻量 2C2G ≈ $4–5/月。可选：前面再套一层 Cloudflare 免费 CDN（只需把 NS 指到 CF）。

## 方案 D：Render + Neon（一键 Blueprint）

仓库根的 `render.yaml` 是 Render Blueprint（规范：<https://docs.render.com/blueprint-spec>），
定义一个 Docker runtime Web Service（单端口镜像 + 持久盘 + preDeploy 自动迁移），
数据库用 Neon 免费档。适合「不想管 VPS、要 Git push 即部署」的场景。

### 1. Neon 建库

1. [neon.tech](https://neon.tech) 注册 → New Project（region 选离 Render `oregon` 近的 AWS us-east-2）。
2. Dashboard 的 Connection Details 里能拿到**两种连接串**（这是 Neon 的关键细节）：
   - **direct**（直连）：`postgresql://user:pass@ep-xxx-123456.us-east-2.aws.neon.tech/neondb`
   - **pooled**（PgBouncer 连接池，host 多一段 `-pooler`）：`postgresql://user:pass@ep-xxx-123456-pooler.us-east-2.aws.neon.tech/neondb`
3. 把两者改写成 SQLAlchemy asyncpg 格式：
   - direct（**只用于迁移**）：
     `postgresql+asyncpg://user:pass@ep-xxx-123456.us-east-2.aws.neon.tech/neondb`
   - pooled（**只用于运行时**）：
     `postgresql+asyncpg://user:pass@ep-xxx-123456-pooler.us-east-2.aws.neon.tech/neondb?prepared_statement_cache_size=0`

> ⚠️ 为什么 pooled 串必须加 `?prepared_statement_cache_size=0`：asyncpg 默认使用
> 服务端预编译语句（prepared statements），而 Neon pooled 走 PgBouncer **事务池模式**，
> 同一事务结束后连接可能被换走，导致 `prepared statement "xxx" does not exist` 报错。
> 该参数是 SQLAlchemy asyncpg 方言的官方解法——禁用语句缓存（规范出处：
> <https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#disabling-the-postgresql-prepared-statement-cache>；
> Neon 官方连接池说明：<https://neon.com/docs/connect/connection-pooling>）。
> 由此形成分工铁律：**迁移（alembic）必须走 direct，运行时走 pooled**。

### 2. 首次迁移

RLS 策略只存在于 Alembic 迁移里（最新版本 022），`create_all` 不会生成。可在本地预热一次
（也可跳过——Blueprint 的 preDeployCommand 每次部署都会自动执行）：

```bash
cd apps/backend
RUBBISH_DATABASE_URL=<direct 连接串> uv run alembic upgrade head
```

迁移 020 会执行 `CREATE EXTENSION IF NOT EXISTS pg_trgm`（性能索引）；Neon 支持 pg_trgm
扩展，库 owner 即可创建，无需额外操作（Neon 扩展列表：<https://neon.com/docs/extensions>）。

### 3. Render 创建服务

**方式一：Blueprint 一键（推荐）。** Render Dashboard → New → Blueprint → 选本仓库 →
Render 自动读取 `render.yaml`，只要求填入其中 `sync: false` 标记的 6 个变量
（两个 Neon 连接串、FERNET_KEY、ADMIN_PASSWORD、ALLOWED_HOSTS、CORS_ORIGINS，
取值见下表）→ Apply。之后每次 push（CI 通过后）自动构建部署。

**方式二：手动。** New → Web Service → 连仓库 → Runtime 选 Docker，
Dockerfile 路径 `apps/backend/Dockerfile`、构建上下文 `.`（仓库根），按 render.yaml
逐项补齐（Pre-Deploy Command 用 direct 串跑迁移、Docker Command 只启动服务）。

### 4. 环境变量（Render 后端服务）

| 变量 | 必填 | 取值 |
|---|---|---|
| `RUBBISH_DATABASE_URL` | ✅ | Neon **pooled** 串改写 + `?prepared_statement_cache_size=0`（见步骤 1） |
| `RUBBISH_DATABASE_URL_DIRECT` | ✅ | Neon **direct** 串改写，仅 preDeployCommand 迁移时使用 |
| `RUBBISH_ENVIRONMENT` | ✅ | `production`（render.yaml 已内置） |
| `RUBBISH_SECRET_KEY` | ✅ | render.yaml `generateValue` 自动生成（base64 256-bit） |
| `RUBBISH_FERNET_KEY` | ✅ | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`（必须是合法 Fernet key，generateValue 不保证 url-safe） |
| `RUBBISH_ADMIN_PASSWORD` | ✅ | ≥12 位强密码（首次登录后立即改掉 + 开 TOTP） |
| `RUBBISH_ALLOWED_HOSTS` | ✅ | `<service>.onrender.com`（多个用逗号，含自定义域名）；production 禁止留空/`*` |
| `RUBBISH_CORS_ORIGINS` | 建议 | 单端口同源部署填 `https://<service>.onrender.com`；production 禁止 `*` |
| `RUBBISH_TRUSTED_PROXIES_COUNT` | 建议 | `1`（Render 反代一层，限流按 X-Forwarded-For 还原真实 IP；render.yaml 已内置） |
| `RUBBISH_JSON_LOGS` | 建议 | `true`（结构化日志；render.yaml 已内置） |
| `RUBBISH_STORAGE_BACKEND` | 可选 | 默认 `local` + 挂载持久盘 `/data/uploads`；生产建议切 `s3`（R2），另加 `RUBBISH_S3_*` 5 项 |
| `RUBBISH_MEILISEARCH_URL` / `_API_KEY` | 可选 | 留空 = 不启用，搜索回退内置 DB ILIKE（**无需为方案 D 再开 Meilisearch**） |

> 端口无需配置：镜像里 `PORT=8080` 只是缺省值，Render 运行时注入的 `PORT` 会覆盖它，
> `deploy_server.py` 按注入值监听。
>
> **搜索后端说明**：`meilisearch_url` 留空时应用 fail-open 回退 DB ILIKE 搜索，方案 D 默认
> 不再额外开 Meilisearch 服务（省钱且零维护）。确需全文检索时最省钱的挂法是在同一
> Blueprint 加一个最小规格 pserv 拉起 `getmeili/meilisearch` 镜像 + 持久盘（约 $1–2/月级别），
> 或直接用 Meilisearch Cloud 免费档，然后把 URL/KEY 填入上表。

### 5. 验证

```bash
curl https://<service>.onrender.com/api/health        # 期望 {"status":"ok"}
```

- 一键冒烟门禁（推荐）：`./scripts/smoke.sh https://<service>.onrender.com`——
  exit 0 才算过；SKIP 项（验证码/关注册/2FA 策略所致）须人工核对后放行；
  生产 login 限流 10/min，重跑间隔 ≥1 分钟。管理员凭据用
  `SMOKE_ADMIN_USER` / `SMOKE_ADMIN_PASSWORD` 环境变量注入。
- Render 部署日志应出现 `alembic upgrade head` 执行记录（pre-deploy 步骤）。
- 浏览器打开 `https://<service>.onrender.com` 应看到前端 SPA，登录 admin 账户成功。

### 6. 回滚要点

- **应用回滚**：Render Dashboard → 服务 → Deploys → 选上一个成功部署 → Rollback，
  镜像级秒级切换，无需重建（Render 原生保留部署历史）。
- **数据库回滚**：Alembic 迁移**不会**随应用回滚自动降级。回滚前确认旧版本代码与当前
  schema 兼容（本项目迁移只增不删、向后兼容设计）；若必须降级，先在 Neon 备份/分支上
  演练 `alembic downgrade`，切勿直接对生产库执行未经演练的降级。
- **误升级保险**：Neon 免费档自带 point-in-time restore 分支，重大迁移前建一个分支快照。

### 免费套餐变体（`plan: free`）

Render free 实例**不支持** preDeployCommand 与 persistent disk
（<https://render.com/docs/deploys#pre-deploy-command>、<https://render.com/docs/disks>）。
如用 free 套餐：① 删除 render.yaml 里的 `preDeployCommand` 与 `disk` 字段、删除
`dockerCommand`（让镜像自带 CMD 在启动时对 `RUBBISH_DATABASE_URL` 执行迁移）；②
`RUBBISH_DATABASE_URL` 直接填 **direct** 连接串（单实例小流量，无需 pooled）；③
文件存储必须切 `RUBBISH_STORAGE_BACKEND=s3`（R2），free 实例本地盘重启即丢。

## 上线前 checklist

- [ ] `alembic upgrade head` 已在目标库执行（RLS 就位，`test_rls_coverage` 保证所有租户表都有策略）
- [ ] `RUBBISH_ENVIRONMENT=production`（触发强密钥/ALLOWED_HOSTS 校验）
- [ ] SECRET_KEY / FERNET_KEY / ADMIN_PASSWORD 均为强随机值且**持久化**（重启不变）
- [ ] `RUBBISH_ALLOWED_HOSTS` / `RUBBISH_CORS_ORIGINS` 收紧到真实域名
- [ ] 首次登录后立即改 admin 密码 + 开启 TOTP（`/api/auth/2fa`）
- [ ] 健康检查：`GET /api/health` → `{"status":"ok"}`
- [ ] 文件存储用 R2/S3（容器本地盘会随重启丢文件）

## 期次与定时发布（1.0.1 起）

期刊按「期」发布，不靠人工删改可见性：

- 每条 `resources` 有 `publish_at`。`publication_status='published'` 且
  `publish_at <= now()` 才算公开发布；`publish_at` 在未来 = 已排期、对公众不可见
  （判定集中在 `app/modules/catalog/visibility.py`，目录/详情/文件/Markdown/
  统计/分面/评论/搜索/导出/SEO/OAI 全部同一口径，管理员不受限）。
- 公开日历 `GET /api/catalog/issue-plan`；L9 可用
  `POST /api/catalog/issues/{volume}/{issue}/publish` 一键发整期或改期（写审计）。
- 后台 `/archive` 的「发刊计划」表提供行内「立即发布」。
- 创刊排期：第 1 期 2026-10-01，其后每月 1 日一期至 2027-07-01。

导入/重导流水线（含备份、manifest、Markdown 重建、排期脚本）见
`_deploy/journal_import/README.md`。
