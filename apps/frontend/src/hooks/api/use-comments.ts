import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { PaginationMeta } from '@/lib/types'

export interface CommentItem {
  id: number
  resource_id: number
  user_id: number
  author_name: string
  author_avatar_url?: string | null
  body: string
  created_at: string
}

export interface CommentListResponse {
  data: CommentItem[]
  meta: PaginationMeta
}

// --- 后台审核（editor 及以上） ---
export type CommentModerationStatus = 'pending' | 'published' | 'rejected'

export interface AdminCommentRow {
  id: number
  resource_id: number
  resource_title: string | null
  user_id: number
  author_name: string
  body: string
  status: CommentModerationStatus
  moderation_note: string | null
  moderated_by: number | null
  moderated_by_name: string | null
  moderated_at: string | null
  created_at: string
}

export interface AdminCommentListResponse {
  data: AdminCommentRow[]
  meta: PaginationMeta
}

export interface AdminCommentStatusCounts {
  pending: number
  published: number
  rejected: number
}

const keys = {
  list: (resourceId: number, page: number) =>
    ['comments', 'list', resourceId, page] as const,
  adminList: (status: CommentModerationStatus | 'all', page: number) =>
    ['admin', 'comments', status, page] as const,
  adminCounts: () => ['admin', 'comments', 'counts'] as const,
}

export function useComments(resourceId: number, page = 1) {
  return useQuery({
    queryKey: keys.list(resourceId, page),
    queryFn: async () =>
      (
        await api.get<CommentListResponse>('/comments', {
          params: { resource_id: resourceId, page, page_size: 20 },
        })
      ).data,
    staleTime: 30_000,
  })
}

export function useCreateComment(resourceId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: string) =>
      (await api.post<CommentItem>('/comments', { resource_id: resourceId, body })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['comments', 'list', resourceId] })
    },
  })
}

export function useDeleteComment(resourceId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (commentId: number) => {
      await api.delete(`/comments/${commentId}`)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['comments', 'list', resourceId] })
    },
  })
}

// --- 后台审核 hooks ---

export function useAdminComments(
  status: CommentModerationStatus | 'all',
  page: number,
  enabled = true,
) {
  return useQuery({
    queryKey: keys.adminList(status, page),
    queryFn: async () =>
      (
        await api.get<AdminCommentListResponse>('/admin/comments', {
          params: status === 'all' ? { page, page_size: 20 } : { status, page, page_size: 20 },
        })
      ).data,
    enabled,
  })
}

export function useAdminCommentCounts(enabled = true) {
  return useQuery({
    queryKey: keys.adminCounts(),
    queryFn: async () =>
      (await api.get<AdminCommentStatusCounts>('/admin/comments/counts')).data,
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

export function useModerateComment() {
  const qc = useQueryClient()
  return useMutation<
    AdminCommentRow,
    Error,
    { commentId: number; action: 'approve' | 'reject'; note?: string }
  >({
    mutationFn: async ({ commentId, action, note }) =>
      (await api.post<AdminCommentRow>(`/admin/comments/${commentId}/moderate`, { action, note }))
        .data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'comments'] })
    },
  })
}
