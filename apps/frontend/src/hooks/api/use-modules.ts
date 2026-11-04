import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { downloadBlob } from '@/lib/utils'
import type {
  Announcement,
  AssignableRole,
  AssignmentCreate,
  AssignmentListResponse,
  AssignmentResponse,
  AuditLogEntry,
  AuthorFollowListResponse,
  DisciplineSubscriptionListResponse,
  FetchRequest,
  FollowStatusResponse,
  GamificationProfile,
  IngestResource,
  IssueInfo,
  IssuePlanEntry,
  IssuePlanResponse,
  JournalMetrics,
  JournalSettings,
  LadderResponse,
  LevelSnapshot,
  MessageResponse,
  NotificationListResponse,
  NotificationResponse,
  ParseRequest,
  ParseResponse,
  QualityRubric,
  ReadingListCreate,
  ReadingListDetailResponse,
  ReadingListItemCreate,
  ReadingListListResponse,
  ReadingListUpdate,
  ReadingProgressResponse,
  ReadingProgressUpdate,
  ReadingHistoryListResponse,
  RecommendationListResponse,
  ResourceCreate,
  ResourceListParams,
  ResourceListResponse,
  ResourceResponse,
  ResourceStats,
  ResourceUpdate,
  ReviewMode,
  ReviewModeResponse,
  ReviewReportResponse,
  ReviewSubmit,
  SubmissionCreate,
  SubmissionDecision,
  SubmissionListResponse,
  SubmissionResponse,
  SubmissionUpdate,
  SubmissionVersionListResponse,
  SubmissionVersionResponse,
  SubscriptionStatusResponse,
  UnreadCountResponse,
  UserResponse,
  VolumeInfo,
  QualityForm,
  DimensionScoreInput,
  QualityScoreResult,
} from '@/lib/types'

// query key 工厂，避免散落字符串
export const keys = {
  catalog: {
    list: (params: ResourceListParams) => ['catalog', 'list', params] as const,
    detail: (id: number) => ['catalog', 'detail', id] as const,
    stats: () => ['catalog', 'stats'] as const,
  },
  reader: {
    progress: (id: number) => ['reader', 'progress', id] as const,
    history: (page = 1) => ['reader', 'history', page] as const,
  },
  submission: {
    // page 必须进 key：queryFn 用了它，key 里没有就会出现「翻页后 60 秒内
    // 仍显示上一页」（staleTime 内命中同一 key 不会 refetch）。
    mine: (status?: string, page = 1) =>
      ['submissions', 'mine', status ?? 'all', page] as const,
    all: (status?: string, page = 1) =>
      ['submissions', 'all', status ?? 'all', page] as const,
    pending: (page = 1) => ['submissions', 'pending', page] as const,
    detail: (id: number) => ['submissions', 'detail', id] as const,
    assignments: (id: number) => ['submissions', id, 'assignments'] as const,
    reports: (id: number) => ['submissions', id, 'reports'] as const,
    versions: (id: number) => ['submissions', id, 'versions'] as const,
  },
  review: {
    myAssignments: (status?: string, page = 1) =>
      ['review', 'my-assignments', status ?? 'all', page] as const,
    assignment: (id: number) => ['review', 'assignment', id] as const,
    // 审稿人查看分配稿件的完整内容
    submission: (assignmentId: number) =>
      ['review', 'assignment', assignmentId, 'submission'] as const,
  },
  library: {
    list: (page = 1) => ['library', 'list', page] as const,
    detail: (id: number) => ['library', 'detail', id] as const,
  },
  notifications: {
    // pageSize 也要进 key：仪表盘取 (1,5)、通知页取 (1,20)，
    // 只带 page 会让两者共用一个缓存条目、互相污染数据。
    list: (page = 1, pageSize = 20) =>
      ['notifications', 'list', page, pageSize] as const,
    unread: () => ['notifications', 'unread'] as const,
  },
  recommendations: {
    me: (limit = 10) => ['recommendations', 'me', limit] as const,
  },
  admin: {
    users: (limit = 50, offset = 0) => ['admin', 'users', limit, offset] as const,
    usersSearch: (limit = 50, offset = 0, query = '') =>
      ['admin', 'users', limit, offset, query] as const,
    audit: (limit = 50, offset = 0) => ['admin', 'audit', limit, offset] as const,
    reviewMode: () => ['admin', 'review-mode'] as const,
    volumes: () => ['admin', 'volumes'] as const,
    issues: (volume: string) => ['admin', 'issues', volume] as const,
    journalSettings: () => ['admin', 'journal-settings'] as const,
    claims: (status: string) => ['admin', 'claims', status] as const,
  },
  claims: {
    status: (resourceId: number) => ['claims', 'status', resourceId] as const,
  },
  follows: {
    author: (name: string) => ['follows', 'author', name] as const,
    discipline: (slug: string) => ['follows', 'discipline', slug] as const,
    myAuthors: (page = 1) => ['follows', 'my-authors', page] as const,
    myDisciplines: () => ['follows', 'my-disciplines'] as const,
  },
  gamification: {
    profile: () => ['gamification', 'profile'] as const,
    ladder: () => ['gamification', 'ladder'] as const,
    checkin: () => ['gamification', 'checkin'] as const,
  },
  announcements: {
    active: () => ['announcements', 'active'] as const,
    all: () => ['announcements', 'all'] as const,
  },
  quality: {
    rubric: () => ['quality', 'rubric'] as const,
  },
  issuePlan: () => ['catalog', 'issue-plan'] as const,
} as const

// --- Catalog ---
export function useResources(params: ResourceListParams = {}) {
  return useQuery<ResourceListResponse>({
    queryKey: keys.catalog.list(params),
    queryFn: async () => (await api.get<ResourceListResponse>('/catalog', { params })).data,
    placeholderData: (prev) => prev,
    // 目录会随刊出变化：30 秒内视为新鲜，切回页面时自动刷新。
    staleTime: 30_000,
  })
}

export function useResource(id: number) {
  return useQuery<ResourceResponse>({
    queryKey: keys.catalog.detail(id),
    queryFn: async () => (await api.get<ResourceResponse>(`/catalog/${id}`)).data,
    enabled: id > 0,
    staleTime: 30_000,
  })
}

export function useJournalMetrics() {
  return useQuery<JournalMetrics>({
    queryKey: ['catalog', 'journal-metrics'],
    queryFn: async () => (await api.get<JournalMetrics>('/catalog/journal-metrics')).data,
    staleTime: 60_000,
  })
}

export function useCatalogStats() {
  return useQuery<ResourceStats>({
    queryKey: keys.catalog.stats(),
    queryFn: async () => (await api.get<ResourceStats>('/catalog/stats')).data,
    staleTime: 60_000,
  })
}

export function useCreateResource() {
  const qc = useQueryClient()
  return useMutation<ResourceResponse, Error, ResourceCreate>({
    mutationFn: async (body) => (await api.post<ResourceResponse>('/catalog', body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
    },
  })
}

export function useUpdateResource() {
  const qc = useQueryClient()
  return useMutation<
    ResourceResponse,
    Error,
    { id: number; body: ResourceUpdate }
  >({
    mutationFn: async ({ id, body }) =>
      (await api.patch<ResourceResponse>(`/catalog/${id}`, body)).data,
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.catalog.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['catalog'] })
    },
  })
}

export function useDeleteResource() {
  const qc = useQueryClient()
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await api.delete(`/catalog/${id}`)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
    },
  })
}

// Export 走 blob，触发浏览器下载
export async function exportResources(ids: number[], format: 'bibtex' | 'ris' | 'csv' | 'json') {
  const res = await api.get('/export', {
    params: { ids, format },
    responseType: 'blob',
  })
  downloadBlob(res.data, res.headers['content-disposition'] ?? '', `export.${format}`)
}

// --- Reader ---
export function useReadingProgress(
  resourceId: number,
  options?: { enabled?: boolean },
) {
  return useQuery<ReadingProgressResponse | null>({
    queryKey: keys.reader.progress(resourceId),
    queryFn: async () => {
      try {
        return (await api.get<ReadingProgressResponse>(`/reader/history/${resourceId}/progress`))
          .data
      } catch (err) {
        // 404 = 这个用户还没读过这篇，是正常状态而不是错误。
        // 之前它会走重试并往控制台打红字，看起来像坏页面。
        const status = (err as { response?: { status?: number } }).response?.status
        if (status === 404) return null
        throw err
      }
    },
    // 访客不发请求：阅读进度接口需要登录，未登录时只会得到 401。
    enabled: resourceId > 0 && (options?.enabled ?? true),
  })
}

export function useRecordView() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, number>({
    mutationFn: async (resourceId) =>
      (await api.post<MessageResponse>(`/reader/history/${resourceId}`)).data,
    onSuccess: () => {
      // Without this, the reading-history list never sees the new entry.
      void qc.invalidateQueries({ queryKey: ['reader'] })
    },
  })
}

// 阅读历史（继续阅读卡数据源）：带资源元信息，一次请求即可渲染。
export function useReadingHistory(page = 1, pageSize = 5) {
  return useQuery<ReadingHistoryListResponse>({
    queryKey: keys.reader.history(page),
    queryFn: async () =>
      (await api.get<ReadingHistoryListResponse>('/reader/history', {
        params: { page, page_size: pageSize },
      })).data,
    staleTime: 30_000,
  })
}

export function useUpdateProgress() {
  const qc = useQueryClient()
  return useMutation<
    ReadingProgressResponse,
    Error,
    { resourceId: number; body: ReadingProgressUpdate }
  >({
    mutationFn: async ({ resourceId, body }) =>
      (await api.put<ReadingProgressResponse>(`/reader/history/${resourceId}/progress`, body)).data,
    onSuccess: (data, { resourceId }) => {
      qc.setQueryData(keys.reader.progress(resourceId), data)
    },
  })
}

export function useRemoveFromHistory() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, number>({
    mutationFn: async (resourceId) =>
      (await api.delete<MessageResponse>(`/reader/history/${resourceId}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['reader'] })
    },
  })
}

// --- Submission ---
export function useCreateSubmission() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, SubmissionCreate>({
    mutationFn: async (body) =>
      (await api.post<SubmissionResponse>('/submissions', body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useMySubmissions(status?: string, page = 1, pageSize = 20) {
  return useQuery<SubmissionListResponse>({
    queryKey: keys.submission.mine(status, page),
    queryFn: async () =>
      (await api.get<SubmissionListResponse>('/submissions/me', {
        params: { status, page, page_size: pageSize },
      })).data,
  })
}

export function useAllSubmissions(status?: string, page = 1, pageSize = 20) {
  return useQuery<SubmissionListResponse>({
    queryKey: keys.submission.all(status, page),
    queryFn: async () =>
      (await api.get<SubmissionListResponse>('/submissions', {
        params: { status, page, page_size: pageSize },
      })).data,
  })
}

export interface ReviewerCandidate {
  id: number
  username: string
  email: string
}

export function useReviewerCandidates(limit = 200) {
  return useQuery<ReviewerCandidate[]>({
    queryKey: ['submissions', 'reviewer-candidates', limit] as const,
    queryFn: async () =>
      (
        await api.get<{ data: ReviewerCandidate[] }>('/submissions/reviewer-candidates', {
          params: { limit },
        })
      ).data.data,
    staleTime: 60_000,
  })
}

export function usePendingSubmissions(page = 1, pageSize = 20) {
  return useQuery<SubmissionListResponse>({
    queryKey: keys.submission.pending(page),
    queryFn: async () =>
      (await api.get<SubmissionListResponse>('/submissions/pending', {
        params: { page, page_size: pageSize },
      })).data,
  })
}

export function useReviewSubmission() {
  const qc = useQueryClient()
  return useMutation<
    MessageResponse,
    Error,
    {
      id: number
      body: { status: 'approved' | 'rejected'; admin_note?: string; resource_id?: number }
    }
  >({
    mutationFn: async ({ id, body }) =>
      (await api.patch<MessageResponse>(`/submissions/${id}/review`, body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useDeleteSubmission() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, number>({
    mutationFn: async (id) => (await api.delete<MessageResponse>(`/submissions/${id}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useSubmission(id: number) {
  return useQuery<SubmissionResponse>({
    queryKey: keys.submission.detail(id),
    queryFn: async () =>
      (await api.get<SubmissionResponse>(`/submissions/${id}`)).data,
    enabled: id > 0,
  })
}

// 编辑分配审稿人
export function useAssignReviewer() {
  const qc = useQueryClient()
  return useMutation<AssignmentResponse, Error, { id: number; body: AssignmentCreate }>({
    mutationFn: async ({ id, body }) =>
      (await api.post<AssignmentResponse>(`/submissions/${id}/assignments`, body)).data,
    onSuccess: (_, { id }) => {
      void qc.invalidateQueries({ queryKey: keys.submission.assignments(id) })
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

export function useSubmissionAssignments(id: number) {
  return useQuery<AssignmentListResponse>({
    queryKey: keys.submission.assignments(id),
    queryFn: async () =>
      (await api.get<AssignmentListResponse>(`/submissions/${id}/assignments`)).data,
    enabled: id > 0,
  })
}

export function useCancelAssignment() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, { submissionId: number; assignmentId: number }>({
    mutationFn: async ({ submissionId, assignmentId }) =>
      (await api.delete<MessageResponse>(
        `/submissions/${submissionId}/assignments/${assignmentId}`,
      )).data,
    onSuccess: (_, { submissionId }) => {
      void qc.invalidateQueries({ queryKey: keys.submission.assignments(submissionId) })
    },
  })
}

// 编辑 4-元决定
export function useEditorDecision() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; body: SubmissionDecision }>({
    mutationFn: async ({ id, body }) =>
      (await api.patch<SubmissionResponse>(`/submissions/${id}/decision`, body)).data,
    onSuccess: (_, { id }) => {
      qc.setQueryData(keys.submission.detail(id), _)
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

// 作者重投（note 可选：给编辑的修改说明，随新版本存档）
export function useResubmitSubmission() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; note?: string }>({
    mutationFn: async ({ id, note }) =>
      (
        await api.post<SubmissionResponse>(
          `/submissions/${id}/resubmit`,
          note ? { note } : {},
        )
      ).data,
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.submission.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['submissions'] })
      // 后端把重投快照成新版本，版本历史必须跟着失效，否则详情弹窗
      // 里的「版本历史」永远停在重投前。
      void qc.invalidateQueries({ queryKey: keys.submission.versions(id) })
    },
  })
}

// 作者修改稿件内容（pending / major_revision / minor_revision 状态限定）
export function useUpdateSubmission() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; body: SubmissionUpdate }>({
    mutationFn: async ({ id, body }) =>
      (await api.patch<SubmissionResponse>(`/submissions/${id}`, body)).data,
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.submission.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

// 编辑设置 / 清除双盲匿名稿外链（传 null 清除，仅编辑可写）
export function useSetAnonymizedFile() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; url: string | null }>({
    mutationFn: async ({ id, url }) =>
      (
        await api.put<SubmissionResponse>(`/submissions/${id}/anonymized-file`, {
          anonymized_file_url: url,
        })
      ).data,
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.submission.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

// 稿件版本历史（作者 + 编辑可见）
export function useSubmissionVersions(id: number, enabled = true) {
  return useQuery<SubmissionVersionResponse[]>({
    queryKey: keys.submission.versions(id),
    queryFn: async () =>
      (
        await api.get<SubmissionVersionListResponse>(
          `/submissions/${id}/versions`,
        )
      ).data.data,
    enabled: enabled && id > 0,
  })
}

// 作者上传稿件文件
export function useUploadSubmissionFile() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; file: File }>({
    mutationFn: async ({ id, file }) => {
      const form = new FormData()
      form.append('file', file)
      // 显式给的 multipart/form-data 没有 boundary，axios 检测到 FormData
      // 后会丢弃这个头、由浏览器自己补 boundary —— 行为正确，注释按实情写。
      const { data } = await api.post<SubmissionResponse>(
        `/submissions/${id}/files`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      return data
    },
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.submission.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}

// 下载稿件文件（作者/编辑/被指派审稿人）。用 blob + programmatic <a>
// 而不是裸 <a href>：请求必须带 Authorization 头，纯链接带不上。
export async function downloadSubmissionFile(id: number): Promise<void> {
  const { data, headers } = await api.get<Blob>(`/submissions/${id}/files`, {
    responseType: 'blob',
  })
  downloadBlob(
    data,
    (headers['content-disposition'] as string | undefined) ?? '',
    `submission-${id}.pdf`,
  )
}

// 审稿报告列表（单盲：作者只看 comments_to_author）
export function useSubmissionReports(id: number) {
  return useQuery<ReviewReportResponse[]>({
    queryKey: keys.submission.reports(id),
    queryFn: async () =>
      (await api.get<ReviewReportResponse[]>(`/submissions/${id}/reports`)).data,
    enabled: id > 0,
  })
}

// --- Reviewer side ---
export function useMyReviewAssignments(status?: string, page = 1, pageSize = 20) {
  return useQuery<AssignmentListResponse>({
    queryKey: keys.review.myAssignments(status, page),
    queryFn: async () =>
      (await api.get<AssignmentListResponse>('/review/assignments/me', {
        params: { status, page, page_size: pageSize },
      })).data,
  })
}

export function useReviewAssignment(id: number) {
  return useQuery<AssignmentResponse>({
    queryKey: keys.review.assignment(id),
    queryFn: async () =>
      (await api.get<AssignmentResponse>(`/review/assignments/${id}`)).data,
    enabled: id > 0,
  })
}

// 审稿人查看分配稿件的完整内容（abstract / file_path / keywords / jel_codes 等）
// 单盲剥离仅作用于作者侧的 review reports，审稿人需要看完整稿件
export function useReviewSubmissionDetail(assignmentId: number) {
  return useQuery<SubmissionResponse>({
    queryKey: keys.review.submission(assignmentId),
    queryFn: async () =>
      (await api.get<SubmissionResponse>(
        `/review/assignments/${assignmentId}/submission`,
      )).data,
    enabled: assignmentId > 0,
  })
}

export function useAcceptAssignment() {
  const qc = useQueryClient()
  return useMutation<AssignmentResponse, Error, number>({
    mutationFn: async (id) =>
      (await api.post<AssignmentResponse>(`/review/assignments/${id}/accept`)).data,
    onSuccess: (data, id) => {
      qc.setQueryData(keys.review.assignment(id), data)
      void qc.invalidateQueries({ queryKey: ['review', 'my-assignments'] })
    },
  })
}

export function useDeclineAssignment() {
  const qc = useQueryClient()
  return useMutation<AssignmentResponse, Error, number>({
    mutationFn: async (id) =>
      (await api.post<AssignmentResponse>(`/review/assignments/${id}/decline`)).data,
    onSuccess: (data, id) => {
      qc.setQueryData(keys.review.assignment(id), data)
      void qc.invalidateQueries({ queryKey: ['review', 'my-assignments'] })
    },
  })
}

export function useSubmitReview() {
  const qc = useQueryClient()
  return useMutation<ReviewReportResponse, Error, { id: number; body: ReviewSubmit }>({
    mutationFn: async ({ id, body }) =>
      (await api.post<ReviewReportResponse>(`/review/assignments/${id}/submit`, body)).data,
    onSuccess: (_, { id }) => {
      void qc.invalidateQueries({ queryKey: keys.review.assignment(id) })
      void qc.invalidateQueries({ queryKey: ['review', 'my-assignments'] })
    },
  })
}

// --- Library ---
export function useReadingLists(page = 1, pageSize = 20) {
  return useQuery<ReadingListListResponse>({
    queryKey: keys.library.list(page),
    queryFn: async () =>
      (await api.get<ReadingListListResponse>('/reading-lists', {
        params: { page, page_size: pageSize },
      })).data,
  })
}

export function useReadingList(id: number) {
  return useQuery<ReadingListDetailResponse>({
    queryKey: keys.library.detail(id),
    queryFn: async () =>
      (await api.get<ReadingListDetailResponse>(`/reading-lists/${id}`)).data,
    enabled: id > 0,
  })
}

export function useCreateReadingList() {
  const qc = useQueryClient()
  return useMutation<ReadingListDetailResponse, Error, ReadingListCreate>({
    mutationFn: async (body) =>
      (await api.post<ReadingListDetailResponse>('/reading-lists', body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useUpdateReadingList() {
  const qc = useQueryClient()
  return useMutation<
    ReadingListDetailResponse,
    Error,
    { id: number; body: ReadingListUpdate }
  >({
    mutationFn: async ({ id, body }) =>
      (await api.patch<ReadingListDetailResponse>(`/reading-lists/${id}`, body)).data,
    onSuccess: (data, { id }) => {
      qc.setQueryData(keys.library.detail(id), data)
      void qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useDeleteReadingList() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, number>({
    mutationFn: async (id) => (await api.delete<MessageResponse>(`/reading-lists/${id}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useAddReadingListItem() {
  const qc = useQueryClient()
  return useMutation<
    ReadingListDetailResponse,
    Error,
    { listId: number; body: ReadingListItemCreate }
  >({
    mutationFn: async ({ listId, body }) =>
      (await api.post<ReadingListDetailResponse>(`/reading-lists/${listId}/items`, body)).data,
    onSuccess: (data, { listId }) => {
      qc.setQueryData(keys.library.detail(listId), data)
      void qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useRemoveReadingListItem() {
  const qc = useQueryClient()
  return useMutation<void, Error, { listId: number; resourceId: number }>({
    mutationFn: async ({ listId, resourceId }) => {
      await api.delete(`/reading-lists/${listId}/items/${resourceId}`)
    },
    onSuccess: (_, { listId }) => {
      void qc.invalidateQueries({ queryKey: keys.library.detail(listId) })
    },
  })
}

// --- Notifications ---
export function useNotifications(page = 1, pageSize = 20) {
  return useQuery<NotificationListResponse>({
    queryKey: keys.notifications.list(page, pageSize),
    queryFn: async () =>
      (await api.get<NotificationListResponse>('/notifications', {
        params: { page, page_size: pageSize },
      })).data,
    refetchInterval: 30_000,
  })
}

export function useUnreadCount(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true
  return useQuery<UnreadCountResponse>({
    queryKey: keys.notifications.unread(),
    queryFn: async () => (await api.get<UnreadCountResponse>('/notifications/unread-count')).data,
    // 访客不轮询：未登录时该接口只会返回 401，白白打请求。
    enabled,
    refetchInterval: enabled ? 30_000 : false,
  })
}

export function useMarkAllRead() {
  const qc = useQueryClient()
  return useMutation<{ updated: number }, Error, void>({
    mutationFn: async () => (await api.patch('/notifications/read-all')).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

export function useMarkRead() {
  const qc = useQueryClient()
  return useMutation<NotificationResponse, Error, number>({
    mutationFn: async (id) =>
      (await api.patch<NotificationResponse>(`/notifications/${id}/read`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

export function useDeleteNotification() {
  const qc = useQueryClient()
  return useMutation<MessageResponse, Error, number>({
    mutationFn: async (id) =>
      (await api.delete<MessageResponse>(`/notifications/${id}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

// --- Recommendations ---
export function useMyRecommendations(limit = 10) {
  return useQuery<RecommendationListResponse>({
    queryKey: keys.recommendations.me(limit),
    queryFn: async () =>
      (await api.get<RecommendationListResponse>('/recommendations/me', {
        params: { limit },
      })).data,
  })
}

// --- Follows ---
export function useAuthorFollowStatus(authorName: string) {
  return useQuery<FollowStatusResponse>({
    queryKey: keys.follows.author(authorName),
    queryFn: async () =>
      (await api.get<FollowStatusResponse>(`/authors/${encodeURIComponent(authorName)}/follow`)).data,
    enabled: !!authorName,
  })
}

export function useFollowAuthor() {
  const qc = useQueryClient()
  return useMutation<FollowStatusResponse, Error, string>({
    mutationFn: async (authorName) =>
      (await api.post<FollowStatusResponse>(`/authors/${encodeURIComponent(authorName)}/follow`)).data,
    onSuccess: (data, authorName) => {
      qc.setQueryData(keys.follows.author(authorName), data)
      void qc.invalidateQueries({ queryKey: ['follows', 'my-authors'] })
    },
  })
}

export function useUnfollowAuthor() {
  const qc = useQueryClient()
  return useMutation<FollowStatusResponse, Error, string>({
    mutationFn: async (authorName) =>
      (await api.delete<FollowStatusResponse>(`/authors/${encodeURIComponent(authorName)}/follow`)).data,
    onSuccess: (data, authorName) => {
      qc.setQueryData(keys.follows.author(authorName), data)
      void qc.invalidateQueries({ queryKey: ['follows', 'my-authors'] })
    },
  })
}

export function useMyFollowedAuthors(page = 1, pageSize = 20) {
  return useQuery<AuthorFollowListResponse>({
    queryKey: keys.follows.myAuthors(page),
    queryFn: async () =>
      (await api.get<AuthorFollowListResponse>('/users/me/following/authors', {
        params: { page, page_size: pageSize },
      })).data,
  })
}

export function useDisciplineSubscriptionStatus(discipline: string) {
  return useQuery<SubscriptionStatusResponse>({
    queryKey: keys.follows.discipline(discipline),
    queryFn: async () =>
      (await api.get<SubscriptionStatusResponse>(`/disciplines/${encodeURIComponent(discipline)}/subscribe`)).data,
    enabled: !!discipline,
  })
}

export function useSubscribeDiscipline() {
  const qc = useQueryClient()
  return useMutation<SubscriptionStatusResponse, Error, string>({
    mutationFn: async (discipline) =>
      (await api.post<SubscriptionStatusResponse>(`/disciplines/${encodeURIComponent(discipline)}/subscribe`)).data,
    onSuccess: (data, discipline) => {
      qc.setQueryData(keys.follows.discipline(discipline), data)
      void qc.invalidateQueries({ queryKey: ['follows', 'my-disciplines'] })
    },
  })
}

export function useUnsubscribeDiscipline() {
  const qc = useQueryClient()
  return useMutation<SubscriptionStatusResponse, Error, string>({
    mutationFn: async (discipline) =>
      (await api.delete<SubscriptionStatusResponse>(`/disciplines/${encodeURIComponent(discipline)}/subscribe`)).data,
    onSuccess: (data, discipline) => {
      qc.setQueryData(keys.follows.discipline(discipline), data)
      void qc.invalidateQueries({ queryKey: ['follows', 'my-disciplines'] })
    },
  })
}

export function useMySubscribedDisciplines() {
  return useQuery<DisciplineSubscriptionListResponse>({
    queryKey: keys.follows.myDisciplines(),
    queryFn: async () =>
      (await api.get<DisciplineSubscriptionListResponse>('/users/me/subscriptions/disciplines')).data,
  })
}

// --- Ingest ---
export function useParseIngest() {
  return useMutation<ParseResponse, Error, ParseRequest>({
    mutationFn: async (body) => (await api.post<ParseResponse>('/ingest/parse', body)).data,
  })
}

export function useFetchIngest() {
  return useMutation<IngestResource, Error, FetchRequest>({
    mutationFn: async (body) => (await api.post<IngestResource>('/ingest/fetch', body)).data,
  })
}

// --- Admin ---
export function useAdminUsers(limit = 50, offset = 0, query = '') {
  return useQuery<UserResponse[]>({
    // query 进 key：搜索词变化要重新请求，而不是复用上一页的缓存
    queryKey: keys.admin.usersSearch(limit, offset, query),
    queryFn: async () =>
      (
        await api.get<UserResponse[]>('/admin/users', {
          params: { limit, offset, ...(query ? { q: query } : {}) },
        })
      ).data,
  })
}

export function useSetUserActive() {
  const qc = useQueryClient()
  return useMutation<UserResponse, Error, { userId: number; isActive: boolean }>({
    mutationFn: async ({ userId, isActive }) =>
      (await api.patch<UserResponse>(`/admin/users/${userId}/active`, null, {
        params: { is_active: isActive },
      })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}

// admin 给用户分配角色（同租户内幂等：已分配则后端返回 200）
export function useAssignRole() {
  const qc = useQueryClient()
  return useMutation<UserResponse, Error, { userId: number; role: AssignableRole }>({
    mutationFn: async ({ userId, role }) =>
      (await api.post<UserResponse>(`/admin/users/${userId}/roles`, { role })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}

// admin 撤销用户角色（不存在则后端 404）
export function useRevokeRole() {
  const qc = useQueryClient()
  return useMutation<UserResponse, Error, { userId: number; role: AssignableRole }>({
    mutationFn: async ({ userId, role }) =>
      (await api.delete<UserResponse>(`/admin/users/${userId}/roles/${role}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}

// --- 作者认领（Author Claim） ----------------------------------------------

export interface ClaimStatus {
  claimable: boolean
  state: 'open' | 'claimed'
  claimer?: string | null
  mine?: { id: number; status: string; created_at: string } | null
}

// 查询某篇文章当前可否被认领（登录后文章页据此显示认领入口）
export function useClaimStatus(resourceId: number | null, enabled = true) {
  return useQuery<ClaimStatus>({
    queryKey: keys.claims.status(resourceId ?? 0),
    enabled: enabled && resourceId != null,
    queryFn: async () =>
      (await api.get<ClaimStatus>(`/catalog/${resourceId}/claim-status`)).data,
  })
}

// 发起认领（登录用户对"无人认领"的存量文章）
export function useClaimResource() {
  const qc = useQueryClient()
  return useMutation<{ id: number; status: string }, Error, { resourceId: number; note?: string }>({
    mutationFn: async ({ resourceId, note }) =>
      (await api.post(`/catalog/${resourceId}/claim`, { note })).data,
    onSuccess: (_res, vars) => {
      void qc.invalidateQueries({ queryKey: keys.claims.status(vars.resourceId) })
    },
  })
}

export interface AdminClaim {
  id: number
  resource_id: number
  resource_title: string
  user_id: number
  username: string
  note: string | null
  status: 'pending' | 'approved' | 'rejected'
  decision_note: string | null
  created_at: string
  decided_at: string | null
}

// 编辑部：认领申请列表
export function useAdminClaims(claimStatus: string) {
  return useQuery<AdminClaim[]>({
    queryKey: keys.admin.claims(claimStatus),
    queryFn: async () =>
      (await api.get<AdminClaim[]>('/admin/claims', { params: { claim_status: claimStatus } }))
        .data,
  })
}

// 编辑部：批准 / 拒绝认领
export function useDecideClaim() {
  const qc = useQueryClient()
  return useMutation<{ id: number; status: string }, Error, { claimId: number; action: 'approve' | 'reject'; note?: string }>({
    mutationFn: async ({ claimId, action, note }) =>
      (await api.post(`/admin/claims/${claimId}/decision`, { action, note })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'claims'] })
    },
  })
}

// 期刊评审模式（单盲 / 双盲）——租户级设置
export function useReviewMode() {
  return useQuery<ReviewModeResponse>({
    queryKey: keys.admin.reviewMode(),
    queryFn: async () =>
      (await api.get<ReviewModeResponse>('/admin/settings/review-mode')).data,
  })
}

export function useSetReviewMode() {
  const qc = useQueryClient()
  return useMutation<ReviewModeResponse, Error, ReviewMode>({
    mutationFn: async (review_mode) =>
      (await api.patch<ReviewModeResponse>('/admin/settings/review-mode', { review_mode }))
        .data,
    onSuccess: (data) => {
      qc.setQueryData(keys.admin.reviewMode(), data)
      // 审稿人看到的稿件内容随模式变化，相关缓存需失效
      void qc.invalidateQueries({ queryKey: ['review'] })
    },
  })
}

export function useAdminAuditLogs(limit = 50, offset = 0) {
  return useQuery<AuditLogEntry[]>({
    queryKey: keys.admin.audit(limit, offset),
    queryFn: async () =>
      (await api.get<AuditLogEntry[]>('/admin/audit-logs', { params: { limit, offset } })).data,
  })
}

// --- Volume / Issue management (admin) ---

// 后端单页上限（catalog/routes.py MAX_PAGE_SIZE）。卷/期聚合目前只能拉一页
// 在前端推导，超过这个量就会少数据，所以页面必须把 truncated 提示出来。
export const CATALOG_PAGE_MAX = 100

export interface AggregatedListResult<T> {
  items: T[]
  /** 源数据已达单页上限：统计不完整，数字偏小。 */
  truncated: boolean
}

export function useVolumeList() {
  return useQuery<AggregatedListResult<VolumeInfo>>({
    queryKey: keys.admin.volumes(),
    queryFn: async () => {
      const res = await api.get<ResourceListResponse>('/catalog', {
        params: { page_size: CATALOG_PAGE_MAX, sort: 'year', order: 'desc' },
      })
      const resources = res.data.data
      const volumeMap = new Map<string, { articles: number; issues: Set<string> }>()
      for (const r of resources) {
        if (!r.volume) continue
        const v = volumeMap.get(r.volume) ?? { articles: 0, issues: new Set<string>() }
        v.articles++
        if (r.issue) v.issues.add(r.issue)
        volumeMap.set(r.volume, v)
      }
      return {
        items: Array.from(volumeMap.entries())
          .map(([volume, info]) => ({
            volume,
            articleCount: info.articles,
            issueCount: info.issues.size,
          }))
          .sort((a, b) => {
            const na = Number(a.volume)
            const nb = Number(b.volume)
            if (!Number.isNaN(na) && !Number.isNaN(nb)) return nb - na
            return b.volume.localeCompare(a.volume)
          }),
        truncated: resources.length >= CATALOG_PAGE_MAX,
      }
    },
    staleTime: 2 * 60_000,
  })
}

export function useIssueList(volume: string) {
  return useQuery<AggregatedListResult<IssueInfo>>({
    queryKey: keys.admin.issues(volume),
    queryFn: async () => {
      const res = await api.get<ResourceListResponse>('/catalog', {
        params: { page_size: CATALOG_PAGE_MAX, sort: 'year', order: 'desc' },
      })
      const resources = res.data.data.filter((r) => r.volume === volume)
      const issueMap = new Map<string, { articles: number; years: number[] }>()
      for (const r of resources) {
        if (!r.issue) continue
        const v = issueMap.get(r.issue) ?? { articles: 0, years: [] as number[] }
        v.articles++
        v.years.push(r.year)
        issueMap.set(r.issue, v)
      }
      return {
        items: Array.from(issueMap.entries())
          .map(([issue, info]) => ({
            issue,
            articleCount: info.articles,
            firstYear: Math.min(...info.years),
            lastYear: Math.max(...info.years),
          }))
          .sort((a, b) => {
            const na = Number(a.issue)
            const nb = Number(b.issue)
            if (!Number.isNaN(na) && !Number.isNaN(nb)) return nb - na
            return b.issue.localeCompare(a.issue)
          }),
        truncated: res.data.data.length >= CATALOG_PAGE_MAX,
      }
    },
    // 未选卷时不发请求：组件已经早退到空态，白打一个全量 /catalog 没意义。
    enabled: !!volume,
    staleTime: 2 * 60_000,
  })
}

export function useJournalSettings() {
  return useQuery<JournalSettings>({
    queryKey: keys.admin.journalSettings(),
    queryFn: async () => {
      const res = await api.get<ResourceListResponse>('/catalog', {
        params: { page_size: 100, sort: 'created_at', order: 'desc' },
      })
      const resources = res.data.data
      const issn = resources.find((r) => r.issn)?.issn ?? ''
      const publisher = resources.find((r) => r.publisher)?.publisher ?? ''
      const short_container_title =
        resources.find((r) => r.short_container_title)?.short_container_title ?? ''
      return { issn, publisher, short_container_title }
    },
    staleTime: 5 * 60_000,
  })
}

// --- Gamification / 等级体系 ---
export function useGamificationProfile(options?: { enabled?: boolean }) {
  return useQuery<GamificationProfile>({
    queryKey: keys.gamification.profile(),
    queryFn: async () => (await api.get<GamificationProfile>('/gamification/me')).data,
    enabled: options?.enabled ?? true,
    staleTime: 60_000,
  })
}

export interface CheckinStatus {
  checked_in_today: boolean
  streak: number
  total: number
  daily_xp: number
  weekly_bonus_xp: number
}

export interface CheckinResult extends CheckinStatus {
  awarded: boolean
  bonus_awarded: boolean
}

export function useCheckinStatus(options?: { enabled?: boolean }) {
  return useQuery<CheckinStatus>({
    queryKey: keys.gamification.checkin(),
    queryFn: async () => (await api.get<CheckinStatus>('/gamification/checkin')).data,
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
  })
}

export function useDailyCheckin() {
  const qc = useQueryClient()
  return useMutation<CheckinResult, unknown, void>({
    mutationFn: async () => (await api.post<CheckinResult>('/gamification/checkin')).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.gamification.checkin() })
      void qc.invalidateQueries({ queryKey: keys.gamification.profile() })
    },
  })
}

export function useLadder() {
  return useQuery<LadderResponse>({
    queryKey: keys.gamification.ladder(),
    queryFn: async () => (await api.get<LadderResponse>('/gamification/ladder')).data,
    staleTime: 10 * 60_000,
  })
}

export function useAcknowledgeCommunity() {
  const qc = useQueryClient()
  return useMutation<{ level: LevelSnapshot }, unknown, void>({
    mutationFn: async () => (await api.post('/gamification/onboarding/community')).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.gamification.profile() })
      void qc.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
  })
}

export function useAcceptAuthorRules() {
  const qc = useQueryClient()
  return useMutation<{ level: LevelSnapshot; rules_version: string }, unknown, void>({
    mutationFn: async () =>
      (await api.post('/gamification/onboarding/author', { accept_rules: true })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.gamification.profile() })
      void qc.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
  })
}

// --- Announcements ---
export function useActiveAnnouncement() {
  return useQuery<Announcement | null>({
    queryKey: keys.announcements.active(),
    queryFn: async () => {
      const res = await api.get<Announcement | null>('/announcements/active')
      return res.data
    },
    staleTime: 5 * 60_000,
  })
}

// --- Quality rubric ---
export function useQualityRubric() {
  return useQuery<QualityRubric>({
    queryKey: keys.quality.rubric(),
    queryFn: async () => (await api.get<QualityRubric>('/quality/rubric')).data,
    staleTime: 30 * 60_000,
  })
}

export function useIssuePlan() {
  return useQuery<IssuePlanResponse>({
    queryKey: keys.issuePlan(),
    queryFn: async () => (await api.get<IssuePlanResponse>('/catalog/issue-plan')).data,
    staleTime: 5 * 60_000,
  })
}

export function usePublishIssue() {
  const qc = useQueryClient()
  return useMutation<
    IssuePlanEntry,
    unknown,
    { volume: string; issue: string; publishAt: string | null }
  >({
    mutationFn: async ({ volume, issue, publishAt }) =>
      (
        await api.post(`/catalog/issues/${volume}/${issue}/publish`, {
          publish_at: publishAt,
        })
      ).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
      void qc.invalidateQueries({ queryKey: keys.issuePlan() })
    },
  })
}

// --- 质量评分 v3.0（审稿表单 / 算分 / 改分 / 打回） ---

export function useQualityForm() {
  return useQuery<QualityForm>({
    queryKey: [...keys.quality.rubric(), 'form'],
    queryFn: async () => (await api.get<QualityForm>('/quality/form')).data,
    staleTime: 30 * 60_000,
  })
}

/** 按检查项答案折算建议分（无需登录，作者自查也能用）。 */
export function useSuggestScores() {
  return useMutation<
    { dimensions: Record<string, { label: string; suggested_score: number; items: unknown[] }> },
    Error,
    Record<string, string>
  >({
    mutationFn: async (answers) => (await api.post('/quality/suggest', { answers })).data,
  })
}

/** 服务端算分（审稿人）：返回总分、等级、逐维明细。 */
export function useComputeQualityScore() {
  return useMutation<
    QualityScoreResult,
    Error,
    { article_type: string; dimensions: DimensionScoreInput[] }
  >({
    mutationFn: async (body) => (await api.post('/quality/score', body)).data,
  })
}

/** 管理员改分（必须写理由）。 */
export function useOverrideQualityScore() {
  const qc = useQueryClient()
  return useMutation<unknown, Error, { score: number; reason: string }>({
    mutationFn: async (body) => (await api.post('/quality/override', body)).data,
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.quality.rubric() }),
  })
}

/** D 级打回：通知审稿人补审 + 作者修改。 */
export function useRequestRework() {
  const qc = useQueryClient()
  return useMutation<
    SubmissionResponse,
    Error,
    { id: number; requirements: string[]; note?: string }
  >({
    mutationFn: async ({ id, ...body }) =>
      (await api.post<SubmissionResponse>(`/submissions/${id}/rework`, body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['submissions'] })
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

/** 设置/取消平台管理员（提权）。后端拒绝改自己、拒绝降级最后一个管理员。 */
export function useSetUserAdmin() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    Error,
    { userId: number; isAdmin: boolean }
  >({
    mutationFn: async ({ userId, isAdmin }) =>
      (
        await api.patch(`/admin/users/${userId}/admin`, null, {
          params: { is_admin: isAdmin },
        })
      ).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
  })
}

/** 作者上传封面图（PNG/JPEG/WebP ≤5MB）。 */
export function useUploadSubmissionCover() {
  const qc = useQueryClient()
  return useMutation<SubmissionResponse, Error, { id: number; file: File }>({
    mutationFn: async ({ id, file }) => {
      const fd = new FormData()
      fd.append('file', file)
      return (await api.post<SubmissionResponse>(`/submissions/${id}/cover`, fd)).data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })
}
