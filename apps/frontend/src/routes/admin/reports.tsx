import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, ShieldAlert, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import { requireAdminGuard } from '@/lib/route-guards'
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
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/admin/reports')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminReportsPage,
})

type ReportStatus = 'open' | 'resolved' | 'rejected'
type ReportAction = 'dismiss' | 'remove_content' | 'suspend_author'

interface ForumReportRow {
  id: number
  topic_id: number | null
  reply_id: number | null
  reason: string
  status: ReportStatus
  created_at: string
  resolved_at: string | null
  target_type: 'topic' | 'reply' | null
  target_excerpt: string | null
  target_author: { id: number; username: string; display_name?: string | null } | null
  reporter: { id: number; username: string; display_name?: string | null } | null
}

const TABS: { value: ReportStatus; label: string }[] = [
  { value: 'open', label: '待处理' },
  { value: 'resolved', label: '已处理' },
  { value: 'rejected', label: '已驳回' },
]

const ACTION_LABEL: Record<ReportAction, string> = {
  dismiss: '驳回举报',
  remove_content: '移除内容',
  suspend_author: '移除内容并停用作者',
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

function AdminReportsPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<ReportStatus>('open')
  const [target, setTarget] = useState<{ row: ForumReportRow; action: ReportAction } | null>(null)
  const [note, setNote] = useState('')

  const listQ = useQuery({
    queryKey: ['forum', 'reports', tab],
    queryFn: async () =>
      (
        await api.get('/forum/reports', {
          params: { status_filter: tab },
        })
      ).data as ForumReportRow[],
  })

  const handleMut = useMutation({
    mutationFn: async (payload: { id: number; action: ReportAction; note?: string }) =>
      (await api.patch(`/forum/reports/${payload.id}`, payload)).data,
    onSuccess: () => {
      toast.success('举报已处理')
      setTarget(null)
      setNote('')
      void qc.invalidateQueries({ queryKey: ['forum'] })
    },
    onError: (err) => toast.error(extractError(err, '处理失败')),
  })

  const rows = listQ.data ?? []

  return (
    <div>
      <PageHeader
        title="举报处置"
        description="统一查看帖子/回复举报；移除内容走软删除，停用作者会立即让登录态失效。所有动作写入审计日志。"
      />

      <Tabs
        value={tab}
        onValueChange={(v) => {
          setTab(v as ReportStatus)
        }}
        className="mb-4"
      >
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {listQ.isLoading ? (
        <Loading />
      ) : listQ.isError ? (
        <ErrorState message="加载举报失败" onRetry={() => listQ.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={tab === 'open' ? '没有待处理举报' : '这一栏还是空的'}
          description={tab === 'open' ? '社区安静是好事；有举报时会出现在这里。' : '处理过的举报会归档到这里。'}
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <Card key={row.id}>
              <CardContent className="space-y-2 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={row.status === 'open' ? 'destructive' : 'outline'}>
                    {TABS.find((t) => t.value === row.status)?.label ?? row.status}
                  </Badge>
                  <Badge variant="secondary">{row.target_type === 'reply' ? '回帖' : '帖子'}</Badge>
                  <span className="text-xs text-muted-foreground">
                    举报人：{row.reporter?.display_name || row.reporter?.username || '已注销'}
                  </span>
                  <span className="text-xs text-muted-foreground">{fmtTime(row.created_at)}</span>
                </div>
                <p className="text-sm">
                  <span className="text-muted-foreground">原因：</span>
                  {row.reason || '未填写'}
                </p>
                <blockquote className="rounded-lg border-l-2 border-primary/30 bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                  {row.target_excerpt || '目标内容已不可读'}
                </blockquote>
                <p className="text-xs text-muted-foreground">
                  内容作者：{row.target_author?.display_name || row.target_author?.username || '未知'}
                  {row.resolved_at ? ` · 处理于 ${fmtTime(row.resolved_at)}` : ''}
                </p>
                {row.status === 'open' ? (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleMut.mutate({ id: row.id, action: 'dismiss' })}
                      disabled={handleMut.isPending}
                    >
                      <Check className="h-3.5 w-3.5" />
                      驳回
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setTarget({ row, action: 'remove_content' })}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      移除内容
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => setTarget({ row, action: 'suspend_author' })}
                    >
                      <Ban className="h-3.5 w-3.5" />
                      停用作者
                    </Button>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={Boolean(target)} onOpenChange={(v) => !v && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" />
              {target ? ACTION_LABEL[target.action] : ''}
            </DialogTitle>
            <DialogDescription>
              {target?.action === 'suspend_author'
                ? '会软删被举报内容，并停用作者账号（现有登录态立即失效）。请确认举报属实。'
                : '会软删被举报内容，帖子/回复从列表和详情中隐藏。'}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="处理备注（写入审计日志，可选）"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>
              取消
            </Button>
            <Button
              variant={target?.action === 'suspend_author' ? 'destructive' : 'default'}
              onClick={() =>
                target &&
                handleMut.mutate({
                  id: target.row.id,
                  action: target.action,
                  note: note.trim() || undefined,
                })
              }
              disabled={handleMut.isPending}
            >
              {handleMut.isPending ? '处理中…' : '确认'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
