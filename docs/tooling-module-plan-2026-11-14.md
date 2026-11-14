# Rubbish 工具模块专项：编辑器 / 查看器 / 转换器 / 导入导出

> 2026-11-14。目标不是“再加功能”，而是先把现有工具链做成**可验证、可回退、结果一致**的模块，再按市面常见产品补齐。

## 0. 先定原则

1. **同一份内容只走一条渲染链**：编辑器预览、投稿预览、文章页、PDF/Word 导出看到的结构必须一致；不一致就是 bug。
2. **先修数据正确性，再修交互**：转换器输出错一个字段，比工具栏少一个按钮严重得多。
3. **每个工具都要有失败态**：超时、空文件、坏格式、扫描件、LibreOffice 缺失、图片 404，都不能只显示“加载中”。
4. **不引入第二套真相**：能复用 `MarkdownContent` / `export_docs` / `ingest.parsers` 的，不另写渲染器或解析器。
5. **先小步提交，CI 全绿再推远程**；不把大重构和功能新增混在一个不可回滚的提交里。

## 1. 模块清单（现状）

| 类别 | 模块 / 文件 | 现有能力 | 当前问题（审计结论） |
|---|---|---|---|
| 编辑器 | `components/common/markdown-editor.tsx`（396 行） | 标题/加粗/斜体/段落/插入、编辑/分栏/预览、字数、图片上传 | 已接投稿正文插图；Tab/Shift+Tab 多行缩进；仍缺少撤销/重做、查找、目录、版本对比 |
| 编辑器 | `components/common/markdown-field.tsx`（118 行） | 表单内编辑/预览、模板、字数 | 预览与正文渲染链一致，但没有自动保存、没有快捷键说明 |
| 编辑页 | `routes/submissions/new.tsx`（1624 行） | 上传 Word/PDF 识别、在线正文、发布预览、分步表单 | 页面仍过大；在线正文已可插图；编辑器/预览已走共享渲染 |
| 预览 | `components/common/article-preview.tsx`（102 行） | 标题/作者/摘要/关键词/正文预览 | 已改用共享 `MarkdownContent`；摘要也按 Markdown 渲染 |
| 渲染 | `components/common/markdown-content.tsx`（140 行） | GFM、公式、raw HTML、sanitize、data 图、中文紧邻加粗 | 已是编辑器/预览/文章页/评审报告共用的唯一渲染器；后续只需处理更复杂的 Markdown 扩展 |
| 查看器 | `components/common/manuscript-view.tsx`（1406 行） | 正文、目录、参考文献折叠、阅读偏好、进度、移动端 | 单文件仍过大；已接入 raw HTML 清洗；目录/折叠/清洗规则仍混在一起 |
| 查看器 | `components/pdf-image-preview.tsx`（122 行） | 分页 PNG 预览、总页数、下载兜底 | 换资源重置页码、失败重试已修；仍无预取 |
| 查看器 | `components/source-preview-png.tsx`（98 行） | 投稿原件分页预览 | 已并入 `AuthPngPreview`（2026-11-14 续）；旧组件删除，不再维护三套相似逻辑 |
| 查看器 | `components/auth-png-preview.tsx`（120 行） | 鉴权分页 PNG、缓存、重试、图片解码失败态 | 已用于投稿原件预览；分页缓存上限 20；与 `PdfImagePreview` 仍有结构相似，后续可合并 |
| 转换 | `domain/export/exporters.py`（388 行） | BibTeX/RIS/CSV/JSON/JATS | 页码拆分、作者/关键词转义、中文 citation key 兜底、JATS 文案已修；仍需字段级往返夹具 |
| 转换 | `domain/submission/export_docs.py`（465 行） | MD→HTML→PDF、MD→DOCX、整期 PDF、DOCX→PDF | PDF 字体/图片压缩有兜底；LibreOffice 缺失时回退路径需可观测；公式在 PDF 中可能丢失 |
| 转换 | `domain/submission/docx_template.py`（1199 行） | 品牌 Word 模板、题录、表格、图注、页眉 | 单文件巨大；表格跨页、图注孤页、图片尺寸规则散落；缺独立回归夹具 |
| 导入 | `domain/ingest/parsers.py` | BibTeX/RIS/CSV/JSON | 已支持 JSON 回导；CSV 别名仍未完全对齐；错误定位只到行号 |
| 导入 | `domain/ingest/fetchers.py` | Crossref/arXiv/PubMed/OpenAlex/Semantic Scholar | 后端 5 个源已在前端全部可选；字段映射仍未做 |
| 导入页 | `routes/ingest/index.tsx`（255 行） | 粘贴文本解析、文件选择/拖拽、五源查询 | 仍不能编辑解析结果、批量勾选；字段映射未做 |
| 导出页 | `interfaces/http/export/routes.py` | 批量引用导出 5 种格式 | 注释仍写“四选一”；无导出前预览/字段校验 |

## 2. 本轮 P0：先修“会丢内容 / 会出错 / 会误导”

### P0-1 统一渲染链
- `ArticlePreview` 改用 `MarkdownContent`，让投稿预览与文章页共享 GFM、公式、raw HTML、sanitize。
- `ManuscriptView` 接入同一套 `rehypeRaw + rehypeSanitize` schema，修复 `<u>/<mark>/<sup>/<sub>` 在发布页失效。
- 验收：编辑器写入 `<mark>高亮</mark>`、`<u>下划线</u>`、表格、公式，投稿预览与文章页都能看到；脚本/事件属性仍被清洗。

### P0-2 转换器字段正确性
- RIS 页码拆成 `SP` / `EP`；标题、作者、关键词换行压平，避免破坏 RIS 记录。
- BibTeX 作者、关键词转义；中文标题 citation key 不再全部退化成 `untitled`，用稳定 id 兜底。
- `export_resources` 错误文案包含 JATS；同步路由注释。
- 验收：往返导出再导入字段不丢；同一批中文文献 citation key 不重复。

### P0-3 预览器状态
- `PdfImagePreview` / `SourcePreviewPng` 在资源/token 变化时重置页码并按总页数夹取；图片失败可重试。
- 验收：从 20 页文档切到 3 页文档不出现 404 空白；重试能重新拉图。

### P0-4 导入入口
- 导入页补齐 PubMed/OpenAlex/Semantic Scholar 三个已存在后端源；按来源给不同 placeholder。
- 增加 `.bib/.ris/.csv` 文件选择，读取后自动填入并识别格式。
- 验收：五种来源都可选；选文件后不用手工粘贴。

### P0-5 编辑器基础手感
- Tab/Shift+Tab 支持多行缩进/反缩进，不再只插两个空格。
- 工具栏按钮和 textarea 补 accessible name；`Ctrl+U` 下划线。
- 验收：选中三行按 Tab 三行都缩进；Shift+Tab 撤回；键盘操作不破坏选区。

### P0-6 原件预览缓存治理
- `/source-preview` 的临时 PDF 加 TTL + 数量上限清理，避免登录用户反复上传把 `/tmp` 塞满。
- 验收：超过 TTL 的预览 PDF 被清理；最近文件仍可访问。

## 2.1 本轮实际完成（2026-11-14）

- [x] P0-1 统一渲染链：`ArticlePreview` 改用共享 `MarkdownContent`；`ManuscriptView` 接入同一套 `rehypeRaw + rehypeSanitize`；新增投稿预览/文章页 raw HTML 回归测试。
- [x] P0-2 转换器：RIS 页码拆 `SP/EP`、换行压平；BibTeX 作者/关键词转义；中文标题 citation key 用资源 id 兜底；错误文案补 JATS；路由注释改“五选一”。
- [x] P0-3 预览器：`PdfImagePreview` / `AuthPngPreview` 换 token/资源时页码同帧归 1，按总页数夹取；两个预览补“重新加载本页”；PDF info 只在资源/版本变化时请求，不再每翻一页重复请求。投稿原件预览统一收口到 `AuthPngPreview`，旧的 `SourcePreviewPng` 已删除，三套相似逻辑不再并行维护。
- [x] P0-4 导入入口：补齐 PubMed/OpenAlex/Semantic Scholar；前端 `FetchSource` 类型同步；支持 `.bib/.bibtex/.ris/.csv` 文件选择与拖拽读取，自动识别格式。
- [x] P0-5 编辑器：Tab/Shift+Tab 多行缩进与反缩进；`Ctrl+U` 下划线；工具栏/textarea 补 accessible name。
- [x] P0-6 预览缓存：`/source-preview` 临时 PDF 加 6 小时 TTL + 200 份上限清理，避免 `/tmp` 被登录用户反复上传堆满。
- [x] 额外：新增通用 `/api/media/images`（submission/forum/note），投稿正文在线编辑器现在可以直接插图；论坛新图也走同一端点，旧 `/api/forum/images` 保留兼容。
- [x] 测试：后端新增导出器、JATS 路由、媒体上传、预览缓存测试；前端新增投稿预览、正文 raw HTML、分页预览、编辑器缩进测试。
- [x] 回归（第一轮记录）：后端全量 `1171 passed, 1 skipped`；前端 `26 files / 150 tests passed`；`lint`、`typecheck`、`build` 均通过；E2E 使用系统 Chromium 全量 `75 passed`（19.2m）。第二轮回归见 2.3。
- [x] 回归中顺手收口：导入页保留稳定 placeholder（避免 E2E 选择器失效）；主页保存 toast 固定 id（连续保存不再堆叠两条相同提示）；管理员角色菜单用例改用真实点击（Radix 菜单项由 roving tabindex 管理焦点）。

对应提交与 CI 结果：本地提交见下方“交付记录”；推送后由远程 CI 触发，结果在交付说明中回填。

### 2.2 横向补充（2026-11-14 续，计划外发现并已修）

- [x] 中文紧邻加粗：把 `ManuscriptView` 原有的 `remarkCjkStrong` 移到共享 `markdown-content.tsx` 并导出，编辑预览、投稿预览、文章页、评审报告共用同一规则；`**作者：**马必略` 不再露出字面 `**`。
- [x] 引用格式：文章页引用卡从固定 `[Z]` 改为按资源类型生成 `[J]/[M]/[DS]/[EB/OL]`，新增 GB/T 7714、APA、MLA 三种格式复制，默认仍展示 GB/T。
- [x] JSON 回导：`POST /api/ingest/parse` 支持 `format=json`，接受导出数组、单对象和 `data`/`items` 包装；忽略 `source_id`/`external_url` 等导出专用字段，前端格式下拉和文件 accept 同步支持 `.json`。
- [x] 投稿原件预览鉴权：`GET /source-preview/{token}.pdf` 与分页 PNG 补登录校验；投稿页改用 `AuthPngPreview` 走带 Authorization 的 blob 请求，避免拿到 32 位 token 即可读草稿原件。
- [x] 预览失败态：`AuthPngPreview` 的 `<img>` 补 `onLoad/onError`，后端已返回图片但浏览器解码失败时也能显示“重试”，不会停在空白页。
- [x] 投稿预览摘要一致性：`ArticlePreview` 的摘要从纯文本 `<p>` 改为共享 `MarkdownContent`，摘要里的公式、`<mark>`、`<u>` 与文章页表现一致。
- [x] 预览标题去重：`ArticlePreview` 从只匹配 `#` 一级标题扩展到 `#{1,6}`，`## 标题` 也不会在预览里重复出现。
- [x] 测试：新增 `citation.test.ts`、JSON 导入后端测试、`auth-png-preview.test.tsx`、投稿原件预览鉴权测试；补充 `MarkdownContent` 中文加粗、`ArticlePreview` 摘要/标题去重断言。

### 2.3 第二轮回归（2026-11-14 续）

- [x] 后端全量：`1176 passed, 1 skipped`（12m05s）。
- [x] 前端全量：`28 files / 157 tests passed`（9m23s）；`lint`、`typecheck`、`build` 通过。
- [x] E2E 全量：`75 passed`（27.1m），2FA 用例 48.1s；使用系统 Chromium。

## 3. 后续 P1：按市面常见能力补齐

### 3.1 编辑器
- 撤销/重做按钮与快捷键说明；查找/替换；文档大纲；专注模式。
- 表格行/列增删、对齐；图片拖拽/粘贴（投稿页接通用上传）；脚注、引用块、参考文献格式化。
- 自动保存草稿（本地 + 服务端）、版本快照对比、恢复。
- 移动端工具栏折叠为“格式 / 插入 / 视图”三组，不横向挤成四行。

### 3.2 查看器
- 合并 `PdfImagePreview` / `SourcePreviewPng` / `AuthPngPreview` 为通用 `PagedPdfPreview`，统一分页、缓存、重试、键盘翻页。
- PDF 预览支持页码跳转、缩放、适合宽度；移动端手势。
- Markdown 查看器拆分为 `render / toc / reference / reading-prefs` 四个模块，降低 1406 行单文件风险。
- 表格、CSV、代码、图片查看器按内容类型分流；没有对应查看器时给出明确兜底，不空白。

### 3.3 转换器
- MD↔DOCX/PDF/HTML/JATS 统一契约测试：标题、作者、摘要、关键词、图注、表题、公式、脚注、参考文献。
- 批量导出（多篇合并 PDF/Word、整期 ZIP、引用文件）。
- 导入支持 JSON、EndNote RIS 变体、CSV 别名、DOI 批量解析。
- 导出前字段校验：缺标题/作者/年份/DOI 给 warning；不静默生成空字段。
- 转换失败可观测：记录阶段（解析/排版/转 PDF/字体），前端显示具体下一步，不只“失败”。

### 3.4 内置小工具
- 引用格式生成（GB/T 7714、APA、MLA、BibTeX、RIS）与一键复制。
- 图/表编号检查、参考文献序号检查、重复段落检查、AI 风格清洗。
- 元数据抽取（DOI/arXiv/PubMed/OpenAlex）→ 预填投稿表单。
- 底刊编号/DOI/ISSN 的选填校验与引用块生成。
- 批量导入预览、字段映射、冲突合并。

## 4. 验收矩阵

| 模块 | 必测输入 | 必测失败态 | 通过标准 |
|---|---|---|---|
| Markdown 编辑器 | 标题、表格、公式、`<u>/<mark>`、图片、多行选区 | 上传失败、超 5MB、空内容 | 预览与文章页一致；快捷键不破坏选区 |
| 投稿预览 | 同上 + 摘要/关键词重复 | 空正文 | 不重复标题/摘要；无 XSS |
| 文章查看器 | 长文、参考文献、图注、公式 | 409 needs_docx、404 图 | 目录可跳转；折叠正确；raw HTML 安全 |
| PDF/原件预览 | 1 页、20 页、切换资源 | 页码越界、图片 404 | 自动回第 1 页/夹取；可重试 |
| 引用导出 | 中英文、重复作者、页码区间 | 空 ids、未知格式 | RIS/BibTeX 可被 Zotero 解析；key 不重复 |
| Word/PDF 导出 | 图表、公式、长表 | LibreOffice 缺失 | 有兜底；失败原因可读 |
| 导入 | BibTeX/RIS/CSV/文件上传/5 源 | 坏条目、上游 404 | 逐条错误；成功条目可用 |

## 5. 执行顺序

1. 本轮 P0-1 至 P0-6，全部带单测/回归，CI 绿后推送。
2. 下一轮 P1 编辑器与查看器合并，先做 `PagedPdfPreview` 和 `ManuscriptView` 拆分。
3. 再做转换契约测试与批量导出。
4. 最后补内置小工具，避免在渲染/转换还不稳时堆功能。

## 6. 不做什么

- 不引入 TipTap/ProseMirror 这类富文本内核替换现有 Markdown：当前内容是 Markdown 单一真相，换内核会带来双向转换和迁移风险。
- 不为“看起来功能多”把 20 个按钮重新平铺；工具栏继续分组。
- 不把代码备份进仓库；远程仓库是代码的唯一备份，数据备份仍只做 DB + uploads。

## 7. 交付记录

- 本地提交：`d37b6b9 fix(tooling): unify markdown render and close preview/import/export bugs`
- 验证：后端 `1171 passed, 1 skipped`；前端 `150 passed`；`lint` / `typecheck` / `build` 通过；E2E `75 passed`。
- 远程推送与 CI 结果：见最终交付说明（远程 CI 由推送触发，不在本地伪造结果）。

## 8. 2026-11-14 续批状态

- [x] 3.1 撤销/重做（Ctrl+Z / Ctrl+Shift+Z，100 步上限）、查找/替换、文档大纲、专注模式；已补 3 个前端测试。
- [x] 3.2 抽出通用 `PagedPdfPreview`，`PdfImagePreview` 与 `AuthPngPreview` 改为薄包装；统一换稿归位、页码夹取、重试、页码跳转、缩放、键盘翻页；已补页码跳转/缩放/键盘测试。
- [ ] 3.2 `ManuscriptView` 拆分为 render/toc/reference/reading-prefs 四模块；当前仍是单文件。
- [ ] 3.2 表格/CSV/代码/图片按内容类型分流查看器。
- [ ] 3.3 批量导出、统一转换契约测试、导出前字段校验。
- [ ] 3.4 独立引用生成器、图表/参考文献编号检查、批量导入字段映射。
- [x] 分页缓存键修正：`useMySubmissions` / `usePendingSubmissions` / `useMyReviewAssignments` 等把 `pageSize` 纳入 query key，避免 Dashboard 用 1 条把列表页 20 条的缓存覆盖。
- [x] 期号页 JSON-LD `PublicationIssue`，与 canonical 路由、整期 PDF 一并落地。
- [x] P2-11 第一版 `/desk`：主编桌，三根内容支柱 + 真实卷首手记，不伪造个人头衔或数据；尚未接入独立域名/邮件订阅。
