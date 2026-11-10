import { useState } from 'react'
import { createFileRoute, redirect } from '@tanstack/react-router'
import { CheckCircle2, MessageSquareText, Pin, RefreshCw } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/use-auth'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import { MarkdownField } from '@/components/common/markdown-field'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/feedback')({
  // 反馈墙已并入论坛「站务公告」版块；旧入口跳转过去，保留书签可达。
  beforeLoad: () => {
    throw redirect({ to: '/forum', search: { category: 'meta' } })
  },
  component: FeedbackBoardPage,
})

interface FeedbackItem {
  id: number
  kind: string
  title: string
  body: string
  page_url: string
  status: 'open' | 'resolved'
  resolution_note: string | null
  resolved_at: string | null
  created_at: string | null
}

const KIND_LABELS: Record<string, string> = {
  bug: '页面/功能出错',
  suggestion: '功能建议',
  content: '内容问题',
  submission: '投稿咨询',
}

type StatusTab = 'all' | 'open' | 'resolved'

function formatDate(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
}

function FeedbackBoardPage() {
  const [status, setStatus] = useState<StatusTab>('all')
  const [target, setTarget] = useState<FeedbackItem | null>(null)
  const [note, setNote] = useState('')
  const { isAdmin } = useAuth()
  const qc = useQueryClient()

  const query = useQuery<{ data: FeedbackItem[]; open_count: number; resolved_count: number }>({
    queryKey: ['feedback-board', status],
    queryFn: async () =>
      (await api.get('/catalog/feedback/board', {
        params: status === 'all' ? {} : { status },
      })).data,
  })

  const resolve = useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      (await api.post(`/catalog/feedback/${id}/resolve`, { note })).data,
    onSuccess: () => {
      toast.success('已标记为已解决')
      setTarget(null)
      setNote('')
      void qc.invalidateQueries({ queryKey: ['feedback-board'] })
    },
    onError: (err) => toast.error(extractError(err, '操作失败')),
  })

  const items = query.data?.data ?? []
  const openCount = query.data?.open_count ?? 0
  const resolvedCount = query.data?.resolved_count ?? 0

  return (
    <div>
      <PageHeader
        title="反馈墙"
        description="大家提过的问题都集中在这里；编辑部处理后会标成「已解决」。"
        actions={
          <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
            <RefreshCw className={query.isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
            刷新
          </Button>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-2 sm:flex">
        <Card>
          <CardContent className="py-3">
            <p className="text-xs text-muted-foreground">待处理</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{openCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <p className="text-xs text-muted-foreground">已解决</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-emerald-600">{resolvedCount}</p>
          </CardContent>
        </Card>
      </div>

      <Tabs
        value={status}
        onValueChange={(v) => setStatus(v as StatusTab)}
      >
        <div className="overflow-x-auto pb-1">
          <TabsList className="w-max">
            <TabsTrigger value="all">全部</TabsTrigger>
            <TabsTrigger value="open">待处理</TabsTrigger>
            <TabsTrigger value="resolved">已解决</TabsTrigger>
          </TabsList>
        </div>
      </Tabs>

      <div className="mt-4">
        {query.isLoading ? (
          <LoadingSkeleton rows={5} />
        ) : query.isError ? (
          <ErrorState message="加载反馈失败" onRetry={() => void query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={status === 'resolved' ? '还没有已解决的反馈' : '暂无反馈'}
            description="页面右下角「有问题」提交后，会出现在这里。"
          />
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <Card key={item.id} className={item.status === 'open' ? 'border-l-4 border-l-amber-500' : 'border-l-4 border-l-emerald-500'}>
                <CardContent className="py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={item.status === 'resolved' ? 'default' : 'secondary'} className={item.status === 'resolved' ? 'bg-emerald-600' : ''}>
                      {item.status === 'resolved' ? '已解决' : '待处理'}
                    </Badge>
                    <Badge variant="outline">{KIND_LABELS[item.kind] ?? item.kind}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {item.created_at ? formatDate(item.created_at) : ''}
                    </span>
                    {item.page_url ? (
                      <span className="ml-auto max-w-[45%] truncate text-xs text-muted-foreground" title={item.page_url}>
                        <Pin className="mr-0.5 inline h-3 w-3" />
                        {item.page_url}
                      </span>
                    ) : null}
                  </div>
                  <h2 className="mt-2 text-sm font-semibold leading-snug">{item.title}</h2>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-muted-foreground">
                    {item.body}
                  </p>
                  {item.status === 'resolved' && item.resolution_note ? (
                    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                      <span className="font-medium">编辑部说明：</span>
                      {item.resolution_note}
                    </div>
                  ) : null}
                  {isAdmin && item.status === 'open' ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-3"
                      onClick={() => {
                        setTarget(item)
                        setNote('')
                      }}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      标记已解决
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Dialog open={target !== null} onOpenChange={(open) => !open && setTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>标记为已解决</DialogTitle>
            <DialogDescription className="line-clamp-2">
              {target?.title}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              写清楚「哪一条反馈、做了什么、现在是什么状态」。这段会原样公开在反馈墙上，
              所以不要写提交人身份或内部链接。
            </p>
            <MarkdownField
              id="feedback-resolution-note"
              label="处理说明（公开）"
              value={note}
              onChange={setNote}
              maxLength={500}
              rows={4}
              template={`**处理结果**\n\n已修复/已调整：……\n\n**现在可以怎么验证**\n\n- 刷新页面后……\n- 如果仍然出现，请补充……`}
              placeholder="例如：已修复该页面报错，刷新后即可；如果仍复现，请附上浏览器与截图。"
              disabled={resolve.isPending}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setTarget(null)}>取消</Button>
            <Button
              onClick={() => {
                if (!target) return
                if (!note.trim()) {
                  toast.error('请先写处理说明：作者需要知道改了什么、怎么验证')
                  return
                }
                resolve.mutate({ id: target.id, note: note.trim() })
              }}
              disabled={resolve.isPending}
            >
              {resolve.isPending ? '提交中…' : '确认已解决'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <p className="mt-6 flex items-center gap-1.5 text-xs text-muted-foreground">
        <MessageSquareText className="h-3.5 w-3.5" />
        反馈默认公开标题和正文，不公开提交人身份。
      </p>
    </div>
  )
}
