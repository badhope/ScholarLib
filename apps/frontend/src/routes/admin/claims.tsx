import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { createFileRoute } from '@tanstack/react-router'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import { useAdminClaims, useDecideClaim } from '@/hooks/api/use-modules'
import type { AdminClaim } from '@/hooks/api/use-modules'
import { extractError } from '@/lib/utils'
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
  rejected: '已拒绝',
}

const STATUS_VARIANT: Record<string, 'default' | 'destructive' | 'outline' | 'secondary'> = {
  pending: 'outline',
  approved: 'default',
  rejected: 'destructive',
}

/**
 * 作者认领审批台：作者对"无人认领"的存量文章发起认领后，
 * 编辑部在这里批准 / 拒绝。批准即把文章挂到认领人名下
 * （自动创建 accepted 关联投稿）并通知申请人。
 */
function ClaimsAdminPage() {
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'rejected' | 'all'>(
    'pending',
  )
  const decideMut = useDecideClaim()
  // 拒绝原因走 Dialog：与角色申请审批页同款交互，原生 prompt 移动端样式割裂。
  const [rejectTarget, setRejectTarget] = useState<AdminClaim | null>(null)
  const [rejectNote, setRejectNote] = useState('')

  const { data, isLoading, isError, refetch } = useAdminClaims(statusFilter)

  const onReject = async () => {
    if (!rejectTarget) return
    try {
      await decideMut.mutateAsync({
        claimId: rejectTarget.id,
        action: 'reject',
        note: rejectNote.trim() || undefined,
      })
      toast.success('已拒绝并通知申请人')
      setRejectTarget(null)
      setRejectNote('')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const onApprove = async (row: AdminClaim) => {
    try {
      await decideMut.mutateAsync({ claimId: row.id, action: 'approve' })
      toast.success('已批准：文章已挂到认领人名下')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="认领审批"
        description="作者对无人认领的存量文章的认领申请。批准即创建关联投稿把文章挂到认领人名下。"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {(['pending', 'approved', 'rejected', 'all'] as const).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={statusFilter === s ? 'default' : 'outline'}
                onClick={() => setStatusFilter(s)}
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
          <ErrorState message="加载认领申请失败" onRetry={() => refetch()} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title={statusFilter === 'pending' ? '没有待处理的认领申请' : '暂无记录'}
            description={statusFilter === 'pending' ? '切到「全部」可查看历史记录。' : undefined}
          />
        ) : (
          data.map((row) => (
            <Card key={row.id} className="py-4">
              <CardContent className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-medium">{row.username}</span>
                    <Badge variant={STATUS_VARIANT[row.status]}>
                      {STATUS_LABEL[row.status] ?? row.status}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {new Date(row.created_at).toLocaleString()}
                    </span>
                  </div>
                  {row.status === 'pending' && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={decideMut.isPending}
                        onClick={() => void onApprove(row)}
                      >
                        批准
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
                        拒绝
                      </Button>
                    </div>
                  )}
                </div>
                {/* 标题单独一行且可换行：不与按钮挤同一行，避免窄屏截断 */}
                <Link
                  to="/catalog/$resourceId"
                  params={{ resourceId: String(row.resource_id) }}
                  className="block text-sm leading-snug underline-offset-4 hover:underline"
                >
                  《{row.resource_title}》
                </Link>
                {row.note ? (
                  <p className="text-sm text-muted-foreground">申请说明：{row.note}</p>
                ) : null}
                {row.decision_note ? (
                  <p className="text-xs text-muted-foreground">处理备注：{row.decision_note}</p>
                ) : null}
              </CardContent>
            </Card>
          ))
        )}
      </div>

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
            <DialogTitle>拒绝认领</DialogTitle>
            <DialogDescription>
              原因会作为站内通知发给申请人；留空则发送默认文案。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="claim-reject-note">拒绝原因（选填）</Label>
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
              disabled={decideMut.isPending}
              onClick={() => void onReject()}
            >
              {decideMut.isPending ? '处理中…' : '确认拒绝'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
