# 发布门禁与 Release Manifest

> 2026-11-12 落地。目标不是“再写一个发布脚本”，而是把“这一期能不能上线”
> 变成一个可检查、可复现、不可悄悄绕过的状态机。

## 1. 为什么不是脚本

旧链路 `POST /api/catalog/issues/{volume}/{issue}/publish` 只做一件事：
把该期 `published` 资源的 `publish_at` 改成指定时间。它默认调用者已经检查过：

- 有没有草稿混进来；
- 标题、摘要、作者、学科、类别是否齐全；
- PDF 是否真的在 `/data/uploads`；
- 有没有重复标题 / slug；
- 检查之后内容有没有又被改过。

这些默认项就是事故面。发布门禁把它们变成显式检查，并把检查结果固化成
Manifest。发布动作只接受“仍然新鲜”的 Manifest。

## 2. 状态机

```
check:
  blocked ──(修完错误，重新 check)──> ready
  ready   ──(内容变化)──────────────> superseded
  ready   ──(编辑批准)──────────────> ready(approved)
  ready(approved) ──(立即发布)──────> published
  ready(approved) ──(未来时间)──────> scheduled
  scheduled ──(到点且哈希仍一致)────> published
  scheduled ──(到点但内容变了)──────> superseded
  published / superseded 为终态，不再被新 check 覆盖
```

`ready` 只是“门禁通过”，不等于“可以发”。还要有一次编辑批准：
`approved_by + approved_at + approval_signature`。签名绑定
`manifest_id + volume + issue + content_hash + approver + time`，
用服务端 `secret_key` 做 HMAC-SHA256。内容一变，新 check 生成新
Manifest，旧批准随旧 Manifest 一起失效。

状态只挂在 Manifest 上，不直接改文章状态；文章仍用 `publication_status`
与 `publish_at` 表达公开可见性。这样不会把“发布批次”和“单篇生命周期”
混成一张表。

## 3. 五类门禁

| 类别 | 检查 | 级别 |
|---|---|---|
| 期内容 | 期里至少有一篇；所有资源都是 `published` | error |
| 元数据 | 标题、摘要、作者、内容类别 | error |
| 元数据 | 摘要过短、缺学科 | warning |
| 文件 | PDF 存在且 ≥ 1KB；PDF 已清理但有 Markdown 时回退 Markdown；两者都没有且无外链才阻断 | error / warning / info |
| 唯一性 | 同期标题、slug 不重复 | error |
| 展示 | 缺封面（走默认封面） | info |

检查结果是一个扁平列表，每项包含 `code`、`level`、`message`、
`resource_id`。前端直接按级别渲染，不需要再解析自然语言。

## 4. Manifest 里有什么

`release_manifests.payload` 保存完整快照：

- `gate_version`
- `checks[]`
- `resources[]`：id、slug、标题、作者、状态、`publish_at`、
  PDF/Markdown 的路径、大小、SHA-256
- `content_hash`：对上述资源快照做规范化 JSON 的 SHA-256

`content_hash` 是发布时的“防篡改票据”。发布接口会重新跑一次门禁，
如果 hash 变了，直接 409 `manifest_stale`，并把旧 Manifest 标成
`superseded`。编辑不能靠“我刚才检查过”绕过。

## 5. API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/admin/releases/issues` | 所有期（含草稿），给后台选期 |
| POST | `/api/admin/releases/check` | 生成 ready / blocked Manifest |
| GET | `/api/admin/releases/manifests?volume=&issue=` | Manifest 历史 |
| GET | `/api/admin/releases/latest?volume=&issue=` | 最近一份 |
| POST | `/api/admin/releases/approve` | 编辑批准一份 ready Manifest |
| POST | `/api/admin/releases/publish` | 用已批准的 ready Manifest 发布/排期 |
| POST | `/api/admin/releases/rollback` | 回滚到某份已发布 Manifest 的发布时间线 |

`publish` body：

```json
{
  "volume": "12",
  "issue": "9",
  "manifest_id": 42,
  "publish_at": null
}
```

`publish_at` 为空 = 立即发布；未来时间 = `scheduled`。只更新该期
`publication_status='published'` 的资源，不碰草稿。发布前会校验
`approval_signature`；没批准或签名失效直接 409 `not_approved`。

`approve` body：

```json
{"manifest_id": 42, "note": "已核对目录、版权页与编后记"}
```

`rollback` body：

```json
{
  "volume": "1",
  "issue": "06",
  "manifest_id": 42,
  "reason": "恢复上一版发布时间线"
}
```

回滚不会改文章正文，只把该期 `published` 资源的 `publish_at` 恢复成
目标 Manifest 快照里的值。它绕过当前门禁，因为目标本来就是一份已经
发布过的 Manifest；新 Manifest 记录 `rollback_of`、原因、恢复数与缺失数，
并写 `release.rollback` 审计。

## 6. 后台入口

- 侧栏 / 移动端“站点管理” → **发布门禁**
- 直接路径：`/admin/releases`
- 页面流程：选卷 → 选期 → 运行门禁 → 看 error/warning/info →
  立即发布或排期 → 查看 Manifest 历史

## 7. 表与迁移

- 表：`release_manifests`
- 迁移：`030_release_manifests.py`（建表/RLS）、`031_release_approval.py`
  （批准签名、`scheduled_for`、`rollback_of`）
- 多租户：`tenant_id` + PostgreSQL RLS `tenant_isolation`
- 审计：`release.check`、`release.approve`、`release.publish`、
  `release.rollback`、`release.scheduled_publish`、
  `release.scheduled_failed`

## 8. 服务端定时发布

`app/modules/release/scheduler.py` 是一个独立的小循环：启动 10 秒后开始，
每 30 秒扫一次 `scheduled` 且 `scheduled_for <= now` 的 Manifest。
主调度器仍保留 6 小时节奏跑审稿催办，两者互不影响。

到点时它会重新跑门禁：

- 哈希一致且仍 `ready`：标 `published`，写 `release.scheduled_publish`；
- 内容变了：标 `superseded`，写 `release.scheduled_failed`，不发布；
- 门禁被阻塞：同样标 `superseded`，写 `release.scheduled_failed`。

所以“排期”不是把任务交给一个不会失败的黑盒；到点前改稿，系统会拒绝
发布并留下原因，编辑重新 check、重新批准即可。

## 9. 还没做的（下一阶段）

1. **单篇生命周期**：`draft → accepted → scheduled → published → corrected → retracted`
   还没有独立事件表；目前由 `publication_status + publish_at` 表达。
2. **发布后校验**：发布完成后自动抓 `/`、`/papers`、`/sitemap.xml`、
   `/rss.xml` 和最新详情页，把 HTTP 状态与 TTFB 写进 Manifest 的
   `post_deploy` 字段。
3. **定时发布失败通知**：现在写审计和日志，还没有给值班编辑发站内信/邮件。
4. **字体子集自动重建**：新文章引入新汉字时，发布门禁应触发字体子集
   重建，而不是回退系统字体。
