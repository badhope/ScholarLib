import { useState } from 'react'
import { createFileRoute, Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Megaphone, MessageSquare, Pin, Plus, Lock, Flag } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { MarkdownEditor } from '@/components/common/markdown-editor'
import { Pagination } from '@/components/common/pagination'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/forum/')({
  component: ForumListPage,
})

interface ForumTopic {
  id: number
  title: string
  body: string
  category: string
  is_pinned: boolean
  is_locked: boolean
  reply_count: number
  created_at: string
  last_reply_at: string | null
  author: { id: number; username: string } | null
}

const CATEGORIES = [
  { value: 'all', label: '全部' },
  { value: 'discussion', label: '讨论' },
  { value: 'suggestion', label: '建议' },
  { value: 'question', label: '求助' },
  { value: 'notice', label: '公告' },
]

const CATEGORY_STYLE: Record<string, string> = {
  discussion: 'bg-sky-500/10 text-sky-700 border-sky-300',
  suggestion: 'bg-violet-500/10 text-violet-700 border-violet-300',
  question: 'bg-amber-500/10 text-amber-700 border-amber-300',
  notice: 'bg-rose-500/10 text-rose-700 border-rose-300',
}

const CATEGORY_LABEL: Record<string, string> = {
  discussion: '讨论',
  suggestion: '建议',
  question: '求助',
  notice: '公告',
}

/** 相对时间：讨论列表的活跃信号比绝对时间更直观。 */
function fmtRelative(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const minutes = Math.floor((Date.now() - t) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

function ForumListPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAuthenticated } = useAuth()
  const search = useSearch({ strict: false }) as { category?: string; page?: number }
  const category = search.category ?? 'all'
  const page = search.page ?? 1

  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', body: '', category: 'discussion' })

  const listQ = useQuery({
    queryKey: ['forum', 'topics', category, page],
    queryFn: async () =>
      (
        await api.get('/forum/topics', {
          params: { category: category === 'all' ? undefined : category, page, page_size: 20 },
        })
      ).data,
  })

  const createMut = useMutation({
    mutationFn: async () => (await api.post('/forum/topics', form)).data,
    onSuccess: (data: ForumTopic) => {
      toast.success('已发布')
      void qc.invalidateQueries({ queryKey: ['forum'] })
      setOpen(false)
      setForm({ title: '', body: '', category: 'discussion' })
      void navigate({ to: '/forum/$topicId', params: { topicId: String(data.id) } })
    },
    onError: (err) => toast.error(extractError(err, '发布失败')),
  })

  const reportMut = useMutation({
    mutationFn: async (target: { topic_id: number; reason?: string }) =>
      (await api.post('/forum/reports', target)).data,
    onSuccess: () => toast.success('已举报，版主会尽快处理'),
    onError: (err) => toast.error(extractError(err, '举报失败')),
  })

  const updateSearch = (patch: Record<string, unknown>) => {
    void navigate({ to: '/forum', search: { ...search, ...patch }, replace: true })
  }

  const topics: ForumTopic[] = listQ.data?.data ?? []
  const meta = listQ.data?.meta

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-8 sm:px-6">
      <PageHeader
        title="讨论区"
        description="提建议、报问题、聊选题、找合作。发帖登录即可，不需要任何积分。"
        actions={
          <Button
            onClick={() => (isAuthenticated ? setOpen(true) : void navigate({ to: '/login' }))}
          >
            <Plus className="h-4 w-4" />
            发帖
          </Button>
        }
      />

      <div className="flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => updateSearch({ category: c.value === 'all' ? undefined : c.value, page: 1 })}
            className={cn(
              'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
              category === c.value
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-input bg-card hover:bg-muted/60',
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {listQ.isLoading ? (
        <Loading />
      ) : listQ.isError ? (
        <ErrorState message="加载讨论失败" onRetry={() => listQ.refetch()} />
      ) : topics.length === 0 ? (
        <EmptyState
          title="还没有人发帖"
          description="第一个帖子可以是你：问一个问题，或提一条建议。"
          action={
            <Button
              size="sm"
              onClick={() => (isAuthenticated ? setOpen(true) : void navigate({ to: '/login' }))}
            >
              发第一个帖
            </Button>
          }
        />
      ) : (
        <div className="space-y-2">
          {topics.map((t) => (
            <Card
              key={t.id}
              className={cn(
                'transition-colors hover:bg-muted/30',
                // 编辑部公告用左侧主色条突出：公告不是普通帖子
                t.category === 'notice' && 'border-l-4 border-l-primary',
              )}
            >
              <CardContent className="flex items-start gap-3 py-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {t.is_pinned && (
                      <Badge className="gap-1 bg-primary/15 text-primary">
                        <Pin className="h-3 w-3" />
                        置顶
                      </Badge>
                    )}
                    {t.category === 'notice' ? (
                      <Badge className="gap-1 border border-transparent bg-primary text-primary-foreground">
                        <Megaphone className="h-3 w-3" />
                        编辑部公告
                      </Badge>
                    ) : (
                      <Badge variant="outline" className={CATEGORY_STYLE[t.category]}>
                        {CATEGORY_LABEL[t.category] ?? t.category}
                      </Badge>
                    )}
                    {t.is_locked && (
                      <Badge variant="secondary" className="gap-1">
                        <Lock className="h-3 w-3" />
                        已锁定
                      </Badge>
                    )}
                    <Link
                      to="/forum/$topicId"
                      params={{ topicId: String(t.id) }}
                      className="text-base font-medium hover:text-primary hover:underline"
                    >
                      {t.title}
                    </Link>
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{t.body}</p>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    {t.author?.username ?? '已注销用户'} · 最后活跃{' '}
                    {fmtRelative(t.last_reply_at ?? t.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span className="tabular-nums">{t.reply_count}</span>
                </div>
                {isAuthenticated && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground"
                        aria-label="举报"
                      >
                        <Flag className="h-3.5 w-3.5" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {['垃圾广告', '不友善内容', '违法违规', '其他'].map((reason) => (
                        <DropdownMenuItem
                          key={reason}
                          onClick={() => reportMut.mutate({ topic_id: t.id, reason })}
                        >
                          {reason}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {meta && meta.total_pages > 1 && (
        <Pagination
          page={meta.page}
          totalPages={meta.total_pages}
          onPageChange={(p) => updateSearch({ page: p })}
        />
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>发新帖</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="t-category">分类</Label>
              <Select
                value={form.category}
                onValueChange={(v) => setForm((p) => ({ ...p, category: v }))}
              >
                <SelectTrigger id="t-category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.filter((c) => c.value !== 'all').map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="t-title">标题</Label>
              <Input
                id="t-title"
                value={form.title}
                onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                maxLength={200}
                placeholder="一句话说清你要讨论什么"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="t-body">内容</Label>
              <MarkdownEditor
                value={form.body}
                onChange={(body) => setForm((p) => ({ ...p, body }))}
                minHeight={180}
                placeholder="支持 Markdown。说清背景、你的判断、以及希望得到什么回应。"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending || form.title.trim().length < 2 || form.body.trim().length < 2}
            >
              {createMut.isPending ? '发布中…' : '发布'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export { CATEGORY_LABEL, CATEGORY_STYLE }
