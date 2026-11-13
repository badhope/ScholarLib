import { useMemo, useRef, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Bookmark,
  Flag,
  HeartHandshake,
  Lock,
  MessageSquare,
  Pin,
  Reply,
  Send,
  Share2,
  ThumbsUp,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { uploadForumImage } from '@/lib/forum'
import { extractError } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { MarkdownEditor } from '@/components/common/markdown-editor'
import { MarkdownContent } from '@/components/common/markdown-content'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/forum/$topicId')({
  component: ForumTopicPage,
})

type ReactionKind = 'agree' | 'helpful' | 'bookmark'

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
  author: { id: number; username: string; display_name?: string | null; avatar_url?: string | null } | null
  reactions?: Record<string, number>
  viewer_reactions?: string[]
}

interface ForumReply {
  id: number
  topic_id: number
  parent_id: number | null
  body: string
  created_at: string
  author: { id: number; username: string; display_name?: string | null; avatar_url?: string | null } | null
  reactions?: Record<string, number>
  viewer_reactions?: string[]
}

const CATEGORY_LABEL: Record<string, string> = {
  paper: '论文沙龙',
  method: '方法与写作',
  life: '学术生存',
  collab: '组队招募',
  meta: '站务公告',
  discussion: '讨论',
  suggestion: '建议',
  question: '求助',
  notice: '公告',
}

const REACTIONS: {
  kind: ReactionKind
  label: string
  icon: typeof ThumbsUp
}[] = [
  { kind: 'agree', label: '赞同', icon: ThumbsUp },
  { kind: 'helpful', label: '有帮助', icon: HeartHandshake },
  { kind: 'bookmark', label: '收藏', icon: Bookmark },
]

const REPORT_REASONS = ['垃圾广告', '不友善内容', '违法违规', '其他']

function ReactionBar({
  targetType,
  targetId,
  reactions,
  viewer,
}: {
  targetType: 'topic' | 'reply'
  targetId: number
  reactions?: Record<string, number>
  viewer?: string[]
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()
  const mut = useMutation({
    mutationFn: async (kind: ReactionKind) =>
      (await api.post('/forum/reactions/toggle', { target_type: targetType, target_id: targetId, kind }))
        .data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['forum'] })
    },
    onError: (err) => toast.error(extractError(err, '操作失败')),
  })

  return (
    <div className="flex flex-wrap items-center gap-1">
      {REACTIONS.map(({ kind, label, icon: Icon }) => {
        const active = viewer?.includes(kind) ?? false
        const count = reactions?.[kind] ?? 0
        return (
          <Button
            key={kind}
            type="button"
            size="sm"
            variant={active ? 'secondary' : 'ghost'}
            aria-pressed={active}
            disabled={mut.isPending}
            onClick={() => {
              if (!isAuthenticated) {
                void navigate({ to: '/login' })
                return
              }
              mut.mutate(kind)
            }}
            className={cn(
              'h-7 gap-1 rounded-full px-2 text-[11px]',
              active ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
            {count > 0 && <span className="tabular-nums">{count}</span>}
          </Button>
        )
      })}
    </div>
  )
}

function ReplyCard({
  reply,
  isRoot,
  parentAuthor,
  topicAuthorId,
  canReply,
  onReply,
  onReport,
}: {
  reply: ForumReply
  isRoot: boolean
  parentAuthor?: string
  topicAuthorId?: number
  canReply: boolean
  onReply: (reply: ForumReply) => void
  onReport: (target: { reply_id: number; reason: string }) => void
}) {
  const { isAuthenticated, user } = useAuth()
  const isTopicAuthor = reply.author?.id !== undefined && reply.author.id === topicAuthorId
  const own = reply.author?.id === user?.id

  return (
    <Card
      id={`reply-${reply.id}`}
      className={cn(
        'scroll-mt-24',
        isRoot ? '' : 'ml-4 border-l-2 border-l-primary/20 sm:ml-8',
      )}
    >
      <CardContent className="space-y-2 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            {!isRoot && parentAuthor && (
              <p className="mb-0.5 text-[11px] text-muted-foreground">
                回复 @{parentAuthor}
              </p>
            )}
            <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              {reply.author?.avatar_url ? (
                <img src={reply.author.avatar_url} alt="" className="h-5 w-5 rounded-full object-cover" />
              ) : null}
              <span className="font-medium text-foreground">
                {reply.author?.display_name || reply.author?.username || '已注销用户'}
              </span>
              {isTopicAuthor && (
                <Badge variant="outline" className="h-4 px-1 text-[10px]">
                  楼主
                </Badge>
              )}
              <span>·</span>
              <span>{new Date(reply.created_at).toLocaleString('zh-CN')}</span>
            </p>
          </div>
          {isAuthenticated && !own && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0 text-muted-foreground"
                  aria-label="举报回复"
                >
                  <Flag className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {REPORT_REASONS.map((reason) => (
                  <DropdownMenuItem
                    key={reason}
                    onClick={() => onReport({ reply_id: reply.id, reason })}
                  >
                    {reason}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <MarkdownContent text={reply.body} className="text-sm leading-relaxed" />

        <div className="flex items-center gap-1 border-t pt-1.5">
          <ReactionBar
            targetType="reply"
            targetId={reply.id}
            reactions={reply.reactions}
            viewer={reply.viewer_reactions}
          />
          {canReply && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onReply(reply)}
              className="ml-auto h-7 gap-1 rounded-full px-2 text-[11px] text-muted-foreground"
            >
              <Reply className="h-3.5 w-3.5" />
              回复
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ForumTopicPage() {
  const { topicId } = Route.useParams()
  const id = Number(topicId)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAuthenticated, user, isAdmin } = useAuth()
  const [reply, setReply] = useState('')
  const [replyTo, setReplyTo] = useState<ForumReply | null>(null)
  const composerRef = useRef<HTMLDivElement | null>(null)

  const topicQ = useQuery<ForumTopic>({
    queryKey: ['forum', 'topic', id],
    queryFn: async () => (await api.get<ForumTopic>(`/forum/topics/${id}`)).data,
    enabled: id > 0,
  })

  const repliesQ = useQuery<ForumReply[]>({
    queryKey: ['forum', 'replies', id],
    queryFn: async () => (await api.get<ForumReply[]>(`/forum/topics/${id}/replies`)).data,
    enabled: id > 0,
  })

  const replyMut = useMutation({
    mutationFn: async () =>
      (
        await api.post(`/forum/topics/${id}/replies`, {
          body: reply,
          parent_id: replyTo ? (replyTo.parent_id ?? replyTo.id) : null,
        })
      ).data,
    onSuccess: () => {
      setReply('')
      setReplyTo(null)
      void qc.invalidateQueries({ queryKey: ['forum'] })
      toast.success(replyTo ? '已回复' : '已发表回复')
    },
    onError: (err) => toast.error(extractError(err, '回复失败')),
  })

  const deleteMut = useMutation({
    mutationFn: async () => (await api.delete(`/forum/topics/${id}`)).data,
    onSuccess: () => {
      toast.success('已删除')
      void qc.invalidateQueries({ queryKey: ['forum'] })
      void navigate({ to: '/forum' })
    },
    onError: (err) => toast.error(extractError(err, '删除失败')),
  })

  const reportMut = useMutation({
    mutationFn: async (target: { topic_id?: number; reply_id?: number; reason?: string }) =>
      (await api.post('/forum/reports', target)).data,
    onSuccess: () => toast.success('已举报，版主会尽快处理'),
    onError: (err) => toast.error(extractError(err, '举报失败')),
  })

  const threads = useMemo(() => {
    const roots = (repliesQ.data ?? []).filter((r) => !r.parent_id)
    const children = new Map<number, ForumReply[]>()
    for (const r of repliesQ.data ?? []) {
      if (!r.parent_id) continue
      const list = children.get(r.parent_id) ?? []
      list.push(r)
      children.set(r.parent_id, list)
    }
    return roots.map((root) => ({ root, children: children.get(root.id) ?? [] }))
  }, [repliesQ.data])

  const parentName = (replyItem: ForumReply) =>
    repliesQ.data?.find((r) => r.id === replyItem.parent_id)?.author?.username

  const startReply = (target: ForumReply) => {
    setReplyTo(target)
    requestAnimationFrame(() => composerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
  }

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      toast.success('链接已复制，可以发给同门或审稿人')
    } catch {
      toast.error('复制失败，请手动复制地址栏')
    }
  }

  if (topicQ.isLoading) return <Loading />
  if (topicQ.isError || !topicQ.data) {
    return <ErrorState message="帖子不存在或已被删除" onRetry={() => topicQ.refetch()} />
  }
  const topic = topicQ.data
  const canDelete = isAuthenticated && (isAdmin || topic.author?.id === user?.id)

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Link
        to="/forum"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        返回讨论区
      </Link>

      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex flex-wrap items-center gap-2">
            {topic.is_pinned && (
              <Badge className="gap-1 bg-primary/15 text-primary">
                <Pin className="h-3 w-3" />
                置顶
              </Badge>
            )}
            <Badge variant="outline">{CATEGORY_LABEL[topic.category] ?? topic.category}</Badge>
            {topic.is_locked && (
              <Badge variant="secondary" className="gap-1">
                <Lock className="h-3 w-3" />
                已锁定
              </Badge>
            )}
          </div>
          <h1 className="text-xl font-semibold leading-snug">{topic.title}</h1>
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {topic.author?.avatar_url ? (
              <img src={topic.author.avatar_url} alt="" className="h-5 w-5 rounded-full object-cover" />
            ) : null}
            {topic.author?.display_name || topic.author?.username || '已注销用户'} ·{' '}
            {new Date(topic.created_at).toLocaleString('zh-CN')}
          </p>
          {/* 主楼按 Markdown 渲染；react-markdown 默认转义原始 HTML，XSS 面为零。 */}
          <div className="markdown-body text-sm leading-relaxed">
            <MarkdownContent text={topic.body} />
          </div>

          <div className="flex flex-wrap items-center gap-1 border-t pt-2">
            <ReactionBar
              targetType="topic"
              targetId={topic.id}
              reactions={topic.reactions}
              viewer={topic.viewer_reactions}
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => void share()}
              className="h-7 gap-1 rounded-full px-2 text-[11px] text-muted-foreground"
            >
              <Share2 className="h-3.5 w-3.5" />
              分享
            </Button>
            {canDelete && (
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto h-7 gap-1 px-2 text-[11px] text-destructive"
                onClick={() => {
                  if (window.confirm('确定删除这个帖子？')) deleteMut.mutate()
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除帖子
              </Button>
            )}
            {isAuthenticated && !canDelete && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto h-7 gap-1 px-2 text-[11px] text-muted-foreground"
                  >
                    <Flag className="h-3.5 w-3.5" />
                    举报
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {REPORT_REASONS.map((reason) => (
                    <DropdownMenuItem
                      key={reason}
                      onClick={() => reportMut.mutate({ topic_id: id, reason })}
                    >
                      {reason}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-2">
        <p className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
          <MessageSquare className="h-4 w-4" />
          回复（{topic.reply_count}）
        </p>
        {repliesQ.isLoading ? (
          <Loading />
        ) : !repliesQ.data?.length ? (
          <EmptyState title="还没有回复" description="你可以是第一个回应的人。" />
        ) : (
          <div className="space-y-3">
            {threads.map(({ root, children }) => (
              <div key={root.id} className="space-y-2">
                <ReplyCard
                  reply={root}
                  isRoot
                  parentAuthor={parentName(root)}
                  topicAuthorId={topic.author?.id}
                  canReply={isAuthenticated && !topic.is_locked}
                  onReply={startReply}
                  onReport={(target) => reportMut.mutate(target)}
                />
                {children.length > 0 && (
                  <div className="space-y-2">
                    {children.map((child) => (
                      <ReplyCard
                        key={child.id}
                        reply={child}
                        isRoot={false}
                        parentAuthor={parentName(child)}
                        topicAuthorId={topic.author?.id}
                        canReply={isAuthenticated && !topic.is_locked}
                        onReply={startReply}
                        onReport={(target) => reportMut.mutate(target)}
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {topic.is_locked ? (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          该帖已锁定，不再接受新回复。
        </p>
      ) : (
        <Card ref={composerRef}>
          <CardContent className="space-y-2 py-4">
            {isAuthenticated ? (
              <>
                {replyTo && (
                  <div className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-2.5 py-1.5 text-xs">
                    <span className="min-w-0 truncate text-muted-foreground">
                      正在回复 <span className="font-medium text-foreground">@{replyTo.author?.username ?? '已注销用户'}</span>
                    </span>
                    <button
                      type="button"
                      className="shrink-0 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                      onClick={() => setReplyTo(null)}
                    >
                      取消
                    </button>
                  </div>
                )}
                <MarkdownEditor
                  value={reply}
                  onChange={setReply}
                  onUploadImage={uploadForumImage}
                  minHeight={160}
                  placeholder={
                    replyTo
                      ? `回复 @${replyTo.author?.username ?? '对方'}：说清你同意哪一点、补充什么证据。`
                      : '写下你的回应…（支持 Markdown、表情和站内表情包）'
                  }
                />
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground">
                    登录即可回复；请针对内容，不针对人。
                  </span>
                  <Button
                    onClick={() => replyMut.mutate()}
                    disabled={replyMut.isPending || reply.trim().length < 1}
                  >
                    <Send className="h-4 w-4" />
                    {replyMut.isPending ? '发送中…' : replyTo ? '回复' : '发表回复'}
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                <Link to="/login" className="text-primary hover:underline">
                  登录
                </Link>{' '}
                后可以回复。
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
