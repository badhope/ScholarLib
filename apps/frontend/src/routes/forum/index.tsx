import { useState } from 'react'
import { createFileRoute, Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Clock3, Flame, Flag, Lock, Megaphone, MessageSquare, Pin, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { uploadForumImage } from '@/lib/forum'
import { extractError } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { MarkdownEditor } from '@/components/common/markdown-editor'
import { MarkdownExcerpt } from '@/components/common/markdown-content'
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
  board_id: number | null
  board_slug: string | null
  board_name: string | null
  board_path: string | null
  is_pinned: boolean
  is_locked: boolean
  reply_count: number
  created_at: string
  last_reply_at: string | null
  paper_id: number | null
  author: { id: number; username: string; display_name?: string | null; avatar_url?: string | null } | null
}

interface BoardNode {
  id: number
  parent_id: number | null
  slug: string
  name: string
  description: string | null
  topics: number
  total_topics: number
  last_active: string | null
  children: BoardNode[]
}

/** 旧分类到新版块 slug 的兼容映射：老链接和旧客户端不 404。 */
const LEGACY_SLUG: Record<string, string> = {
  discussion: 'paper',
  question: 'method',
  notice: 'meta',
  suggestion: 'feedback',
}

function collectBoards(nodes: BoardNode[], depth = 0): Array<BoardNode & { depth: number; path: string }> {
  return nodes.flatMap((node) => [
    { ...node, depth, path: `${'　'.repeat(depth)}${depth ? '└ ' : ''}${node.name}` },
    ...collectBoards(node.children, depth + 1),
  ])
}

function findRoot(nodes: BoardNode[], slug: string): BoardNode | null {
  for (const node of nodes) {
    if (node.slug === slug) return node
    const child = findRoot(node.children, slug)
    if (child) return node
  }
  return null
}

const CATEGORY_STYLE: Record<string, string> = {
  paper: 'bg-muted text-foreground border-border',
  method: 'bg-muted text-foreground border-border',
  life: 'bg-muted text-foreground border-border',
  collab: 'bg-muted text-foreground border-border',
  meta: 'border-primary/25 bg-primary/10 text-primary',
  notice: 'border-primary/25 bg-primary/10 text-primary',
  discussion: 'bg-muted text-foreground border-border',
  question: 'bg-muted text-foreground border-border',
  suggestion: 'bg-muted text-foreground border-border',
}

const CATEGORY_LABEL: Record<string, string> = {
  paper: '论文沙龙',
  method: '方法与写作',
  life: '学术生存',
  collab: '组队招募',
  meta: '站务公告',
  notice: '公告',
  discussion: '讨论',
  question: '求助',
  suggestion: '建议',
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
  const search = useSearch({ strict: false }) as {
    category?: string
    page?: number
    paperId?: number | string
    paperTitle?: string
    sort?: string
  }
  const category = search.category ?? 'all'
  const page = search.page ?? 1
  const sort = search.sort === 'hot' ? 'hot' : 'latest'

  const paperId = search.paperId ? Number(search.paperId) : null
  const paperTitle = search.paperTitle ?? ''

  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    title: paperId ? `讨论：${(paperTitle || `论文 #${paperId}`).slice(0, 170)}` : '',
    body: paperId ? `论文链接：/catalog/${paperId}\n\n` : '',
    board_id: null as number | null,
    paper_id: paperId,
  })

  const boardsQ = useQuery({
    queryKey: ['forum', 'boards'],
    queryFn: async () => (await api.get('/forum/boards')).data,
  })
  const boardTree: BoardNode[] = boardsQ.data?.tree ?? []
  const allBoards = collectBoards(boardTree)
  const leafBoards = allBoards.filter((b) => b.children.length === 0)
  const defaultBoardId = leafBoards.find((b) => b.slug === 'paper-reading')?.id ?? leafBoards[0]?.id ?? null
  const normalizedCategory = LEGACY_SLUG[category] ?? category
  const activeRoot = normalizedCategory === 'all' ? null : findRoot(boardTree, normalizedCategory)
  const activeBoard = normalizedCategory === 'all' ? null : allBoards.find((b) => b.slug === normalizedCategory)

  const listQ = useQuery({
    queryKey: ['forum', 'topics', category, page, sort],
    queryFn: async () =>
      (
        await api.get('/forum/topics', {
          params: { category: category === 'all' ? undefined : category, page, page_size: 20, sort },
        })
      ).data,
  })

  const createMut = useMutation({
    mutationFn: async () => (await api.post('/forum/topics', form)).data,
    onSuccess: (data: ForumTopic) => {
      toast.success('已发布')
      void qc.invalidateQueries({ queryKey: ['forum'] })
      setOpen(false)
      setForm({ title: '', body: '', board_id: defaultBoardId, paper_id: null })
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

  const openComposer = () => {
    if (!isAuthenticated) {
      void navigate({ to: '/login' })
      return
    }
    setForm((prev) => ({ ...prev, board_id: prev.board_id ?? defaultBoardId }))
    setOpen(true)
  }

  const updateSearch = (patch: Record<string, unknown>) => {
    void navigate({ to: '/forum', search: { ...search, ...patch }, replace: true })
  }

  const topics: ForumTopic[] = listQ.data?.data ?? []
  const meta = listQ.data?.meta

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4">
      <PageHeader
        title="讨论"
        description="学术交流与站务反馈两大父板块，向下细分到论文精读、复现与数据、写作与投稿、统计与方法等子板块。发帖登录即可，不需要积分。"
        actions={
          <Button
            onClick={openComposer}
          >
            <Plus className="h-4 w-4" />
            发帖
          </Button>
        }
      />

      {paperId ? (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
            <span className="min-w-0">
              正在为论文
              <Link
                to="/catalog/$resourceId"
                params={{ resourceId: String(paperId) }}
                className="mx-1 font-medium text-primary hover:underline"
              >
                {paperTitle || `#${paperId}`}
              </Link>
              开一个讨论帖。
            </span>
            <Button
              size="sm"
              onClick={openComposer}
            >
              <Plus className="h-4 w-4" />
              写第一条
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="论坛父板块">
          <button
            type="button"
            role="tab"
            aria-selected={category === 'all'}
            onClick={() => updateSearch({ category: undefined, page: 1 })}
            className={cn(
              'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
              category === 'all'
                ? 'border-primary bg-primary text-primary-foreground'
                : 'bg-card hover:border-primary/30',
            )}
          >
            全部
            <span className="ml-1 text-[10px] opacity-70">{allBoards.find((b) => b.slug === 'academic')?.total_topics ?? 0} 学术 · {allBoards.find((b) => b.slug === 'site')?.total_topics ?? 0} 站务</span>
          </button>
          {boardTree.map((root) => (
            <button
              key={root.slug}
              type="button"
              role="tab"
              aria-selected={normalizedCategory === root.slug}
              onClick={() => updateSearch({ category: root.slug, page: 1 })}
              className={cn(
                'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                normalizedCategory === root.slug
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'bg-card hover:border-primary/30',
              )}
            >
              {root.name}
              <span className="ml-1 text-[10px] opacity-70">{root.total_topics} 帖</span>
            </button>
          ))}
        </div>

        {activeRoot ? (
          <div className="space-y-1.5 rounded-xl border bg-muted/30 p-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="px-1 text-[11px] font-medium text-muted-foreground">{activeRoot.name}</span>
              {activeRoot.children.map((child) => (
                <button
                  key={child.slug}
                  type="button"
                  onClick={() => updateSearch({ category: child.slug, page: 1 })}
                  className={cn(
                    'rounded-lg border px-2.5 py-1 text-left text-xs transition-colors',
                    normalizedCategory === child.slug
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'bg-background hover:border-primary/25',
                  )}
                >
                  {child.name}
                  <span className="ml-1 text-[10px] text-muted-foreground">{child.total_topics}</span>
                </button>
              ))}
            </div>
            {activeBoard && activeBoard.children.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 border-l-2 border-primary/20 pl-3">
                <span className="text-[10px] text-muted-foreground">子板块</span>
                {activeBoard.children.map((child) => (
                  <button
                    key={child.slug}
                    type="button"
                    onClick={() => updateSearch({ category: child.slug, page: 1 })}
                    className="inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-0.5 text-[11px] hover:border-primary/40 hover:text-primary"
                  >
                    <ChevronRight className="h-3 w-3" aria-hidden="true" />
                    {child.name}
                    <span className="text-[10px] text-muted-foreground">{child.total_topics}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {category === 'all' ? (
          <span className="text-xs text-muted-foreground">
            {normalizedCategory === 'all' ? '全部板块' : activeBoard?.name ?? '当前板块'}，{sort === 'hot' ? '按回复数排' : '按最近活跃排'}
          </span>
        ) : (
          <button
            type="button"
            onClick={() => updateSearch({ category: undefined, page: 1 })}
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            ← 看全部版块
          </button>
        )}
        <div className="flex items-center gap-0.5 rounded-full border bg-muted/40 p-0.5">
          <button
            type="button"
            onClick={() => updateSearch({ sort: 'latest', page: 1 })}
            className={cn(
              'flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition-colors',
              sort === 'latest'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Clock3 className="h-3 w-3" />
            最新
          </button>
          <button
            type="button"
            onClick={() => updateSearch({ sort: 'hot', page: 1 })}
            className={cn(
              'flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition-colors',
              sort === 'hot'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Flame className="h-3 w-3" />
            热度
          </button>
        </div>
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
              onClick={openComposer}
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
                'group gap-0 rounded-xl p-0 transition-all',
                'hover:-translate-y-0.5 hover:border-primary/20 hover:shadow-sm',
                // 编辑部公告用左侧主色条突出：公告不是普通帖子
                t.category === 'notice' && 'border-l-4 border-l-primary',
              )}
            >
              <CardContent className="flex items-start gap-3 px-4 py-3.5">
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
                        {t.board_name ?? CATEGORY_LABEL[t.category] ?? t.category}
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
                      className="text-[15px] font-semibold leading-6 hover:text-primary hover:underline"
                    >
                      {t.title}
                    </Link>
                  </div>
                  <MarkdownExcerpt
                    text={t.body}
                    className="mt-1 line-clamp-2 text-[13px] leading-6 text-muted-foreground"
                  />
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    {t.author?.display_name || t.author?.username || '已注销用户'} · 最后活跃{' '}
                    {fmtRelative(t.last_reply_at ?? t.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1 rounded-full bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
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
              <Label htmlFor="t-board">版块</Label>
              <Select
                value={form.board_id ? String(form.board_id) : ''}
                onValueChange={(v) => setForm((p) => ({ ...p, board_id: Number(v) }))}
              >
                <SelectTrigger id="t-board">
                  <SelectValue placeholder="选择最具体的子板块" />
                </SelectTrigger>
                <SelectContent>
                  {leafBoards.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>
                      {b.path}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-muted-foreground">
                发到叶子板块，父板块会自动汇总；已选：{allBoards.find((b) => b.id === form.board_id)?.name ?? '未选择'}
              </p>
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
                onUploadImage={uploadForumImage}
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
              disabled={createMut.isPending || !form.board_id || form.title.trim().length < 2 || form.body.trim().length < 2}
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
