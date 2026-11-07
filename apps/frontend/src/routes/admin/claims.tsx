import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { createFileRoute } from '@tanstack/react-router'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import { useAdminClaims, useDecideClaim, useAssignOwner } from '@/hooks/api/use-modules'
import type { AdminClaimEntry } from '@/lib/types'
import { extractError, formatDateTime } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/admin/claims')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: ClaimsAdminPage,
})

const STATUS_LABEL: Record<string, string> = {
  pending: '待审',
  approved: '已批准',
  rejected: '已驳回',
}

const STATUS_VARIANT: Record<string, 'default' | 'destructive' | 'outline' | 'secondary'> = {
  pending: 'outline',
  approved: 'default',
  rejected: 'destructive',
}

const EVIDENCE_LABEL: Record<string, string> = {
  email: '原稿邮箱',
  orcid: 'ORCID',
  manuscript_id: '稿件编号',
}

/**
 * 作者认领审批台（v5）：卡片列表。
 * 通过/驳回/驳回后指定给其他申请人（逐位调用 assign-owner）。
 */
function ClaimsAdminPage() {
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const decideMut = useDecideClaim()
  const assignMut = useAssignOwner()

  const [rejectTarget, setRejectTarget] = useState<AdminClaimEntry | null>(null)
  const [rejectNote, setRejectNote] = useState('')
  const [assignTarget, setAssignTarget] = useState<AdminClaimEntry | null>(null)
  const [assignUserId, setAssignUserId] = useState('')
  const [assignPosition, setAssignPosition] = useState<number>(1)

  const { data, isLoading, isError, refetch } = useAdminClaims(statusFilter)
  const rows = data?.data ?? []

  const onReject = async () => {
    if (!rejectTarget) return
    try {
      await decideMut.mutateAsync({
        claimId: rejectTarget.id,
        body: { approve: false, note: rejectNote.trim() || undefined },
      })
      toast.success('已驳回并通知申请人')
      setRejectTarget(null)
      setRejectNote('')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const onApprove = async (row: AdminClaimEntry) => {
    try {
      await decideMut.mutateAsync({
        claimId: row.id,
        body: { approve: true, author_position: row.author_position },
      })
      toast.success('已通过：文章已挂到认领人名下')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const onAssign = async () => {
    if (!assignTarget) return
    const uid = Number(assignUserId.trim())
    if (!uid || Number.isNaN(uid)) {
      toast.error('请填写正确的用户 ID')
      return
    }
    try {
      await assignMut.mutateAsync({
        resourceId: assignTarget.resource_id,
        body: { user_id: uid, author_position: assignPosition },
      })
      toast.success(`已指定用户 ${uid} 为第 ${assignPosition} 作者`)
      setAssignTarget(null)
      setAssignUserId('')
      setAssignPosition(1)
    } catch (err) {
      toast.error(extractError(err, '指定失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="认领审批"
        description="作者对无人认领的存量文章的认领申请。通过即挂到认领人名下；驳回后可指定给其他申请人。"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {(['pending', 'approved', 'rejected'] as const).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={statusFilter === s ? 'default' : 'outline'}
                onClick={() => setStatusFilter(s)}
              >
                {STATUS_LABEL[s]}
              </Button>
            ))}
          </div>
        }
      />

      <div className="space-y-3">
        {isLoading ? (
          <Loading />
        ) : isError ? (
          <ErrorState message="加载认领申请失败" onRetry={() => refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={statusFilter === 'pending' ? '没有待处理的认领申请' : '暂无记录'}
          />
        ) : (
          rows.map((row) => (
            <Card key={row.id} className="py-4">
              <CardContent className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-medium">@{row.username}</span>
                    <Badge variant={STATUS_VARIANT[row.status]}>
                      {STATUS_LABEL[row.status] ?? row.status}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(row.created_at)}
                    </span>
                  </div>
                  {row.status === 'pending' && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={decideMut.isPending}
                        onClick={() => void onApprove(row)}
                      >
                        通过
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={decideMut.isPending}
                        onClick={() => {
                          setRejectTarget(row)
                          setRejectNote('')
                        }}
                      >
                        驳回
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={assignMut.isPending}
                        onClick={() => {
                          setAssignTarget(row)
                          setAssignPosition(row.author_position || 1)
                          setAssignUserId('')
                        }}
                      >
                        指定他人
                      </Button>
                    </div>
                  )}
                </div>
                <Link
                  to="/catalog/$resourceId"
                  params={{ resourceId: String(row.resource_id) }}
                  className="block text-sm leading-snug underline-offset-4 hover:underline"
                >
                  《{row.title}》
                </Link>
                <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-3">
                  <p>位次：第 {row.author_position} 作者</p>
                  <p>依据类型：{EVIDENCE_LABEL[row.evidence_type] ?? row.evidence_type}</p>
                  <p className="truncate">依据：{row.evidence_value}</p>
                </div>
                {row.note && (
                  <p className="text-xs text-muted-foreground">处理备注：{row.note}</p>
                )}
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* 驳回对话框 */}
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
            <DialogTitle>驳回认领</DialogTitle>
            <DialogDescription>
              驳回原因会作为站内通知发给申请人。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="claim-reject-note">驳回原因（必填）</Label>
            <Textarea
              id="claim-reject-note"
              rows={3}
              maxLength={500}
              value={rejectNote}
              onChange={(e) => setRejectNote(e.target.value)}
              placeholder="例：未能确认您与该文章的作者关系，请补充证明材料后重新申请。"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setRejectTarget(null); setRejectNote('') }}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={decideMut.isPending || !rejectNote.trim()}
              onClick={() => void onReject()}
            >
              {decideMut.isPending ? '处理中…' : '确认驳回'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 指定他人对话框 */}
      <Dialog
        open={assignTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAssignTarget(null)
            setAssignUserId('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>指定给其他申请人</DialogTitle>
            <DialogDescription>
              输入用户 ID 与位次，将本文直接绑定到该用户名下。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="assign-user-id">用户 ID</Label>
              <Input
                id="assign-user-id"
                type="number"
                value={assignUserId}
                onChange={(e) => setAssignUserId(e.target.value)}
                placeholder="例：42"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="assign-position">作者位次</Label>
              <Input
                id="assign-position"
                type="number"
                min={1}
                value={assignPosition}
                onChange={(e) => setAssignPosition(Number(e.target.value))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignTarget(null)}>取消</Button>
            <Button disabled={assignMut.isPending} onClick={() => void onAssign()}>
              {assignMut.isPending ? '绑定中…' : '确认绑定'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
