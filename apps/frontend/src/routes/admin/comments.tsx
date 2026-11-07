import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Check, X } from 'lucide-react'
import { toast } from 'sonner'

import { requireAdminGuard } from '@/lib/route-guards'
import { extractError } from '@/lib/utils'
import {
  useAdminComments,
  useAdminCommentCounts,
  useModerateComment,
  type AdminCommentRow,
  type CommentModerationStatus,
} from '@/hooks/api/use-comments'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/admin/comments')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminCommentsPage,
})

type TabValue = CommentModerationStatus

const TAB_META: { value: TabValue; label: string }[] = [
  { value: 'pending', label: '待审' },
  { value: 'published', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
]

const STATUS_BADGE: Record<TabValue, 'secondary' | 'default' | 'destructive'> = {
  pending: 'secondary',
  published: 'default',
  rejected: 'destructive',
}

function AdminCommentsPage() {
  const [tab, setTab] = useState<TabValue>('pending')
  const [page, setPage] = useState(1)
  const [rejectTarget, setRejectTarget] = useState<AdminCommentRow | null>(null)
  const [rejectNote, setRejectNote] = useState('')

  const { data, isLoading, isError, refetch } = useAdminComments(tab, page)
  const { data: counts } = useAdminCommentCounts()
  const moderateMut = useModerateComment()

  async function onApprove(row: AdminCommentRow) {
    try {
      await moderateMut.mutateAsync({ commentId: row.id, action: 'approve' })
      toast.success('已通过：评论保留在前台')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  async function onConfirmReject() {
    if (!rejectTarget) return
    try {
      await moderateMut.mutateAsync({
        commentId: rejectTarget.id,
        action: 'reject',
        note: rejectNote.trim() || undefined,
      })
      toast.success('已拒绝：评论从前台下架')
      setRejectTarget(null)
      setRejectNote('')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="评论审核"
        description="新评论默认 pending（事后审核，前台仍展示）；判 reject 后立即下架。"
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as TabValue)
            setPage(1)
          }}
        >
          <TabsList>
            {TAB_META.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="gap-1.5">
                {t.label}
                <Badge
                  variant={t.value === 'pending' && (counts?.pending ?? 0) > 0 ? 'destructive' : 'outline'}
                  className="ml-1 h-5 px-1.5 text-[10px]"
                >
                  {counts?.[t.value] ?? 0}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载评论失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState
          title={tab === 'pending' ? '没有待审评论' : '该状态下暂无评论'}
        />
      ) : (
        <div className="space-y-3">
          {data.data.map((row) => (
            <Card key={row.id} className="py-4">
              <CardContent className="space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant={STATUS_BADGE[row.status]}>{TAB_META.find((t) => t.value === row.status)?.label}</Badge>
                  <span className="font-medium">{row.author_name}</span>
                  <span className="text-muted-foreground">评论于文章</span>
                  <span className="text-foreground">{row.resource_title ?? `#${row.resource_id}`}</span>
                  <span className="ml-auto text-muted-foreground">
                    {new Date(row.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-sm">{row.body}</p>
                {row.moderation_note && (
                  <p className="text-xs text-muted-foreground">
                    审核备注：{row.moderation_note}
                    {row.moderated_by_name ? `（${row.moderated_by_name}）` : ''}
                  </p>
                )}
                {row.status === 'pending' && (
                  <div className="flex justify-end gap-2 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={moderateMut.isPending}
                      onClick={() => onApprove(row)}
                    >
                      <Check className="mr-1 h-3.5 w-3.5" />
                      通过
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={moderateMut.isPending}
                      onClick={() => {
                        setRejectTarget(row)
                        setRejectNote('')
                      }}
                    >
                      <X className="mr-1 h-3.5 w-3.5" />
                      拒绝
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          onPageChange={setPage}
        />
      )}

      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRejectTarget(null)
            setRejectNote('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>拒绝该评论</DialogTitle>
            <DialogDescription>
              拒绝后该评论从前台评论区立即下架；理由仅留痕，不向作者公开展示。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="comment-reject-note">拒绝理由（可选）</Label>
            <Textarea
              id="comment-reject-note"
              rows={3}
              maxLength={500}
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="例：含推广链接 / 人身攻击 / 与主题无关"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRejectTarget(null)
                setRejectNote('')
              }}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={moderateMut.isPending}
              onClick={() => void onConfirmReject()}
            >
              {moderateMut.isPending ? '处理中…' : '确认拒绝'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
