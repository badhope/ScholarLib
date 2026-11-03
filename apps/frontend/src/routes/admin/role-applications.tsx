import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { requireAdminGuard } from '@/lib/route-guards'
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
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/admin/role-applications')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: RoleApplicationsAdminPage,
})

interface ApplicationRow {
  id: number
  user_id: number
  username: string | null
  target_role: string
  status: 'pending' | 'approved' | 'rejected'
  statement: string
  decision_note: string | null
  created_at: string | null
}

interface ApplicationsQueueResponse {
  data: ApplicationRow[]
  meta: { total: number; page: number; page_size: number; total_pages: number }
}

const ROLE_LABEL: Record<string, string> = {
  reviewer: '审稿人',
  senior_reviewer: '资深审稿人',
}

const STATUS_LABEL: Record<string, string> = {
  pending: '待审',
  approved: '已通过',
  rejected: '未通过',
}

const STATUS_VARIANT: Record<string, 'default' | 'destructive' | 'outline' | 'secondary'> = {
  pending: 'outline',
  approved: 'default',
  rejected: 'destructive',
}

const PAGE_SIZE = 20

function RoleApplicationsAdminPage() {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'rejected' | 'all'>(
    'pending',
  )
  const [busyId, setBusyId] = useState<number | null>(null)
  // 拒绝原因走 Dialog，不用 window.prompt：原生弹窗在移动端被拦截样式割裂，
  // 也无法承载「选填原因 + 说明会通知申请人」这层上下文。
  const [rejectTarget, setRejectTarget] = useState<ApplicationRow | null>(null)
  const [rejectNote, setRejectNote] = useState('')

  const params: Record<string, unknown> = { page, page_size: PAGE_SIZE }
  if (statusFilter !== 'all') params.status = statusFilter

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['admin', 'role-applications', statusFilter, page],
    queryFn: async () =>
      (
        await api.get<ApplicationsQueueResponse>('/gamification/admin/applications', {
          params,
        })
      ).data,
  })

  const send = async (id: number, decision: 'approve' | 'reject', note: string | null) => {
    setBusyId(id)
    try {
      await api.post(`/gamification/admin/applications/${id}/decision`, { decision, note })
      toast.success(decision === 'approve' ? '已批准并授角色' : '已拒绝并通知申请人')
      void qc.invalidateQueries({ queryKey: ['admin', 'role-applications'] })
      return true
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
      return false
    } finally {
      setBusyId(null)
    }
  }

  const onReject = async () => {
    if (!rejectTarget) return
    const ok = await send(rejectTarget.id, 'reject', rejectNote.trim() || null)
    if (ok) {
      setRejectTarget(null)
      setRejectNote('')
    }
  }

  return (
    <div>
      <PageHeader
        title="角色申请审批"
        description="审稿人 / 资深审稿人申请队列。批准即授角色并通知申请人，全程写审计。"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {(['pending', 'approved', 'rejected', 'all'] as const).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={statusFilter === s ? 'default' : 'outline'}
                onClick={() => {
                  setStatusFilter(s)
                  setPage(1)
                }}
              >
                {s === 'all' ? '全部' : STATUS_LABEL[s]}
              </Button>
            ))}
          </div>
        }
      />

      <div className="space-y-3">
        {isLoading ? (
          <Loading />
        ) : isError ? (
          <ErrorState message="加载申请队列失败" onRetry={() => refetch()} />
        ) : !data || data.data.length === 0 ? (
          <EmptyState
            title={statusFilter === 'pending' ? '没有待处理的申请' : '暂无记录'}
            description={statusFilter === 'pending' ? '切到「全部」可查看历史记录。' : undefined}
          />
        ) : (
          data.data.map((row) => (
            <Card key={row.id} className="py-4">
              <CardContent className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{row.username ?? `用户 #${row.user_id}`}</span>
                    <Badge variant="secondary">{ROLE_LABEL[row.target_role] ?? row.target_role}</Badge>
                    <Badge variant={STATUS_VARIANT[row.status]}>
                      {STATUS_LABEL[row.status] ?? row.status}
                    </Badge>
                  </div>
                  {row.status === 'pending' && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={busyId === row.id}
                        onClick={() => void send(row.id, 'approve', null)}
                      >
                        批准
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === row.id}
                        onClick={() => {
                          setRejectTarget(row)
                          setRejectNote('')
                        }}
                      >
                        拒绝
                      </Button>
                    </div>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">{row.statement}</p>
                {row.decision_note ? (
                  <p className="text-xs text-muted-foreground">处理备注：{row.decision_note}</p>
                ) : null}
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {data && data.meta.total_pages > 1 && (
        <Pagination page={data.meta.page} totalPages={data.meta.total_pages} onPageChange={setPage} />
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
            <DialogTitle>拒绝申请</DialogTitle>
            <DialogDescription>
              原因会作为站内通知发给申请人；留空则发送默认文案。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reject-note">拒绝原因（选填）</Label>
            <Textarea
              id="reject-note"
              rows={3}
              maxLength={500}
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="例：目前审稿人池已满，欢迎下次再申请。"
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
              disabled={busyId !== null}
              onClick={() => void onReject()}
            >
              {busyId !== null ? '处理中…' : '确认拒绝'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
