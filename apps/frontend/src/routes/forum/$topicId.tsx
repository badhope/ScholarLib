import { useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Lock, MessageSquare, Pin, Send, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/forum/$topicId')({
  component: ForumTopicPage,
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

interface ForumReply {
  id: number
  topic_id: number
  body: string
  created_at: string
  author: { id: number; username: string } | null
}

const CATEGORY_LABEL: Record<string, string> = {
  discussion: '讨论',
  suggestion: '建议',
  question: '求助',
  notice: '公告',
}

function ForumTopicPage() {
  const { topicId } = Route.useParams()
  const id = Number(topicId)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAuthenticated, user, isAdmin } = useAuth()
  const [reply, setReply] = useState('')

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
    mutationFn: async () => (await api.post(`/forum/topics/${id}/replies`, { body: reply })).data,
    onSuccess: () => {
      setReply('')
      void qc.invalidateQueries({ queryKey: ['forum'] })
      toast.success('已回复')
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

  if (topicQ.isLoading) return <Loading />
  if (topicQ.isError || !topicQ.data) {
    return <ErrorState message="帖子不存在或已被删除" onRetry={() => topicQ.refetch()} />
  }
  const topic = topicQ.data
  const canDelete = isAuthenticated && (isAdmin || topic.author?.id === user?.id)

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-8 sm:px-6">
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
          <h1 className="text-xl font-semibold">{topic.title}</h1>
          <p className="text-[11px] text-muted-foreground">
            {topic.author?.username ?? '已注销用户'} ·{' '}
            {new Date(topic.created_at).toLocaleString('zh-CN')}
          </p>
          <div className="whitespace-pre-wrap text-sm leading-relaxed">{topic.body}</div>
          {canDelete && (
            <div className="border-t pt-3">
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                onClick={() => {
                  if (window.confirm('确定删除这个帖子？')) deleteMut.mutate()
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除帖子
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-2">
        <p className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
          <MessageSquare className="h-4 w-4" />
          回复（{repliesQ.data?.length ?? 0}）
        </p>
        {repliesQ.isLoading ? (
          <Loading />
        ) : !repliesQ.data?.length ? (
          <EmptyState title="还没有回复" description="你可以是第一个回应的人。" />
        ) : (
          repliesQ.data.map((r) => (
            <Card key={r.id}>
              <CardContent className="py-3">
                <p className="text-[11px] text-muted-foreground">
                  {r.author?.username ?? '已注销用户'} ·{' '}
                  {new Date(r.created_at).toLocaleString('zh-CN')}
                </p>
                <div className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed">{r.body}</div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {topic.is_locked ? (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          该帖已锁定，不再接受新回复。
        </p>
      ) : (
        <Card>
          <CardContent className="space-y-2 py-4">
            {isAuthenticated ? (
              <>
                <Textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  rows={4}
                  placeholder="写下你的回应…"
                />
                <Button
                  onClick={() => replyMut.mutate()}
                  disabled={replyMut.isPending || reply.trim().length < 1}
                >
                  <Send className="h-4 w-4" />
                  {replyMut.isPending ? '发送中…' : '回复'}
                </Button>
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
