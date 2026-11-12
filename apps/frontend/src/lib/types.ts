// Backend API 类型镜像。从 pydantic schemas 1:1 映射；ISO 时间用 string。
// 所有 union 类型保持 Literal 等价，便于 form 校验和 Zod 推断。

// --- Core: PaginationMeta + MessageResponse ---
export interface PaginationMeta {
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface MessageResponse {
  message: string
}

// --- Auth + User ---
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  user_id: number
  username: string
  is_admin: boolean
  // 服务端下发的角色名；旧后端不返回时按空数组处理
  roles?: string[]
  // M2 2FA: when the account requires 2FA, access/refresh are empty
  // strings and the client must redeem ``two_factor_token`` via
  // ``POST /auth/2fa/authenticate`` before storing any tokens.
  requires_2fa?: boolean
  two_factor_token?: string | null
}

// --- 2FA ---
export interface UserResponse {
  id: number
  email: string
  username: string
  is_active: boolean
  is_admin: boolean
  is_email_verified: boolean
  created_at: string
  // 一句话简介（迁移 012；PATCH /users/me 可改）
  bio?: string | null
  // 可扩展资料（迁移 026）
  display_name?: string | null
  real_name?: string | null
  affiliation?: string | null
  department?: string | null
  academic_title?: string | null
  research_interests?: string | null
  website?: string | null
  google_scholar?: string | null
  location?: string | null
  // admin 端点会填入；普通 /auth/* 端点保持空数组
  roles: string[]
  /** 等级体系：XP 与生效等级（1–9） */
  xp?: number
  level?: number
  rules_accepted?: boolean
}

// 可编辑的个人资料字段（PATCH /users/me）。空串表示清除，缺键表示保持不变。
export type UserProfileUpdate = Partial<
  Pick<
    UserResponse,
    | 'bio'
    | 'display_name'
    | 'real_name'
    | 'affiliation'
    | 'department'
    | 'academic_title'
    | 'research_interests'
    | 'website'
    | 'google_scholar'
    | 'location'
  >
>

// 可分配的角色名（与 backend ASSIGNABLE_ROLES 一致；admin 不在此处，由 is_admin 控制）
export type AssignableRole =
  | 'reviewer'
  | 'senior_reviewer'
  | 'editor'
  | 'section_editor'
  | 'board_editor'
  | 'deputy_editor'
  | 'chief_editor'
  | 'author'
  | 'reader'

export interface UserCreate {
  email: string
  username: string
  password: string
  captcha_token?: string
  captcha_answer?: string
}

export interface UserLogin {
  username: string
  password: string
}

// --- Two-factor auth (TOTP) ---
// /auth/login 在账号开启 2FA 时返回它而不是 TokenResponse
export interface TwoFactorRequiredResponse {
  two_factor_required: true
  pending_token: string
}

export type LoginResponse = TokenResponse | TwoFactorRequiredResponse

export function isTwoFactorRequired(
  r: LoginResponse,
): r is TwoFactorRequiredResponse {
  return 'two_factor_required' in r && r.two_factor_required === true
}

export interface TwoFactorLoginRequest {
  pending_token: string
  code: string
}

export interface TwoFactorSetupResponse {
  secret: string
  otpauth_uri: string
  // 10 个一次性恢复码，只在 setup 响应里出现这一次
  backup_codes: string[]
}

export interface TwoFactorStatusResponse {
  enabled: boolean
  backup_codes_remaining: number
}

export interface VerifyEmailRequest {
  token: string
}

export interface ResendVerificationRequest {
  email: string
}

export interface ForgotPasswordRequest {
  email: string
}

export interface ResetPasswordRequest {
  token: string
  new_password: string
}

// --- Module info + Health ---
export interface ModuleInfo {
  name: string
  version: string
  description: string
}

export interface HealthResponse {
  status: 'ok'
  version: string
}

// --- Public capabilities ---
export interface CapabilitiesResponse {
  email_backend: string
  email_delivery: boolean
  email_verification_required: boolean
  oidc_enabled: boolean
  registration_open: boolean
  /** 服务端允许的单文件上限（字节）；前端据此做预校验与文案 */
  upload_max_bytes: number
  /** 服务端接受的扩展名清单（含点号），用于 <input accept> 与文案 */
  upload_extensions: string[]
}

// --- Catalog ---
export type ResourceType = 'paper' | 'book' | 'dataset' | 'tutorial'
export type PublicationStatus = 'published' | 'in_review' | 'draft'

/** 论文子类型：serious=学术论文 / absurd=荒诞论文。
 *  只对 content_track=paper 有意义；副刊不展示。 */
export type Track = 'serious' | 'absurd'

export interface ResourceBase {
  type: ResourceType
  /** 赛道：历史字段，已下线（见 core/tracks.py）。前端不再读写，
   *  后端会把任意值归一为 serious；仅为类型兼容保留为可选。 */
  track?: Track
  title: string
  authors: string[]
  year: number
  venue?: string | null
  discipline: string
  subdiscipline?: string | null
  tags: string[]
  abstract: string
  preview: string
  download_url?: string | null
  external_url?: string | null
  doi?: string | null
  volume?: string | null
  issue?: string | null
  pages?: string | null
  issn?: string | null
  isbn?: string | null
  publisher?: string | null
  short_container_title?: string | null
  keywords?: string[] | null
  language: string
  publication_status: PublicationStatus
  publish_at?: string | null
  article_section?: string | null
  issue_part?: string | null
  /** 质量评分（评审质量分，0–100）与 14 档等级 A+~F */
  quality_score?: number | null
  quality_grade?: string | null
  content_category?: "academic" | "fun" | "rant" | null
  /** 内容赛道：essay 表示娱乐/随笔稿（与 content_category=fun/rant 同义，
   *  后端物化时可能只下发其一）；前端据此隐藏全部学术评分元素。 */
  content_track?: string | null
  /** 娱乐轨文体细分：joke/fiction/review/guide/essay/poetry/rant。
   *  只对 content_track=essay 有值；论文轨为 null。 */
  content_genre?: 'joke' | 'fiction' | 'review' | 'guide' | 'essay' | 'poetry' | 'rant' | null
  /** 特别篇：篇幅超过轨道上限、经显式特许的稿件。 */
  is_special_issue?: boolean
  special_issue_reason?: string | null
  // 编辑部评语挂在 quality_breakdown.comment（额外键，读取处自行收窄类型）
  quality_breakdown?: Record<string, { label: string; score: number; max: number }> | null
  /** 主题封面图（/covers/xx.jpg）；为空时回退生成式封面 */
  cover_image?: string | null
  cover_theme?: string | null
}

export interface ResourceCreate extends ResourceBase {
  slug?: string | null
}

export type ResourceUpdate = Partial<ResourceCreate>

export interface ResourceResponse extends ResourceBase {
  id: number
  /** 本站刊号：R-六位刊号-YYYYMMDD-流水；不是 DOI */
  site_id?: string | null
  slug?: string | null
  created_at: string
  updated_at: string
  /** 是否有可下载的稿件文件（列表与详情都会返回） */
  has_file?: boolean
  /** 是否有在线阅读用 Markdown 稿件 */
  has_markdown?: boolean
  /** R 指数互动指标（列表与详情都会返回） */
  reads?: number | null
  downloads?: number | null
  saves?: number | null
  r_index?: number | null
  quartile?: string | null
  /** 中图分类号（P0）：clc_code 如 TP3，clc_label 如「计算技术、计算机技术」 */
  clc_code?: string | null
  clc_label?: string | null
  /** R 因子：单篇 R 指数（详情接口返回） */
  r_factor?: number | null
  /** 结构化作者列表（v5）：未认领者 email/affiliation/user_id 为 null，
   *  前端绝不能从 PDF/Word 抓私人邮箱展示。 */
  authors_detail?: AuthorDetail[] | null
}

// --- Authors (v5) ---
export type AuthorRole = 'first' | 'corresponding'

export interface AuthorDetail {
  name: string
  order: number
  roles: AuthorRole[]
  claimed: boolean
  user_id: number | null
  affiliation: string | null
  email: string | null
}

export interface AuthorEditInput {
  name: string
  affiliation: string
  email?: string | null
  roles: AuthorRole[]
  order: number
}

// --- Claim (v5) ---
export interface ClaimOwner {
  user_id: number
  username: string
  claimed: boolean
}

export interface ClaimMine {
  id: number
  status: 'pending' | 'approved' | 'rejected'
  author_position?: number | null
  evidence_type?: 'email' | 'orcid' | 'manuscript_id' | null
  evidence_value?: string | null
  note?: string | null
  created_at?: string
}

export interface ClaimStatusResponse {
  claimable: boolean
  state: 'open' | 'claimed' | string
  mine: ClaimMine | null
  owner: ClaimOwner | null
}

export type ClaimEvidenceType = 'email' | 'orcid' | 'manuscript_id'

export interface ClaimSubmitRequest {
  author_position: number
  evidence_type: ClaimEvidenceType
  evidence_value: string
}

export interface ClaimSubmitResponse {
  id: number
  status: 'pending'
}

export interface AdminClaimEntry {
  id: number
  resource_id: number
  title: string
  user_id: number
  username: string
  author_position: number
  evidence_type: ClaimEvidenceType
  evidence_value: string
  status: 'pending' | 'approved' | 'rejected'
  note?: string | null
  created_at: string
}

export interface AdminClaimListResponse {
  data: AdminClaimEntry[]
}

export interface AdminClaimDecideRequest {
  approve: boolean
  note?: string
  author_position?: number
}

export interface AssignOwnerRequest {
  user_id: number
  author_position?: number
}

export interface JournalMetrics {
  published_total: number
  serious_total?: number
  absurd_total?: number
  by_type: Record<string, number>
  by_discipline: Record<string, number>
  discipline_count: number
  downloads_total: number
  reads_total: number
  saves_total: number
  decided_submissions: number
  accepted_submissions: number
  acceptance_rate: number | null
  avg_review_days: number | null
  median_review_days: number | null
  open_access_rate: number | null
  /** R 因子：全刊 R 指数均值，本刊自设计的旗舰指标（口径不公开） */
  r_factor: number | null
  /** 无引文数据，自引率恒为 0 */
  self_citation_rate: number
}

export interface ResourceListResponse {
  data: ResourceResponse[]
  meta: PaginationMeta
}

export interface ResourceStats {
  total: number
  by_type: Record<string, number>
  by_discipline: Record<string, number>
  by_genre?: Record<string, number>
  by_paper_kind?: Record<string, number>
  downloads_total?: number
  reads_total?: number
}

export interface FacetBucket {
  value: string
  count: number
}

export interface ResourceFacets {
  years: FacetBucket[]
  tags: FacetBucket[]
}

export interface ResourceListParams {
  type?: ResourceType
  category?: 'academic' | 'fun' | 'rant' | 'essay'
  track?: 'paper' | 'essay'
  /** 论文子类型：serious=学术论文 / absurd=荒诞论文（只对 paper 生效） */
  paper_kind?: Track
  genre?: 'joke' | 'fiction' | 'review' | 'guide' | 'essay' | 'poetry' | 'rant'
  discipline?: string
  year?: number
  volume?: string
  issue?: string
  section?: string
  issue_part?: string
  clc?: string
  q?: string
  page?: number
  page_size?: number
  sort?: 'created_at' | 'year' | 'title' | 'issue'
  order?: 'asc' | 'desc'
}

// --- Submission ---
// 完整 workflow 9-态机：pending → under_review → (major_revision | minor_revision | accepted | rejected)
//   major_revision / minor_revision → resubmitted → under_review（作者重投后再分配）
// approved/rejected 是旧 review 端点的别名，保留向后兼容
export type SubmissionStatus =
  | 'pending'
  | 'under_review'
  | 'major_revision'
  | 'minor_revision'
  | 'resubmitted'
  | 'accepted'
  | 'rejected'
  | 'approved'
export type SubmissionType = 'paper' | 'book' | 'dataset' | 'tutorial'

export interface SubmissionCreate {
  title: string
  type: SubmissionType
  /** 赛道：历史字段，已下线。后端会把任意值归一为 serious，前端不再发送。 */
  track?: Track
  authors: string[]
  year: number
  venue?: string | null
  discipline: string
  subdiscipline?: string | null
  /** 栏目 / 期次分部（Nature 式 part slug，录用时直通目录资源） */
  article_section?: string | null
  issue_part?: string | null
  keywords?: string[]
  jel_codes?: string[]
  tags: string[]
  abstract: string
  preview: string
  download_url?: string | null
  external_url?: string | null
  doi?: string | null
  corresponding_author_email?: string | null
}

// 4-元决定（编辑终决）
export type EditorDecision =
  | 'accept'
  | 'minor_revision'
  | 'major_revision'
  | 'reject'
  | 'approved'
  | 'rejected'

export interface SubmissionDecision {
  decision: EditorDecision
  editor_note?: string | null
  resource_id?: number | null
  /** accept 且新建物化时生效：published（默认，录用即刊）或 draft（暂存草稿，刊前整理） */
  publication_status?: 'published' | 'draft'
  /** 审稿意见冲突时的裁决理由（冲突时必填） */
  arbitration_note?: string | null
}

/** 结构报告单项（上传文件端点返回） */
export interface FormatCheckItem {
  key: string
  label: string
  ok: boolean
  hint: string
}

export interface FormatReport {
  ok: boolean
  word_count: number
  items: FormatCheckItem[]
}

export interface SubmissionResponse {
  id: number
  title: string
  type: string
  /** 赛道：历史字段（已下线），恒为 serious，仅为兼容保留。 */
  track: Track
  authors: string[]
  year: number
  venue?: string | null
  discipline: string
  subdiscipline?: string | null
  article_section?: string | null
  issue_part?: string | null
  keywords: string[]
  jel_codes: string[]
  tags: string[]
  abstract: string
  preview: string
  download_url?: string | null
  external_url?: string | null
  doi?: string | null
  corresponding_author_email?: string | null
  status: SubmissionStatus
  admin_note?: string | null
  editor_note?: string | null
  /** 关联目录条目的刊出状态（published/draft/in_review）；无关联时为 null。前端据此区分「已发表」与「刊前预览」 */
  resource_publication_status?: string | null
  resource_id?: number | null
  file_path?: string | null
  /**
   * 双盲评审下编辑提供给审稿人的匿名稿外链。
   * 与作者可控的 download_url / external_url 完全隔离：只能经编辑端点
   * PUT /submissions/{id}/anonymized-file 写入，传 null 表示清除。
   */
  anonymized_file_url?: string | null
  /** 双盲评审下，审稿人视图中该字段会被置空 */
  submitted_by: number | null
  submitted_at: string
  reviewed_by?: number | null
  reviewed_at?: string | null
  /** 结构报告：仅上传文件端点返回 */
  format_report?: FormatReport | null
  /** 质量评分（物化后的资源上读取；投稿阶段可能为空） */
  quality_score?: number | null
  quality_grade?: string | null
  content_category?: "academic" | "fun" | "rant" | null
  /** 编辑能否做最终决定（后端基于 reports_completed/conflict 计算） */
  can_decide?: boolean
  /** 已完成的审稿报告数 */
  reports_completed?: number
  /** 给出录用推荐的审稿人数（发表闸门要求 ≥2） */
  accept_recommendations?: number
  /** 给出拒稿推荐的审稿人数 */
  reject_recommendations?: number
  /** 参与过审稿的不同审稿人数 */
  distinct_reviewers?: number
  /** 审稿意见是否冲突（需第三方裁决/裁决理由） */
  conflict?: boolean
  /** 是否已指定第三方裁决人 */
  adjudicator_assigned?: boolean
  /** 第三方裁决人是否已给出录用意见 */
  adjudicator_accepted?: boolean
}

export interface SubmissionListResponse {
  data: SubmissionResponse[]
  meta: PaginationMeta
}

/** 作者修改稿件：所有字段可选，只提交改动的部分 */
export type SubmissionUpdate = Partial<SubmissionCreate>

/** 稿件版本快照。payload 与 SubmissionCreate 同形（书目字段） */
export interface SubmissionVersionResponse {
  id: number
  submission_id: number
  version: number
  payload: Record<string, unknown>
  file_path?: string | null
  /** 作者重投时填写的修改说明；v1 恒为 null */
  note?: string | null
  created_by?: number | null
  created_at: string
}

export interface SubmissionVersionListResponse {
  data: SubmissionVersionResponse[]
}

// --- Peer review ---
export type AssignmentStatus =
  | 'pending'
  | 'accepted'
  | 'declined'
  | 'completed'
  | 'cancelled'
export type Recommendation =
  | 'accept'
  | 'minor_revision'
  | 'major_revision'
  | 'reject'

export interface AssignmentCreate {
  reviewer_id: number
  due_date?: string | null
}

export interface AssignmentResponse {
  id: number
  submission_id: number
  reviewer_id: number
  assigned_by?: number | null
  status: AssignmentStatus
  due_date?: string | null
  invited_at: string
  responded_at?: string | null
  completed_at?: string | null
  reviewer_username?: string | null
  submission_title?: string | null
  last_reminded_at?: string | null
  reminder_count?: number
  report_id?: number | null
  attachments?: ReviewAttachment[]
  round?: number
  slot?: number
  /** 第三方裁决人：意见冲突时由主编/编辑指定 */
  is_adjudicator?: boolean
  /** 外审专家（主编指定，可标注外省/外单位） */
  is_external?: boolean
  external_affiliation?: string | null
}

export interface ReviewMatrixRow {
  reviewer_id: number
  username?: string | null
  slot: number
  status: string
  recommendation?: Recommendation | null
  due_date?: string | null
  is_overdue: boolean
  is_adjudicator: boolean
  is_external?: boolean
  external_affiliation?: string | null
}

export interface ReviewMatrixResponse {
  submission_id: number
  assignments: ReviewMatrixRow[]
  reports_completed: number
  distinct_reviewers: number
  accept_count: number
  reject_count: number
  major_revision_count: number
  can_decide: boolean
  conflict: boolean
  need_adjudication: boolean
  adjudicator_assigned: boolean
  adjudicator_accepted: boolean
}

export interface AssignmentListResponse {
  data: AssignmentResponse[]
  meta: PaginationMeta
}

export interface ReviewSubmit {
  recommendation: Recommendation
  scores: Record<string, unknown>
  comments_to_editor?: string | null
  comments_to_author?: string | null
  special_issue?: boolean
  special_issue_reason?: string | null
}

export interface ReviewAttachment {
  filename: string
  path: string
  content_type: string
  size: number
}

export interface ReviewReportResponse {
  id: number
  assignment_id: number
  recommendation: Recommendation
  scores: Record<string, unknown>
  comments_to_editor?: string | null
  comments_to_author?: string | null
  attachments?: ReviewAttachment[]
  submitted_at: string
}

// --- Library ---
export interface ReadingListCreate {
  name: string
  description?: string | null
}

export type ReadingListUpdate = Partial<ReadingListCreate>

export interface ReadingListItemCreate {
  resource_id: number
}

export interface ResourceRef {
  id: number
  title: string
  type: string
  authors: string[]
  year: number
}

export interface ReadingListItemResponse {
  id: number
  resource_id: number
  added_at: string
  resource: ResourceRef
}

export interface ReadingListResponse {
  id: number
  name: string
  description?: string | null
  item_count: number
  created_at: string
  updated_at: string
}

export interface ReadingListDetailResponse {
  id: number
  name: string
  description?: string | null
  items: ReadingListItemResponse[]
  created_at: string
  updated_at: string
}

export interface ReadingListListResponse {
  data: ReadingListResponse[]
  meta: PaginationMeta
}

// --- Reader ---
export type StorageBackend = 'local' | 's3' | 'minio'

export interface FileAssetCreate {
  filename: string
  original_filename: string
  mime_type: string
  file_size: number
  storage_path: string
  storage_backend: StorageBackend
  sha256?: string | null
}

export interface FileAssetResponse {
  id: number
  filename: string
  original_filename: string
  mime_type: string
  file_size: number
  storage_path: string
  storage_backend: string
  sha256?: string | null
  uploaded_by?: number | null
  created_at: string
}

export interface ReadingProgressUpdate {
  page?: number
  progress_percent?: number
  duration_sec?: number
  completed?: boolean
}

export interface ReadingProgressResponse {
  resource_id: number
  page?: number | null
  progress_percent?: number | null
  duration_sec: number
  visit_count: number
  last_read_at?: string | null
  viewed_at: string
  completed: boolean
}

export interface ReadingHistoryEntryResponse {
  resource_id: number
  viewed_at: string
  last_read_at?: string | null
  visit_count: number
  page?: number | null
  progress_percent?: number | null
  duration_sec: number
  completed: boolean
  // JOIN 附加的资源元信息（继续阅读卡直接渲染用）
  title?: string | null
  authors?: string[]
  discipline?: string | null
  year?: number | null
  resource_type?: string | null
}

export interface ReadingHistoryListResponse {
  data: ReadingHistoryEntryResponse[]
  meta: PaginationMeta
}

// --- Notifications ---
export interface NotificationResponse {
  id: number
  type: string
  title: string
  body?: string | null
  related_type?: string | null
  related_id?: string | null
  is_read: boolean
  created_at: string
}

export interface NotificationListResponse {
  data: NotificationResponse[]
  meta: PaginationMeta
}

export interface UnreadCountResponse {
  unread: number
}

// --- Follows ---
export interface FollowStatusResponse {
  following: boolean
  followers_count: number
}

export interface SubscriptionStatusResponse {
  subscribed: boolean
  subscribers_count: number
}

export interface AuthorFollowEntry {
  author_name: string
  followed_at: string
}

export interface AuthorFollowListResponse {
  data: AuthorFollowEntry[]
  meta: PaginationMeta
}

export interface DisciplineSubscriptionListResponse {
  data: string[]
}

// --- Ingest ---
export type IngestResourceType =
  | 'paper'
  | 'book'
  | 'journal'
  | 'preprint'
  | 'thesis'
  | 'dataset'
  | 'tutorial'

export type ParseFormat = 'bibtex' | 'ris' | 'csv'
export type FetchSource = 'crossref' | 'arxiv'

export interface IngestResource {
  title: string
  type: IngestResourceType
  authors: string[]
  year?: number | null
  venue?: string | null
  discipline: string
  subdiscipline?: string | null
  tags: string[]
  abstract: string
  doi?: string | null
  publisher?: string | null
  volume?: string | null
  issue?: string | null
  pages?: string | null
  issn?: string | null
  short_container_title?: string | null
}

export interface ParseRequest {
  format: ParseFormat
  content: string
}

export interface FetchRequest {
  source: FetchSource
  id: string
}

export interface ParseError {
  line: number
  error: string
}

export interface ParseResponse {
  data: IngestResource[]
  count: number
  errors: ParseError[]
}

// --- Recommendations ---
export interface RecommendationItem {
  id: number
  title: string
  authors: string[]
  year?: number | null
  doi?: string | null
  discipline?: string | null
  subdiscipline?: string | null
  tags: string[]
  score: number
  reason: string
}

export interface RecommendationListResponse {
  data: RecommendationItem[]
  meta: PaginationMeta
}

// --- Audit log (admin) ---
export interface AuditLogEntry {
  id: number
  tenant_id: string | null
  actor_user_id: number | null
  action: string
  target_type: string | null
  target_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

// --- Journal settings (admin) ---
export type ReviewMode = 'single_blind' | 'double_blind'

export interface ReviewModeResponse {
  review_mode: ReviewMode
}

// --- Volume / Issue management (admin) ---
export interface VolumeInfo {
  volume: string
  articleCount: number
  issueCount: number
}

export interface IssueInfo {
  issue: string
  articleCount: number
  firstYear: number
  lastYear: number
}

export interface JournalSettings {
  issn: string
  publisher: string
  short_container_title: string
}

// --- Export ---

// --- Gamification / 身份体系 ---
/**
 * 身份（3.0 口径）：四种真实身份，不再是九级 XP 阶梯。
 * ``level`` 字段保留为身份序号 1–4，兼容旧调用方。
 */
export interface LevelCapability {
  /** 身份序号 1–4（1=读者 … 4=编辑），兼容旧字段名 */
  level: number
  slug: string
  code: string
  name: string
  title: string
  /** 获得方式（"注册即得" / "编辑部授予"） */
  granted_by?: string
  /** 旧字段：保留兼容，新代码用 granted_by */
  track?: 'merit' | 'staff'
  xp_floor?: number
  roles?: string[]
  capabilities: string[]
  description: string
}

export interface LevelSnapshot extends LevelCapability {
  xp: number
  /** 已确认当版投稿规范 = 可投稿（合规状态，不是等级） */
  author_eligible?: boolean
  /** 下一个可争取的身份与获取方式；已在顶阶时为 null */
  next_identity?: { slug: string; name: string; how: string } | null
  roles: string[]
}

export interface BadgeItem {
  key: string
  name: string
  tier: 'bronze' | 'silver' | 'gold' | 'special'
  category: string
  description: string
  threshold: number
  secret: boolean
  unlocked: boolean
  unlocked_at: string | null
  current: number
}

export interface GamificationProfile {
  user_id: number
  username: string
  xp: number
  level: LevelSnapshot
  ladder: LevelCapability[]
  badges: BadgeItem[]
  unlocked_count: number
  total_badges: number
  metrics: Record<string, number>
  recent_xp: { action: string; points: number; note: string | null; created_at: string }[]
  rules_version: string
  rules_accepted: boolean
}

export interface LadderResponse {
  version: string
  levels: LevelCapability[]
  identities: LevelCapability[]
}

// --- Announcements ---
export interface Announcement {
  id: number
  slug: string
  title: string
  body: string
  level: 'info' | 'success' | 'warning' | 'critical'
  is_active: boolean
  starts_at: string
  ends_at: string | null
}

// --- Quality rubric ---
export interface QualityDimension {
  key: string
  label: string
  /** 这一维到底在问什么（v2.0 起提供） */
  hint?: string
  max_score?: number
}

/**
 * 评分口径（v3.0 起为 14 档 ABCDF± 严厉客观制）。
 * v3.0 移除了 ``coefficient_formula``（RQS/50 换算系数无人能懂），
 * 处置语义改为：<40 不合格（rejected，必须打回）、55–57 边缘稿
 * （borderline）、F（40–49）= 及格可发表。
 */
export interface QualityRubric {
  version: string
  dimensions: QualityDimension[]
  profiles: Record<string, { label: string; weights: Record<string, number> }>
  grades: { code: string; label: string; min: number; max: number }[]
  required_sections: string[]
  profile_sections: Record<string, string[]>
  min_references: Record<string, number>
  length_tiers: Record<string, { short: number; medium: number; long: number }>
  abstract_band: [number, number]
  /** 0–100 分锚点（v4.0 起） */
  score_anchors?: { score: number; meaning: string }[]
  /** 学术诚信一票否决的说明 */
  integrity_veto?: string
  /** 不合格的分数下限（v3.0 起，固定 40） */
  rejected_below?: number
  /** 不合格稿件处置说明（v3.0 起，取代旧的 grade_d_action） */
  rejected_action?: string
  /** 边缘稿分数带（v3.0 起，55–57） */
  borderline_band?: [number, number]
  /** 边缘稿处置说明（v3.0 起） */
  borderline_action?: string
}

/** 一个维度的评分（审稿人提交） */
export interface DimensionScoreInput {
  key: string
  score: number
  reason: string
  evidence: string
}

/** 评分结果（v3.0：rejected = <40 必须打回；borderline = 55–57 边缘稿） */
export interface QualityScoreResult {
  rubric_version: string
  track: 'academic' | 'absurd'
  track_label: string
  article_type: string
  article_type_label: string
  score: number
  grade: string
  grade_label: string
  breakdown: Record<
    string,
    {
      label: string
      score: number
      max_score: number
      points: number
      max_points: number
      ratio: number
      reason: string
    }
  >
  integrity_veto: boolean
  overridden: boolean
  /** 总分 <40：不合格，不予发表，必须打回（与 requires_rework 等价） */
  rejected: boolean
  /** 总分 55–57（D-）：可发表但属边缘稿，提示编辑谨慎 */
  borderline: boolean
  requires_rework: boolean
  auto_precheck?: { level: string; dimension: string; message: string }[]
}

/** 审稿评分表单里的一个检查项 */
export interface QualityCheckItem {
  key: string
  question: string
  weight: number
}

export interface QualityFormDimension {
  key: string
  label: string
  hint: string
  items: QualityCheckItem[]
}

export interface QualityForm {
  track: 'academic' | 'absurd'
  track_label: string
  dimensions: QualityFormDimension[]
  answers: { value: string; label: string }[]
  score_anchors: { score: number; meaning: string }[]
}

// --- Issue plan（发布日历）---
export interface IssuePlanEntry {
  volume: string
  issue: string
  label: string
  publish_at: string | null
  total: number
  published: number
  scheduled: number
  state: 'live' | 'scheduled' | 'empty'
}

export interface IssuePlanResponse {
  volume: string
  now: string
  entries: IssuePlanEntry[]
}
