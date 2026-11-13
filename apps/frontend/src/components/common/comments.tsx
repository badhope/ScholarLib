import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Loader2, MessageSquare, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import {
  useComments,
  useCreateComment,
  useDeleteComment,
} from '@/hooks/api/use-comments'
import { useAuth } from '@/hooks/use-auth'
import { formatDateTime } from '@/lib/utils'
import { EmptyState } from '@/components/common/state'

// 超过 160 字的评论默认折叠，展开/收起切换。
function LongText({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 160
  if (!long) {
    return <p className="mt-1.5 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">{text}</p>
  }
  return (
    <div>
      <p
        className={
          'mt-1.5 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90 ' +
          (open ? '' : 'line-clamp-3')
        }
      >
        {text}
      </p>
      <button
        onClick={() => setOpen((v) => !v)}
        className="mt-1 text-xs text-primary hover:underline"
      >
        {open ? '收起' : '展开全文'}
      </button>
    </div>
  )
}

// 读者评论区：游客可见可读，登录后可发言；不可编辑（时间线保持诚实），
// 可删自己的评论，管理员可删任何评论（审计留痕）。
export function Comments({ resourceId }: { resourceId: number }) {
  const { isAuthenticated } = useAuth()
  const [page, setPage] = useState(1)
  const [draft, setDraft] = useState('')
  const { data, isLoading, isError, refetch } = useComments(resourceId, page)
  const createMut = useCreateComment(resourceId)
  const deleteMut = useDeleteComment(resourceId)
  const { user } = useAuth()

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const body = draft.trim()
    if (!body) return
    try {
      await createMut.mutateAsync(body)
      setDraft('')
      setPage(1)
      toast.success('评论已发布')
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status
      if (status === 401) {
        toast.error('登录状态已过期，请重新登录')
      } else {
        toast.error('发布失败，稍后再试')
      }
    }
  }

  const onDelete = async (id: number) => {
    try {
      await deleteMut.mutateAsync(id)
      toast.success('已删除')
    } catch {
      toast.error('删除失败')
    }
  }

  const total = data?.meta.total ?? 0

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4 text-primary" />
          读者评论
          {total > 0 && (
            <span className="text-sm font-normal text-muted-foreground">（{total}）</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isAuthenticated ? (
          <form onSubmit={onSubmit} className="space-y-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="以读者的身份发言：问题、质疑、补充都欢迎（≤1000 字，发布后不可编辑）"
              rows={3}
              maxLength={1000}
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {draft.length}/1000 · 发布后不可编辑
              </span>
              <Button type="submit" size="sm" disabled={createMut.isPending || !draft.trim()}>
                {createMut.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                发布评论
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed bg-muted/30 px-4 py-3">
            <p className="text-sm text-muted-foreground">
              游客模式：可以阅读全部评论；登录后即可参与讨论。
            </p>
            <Button asChild size="sm" variant="outline">
              <Link to="/login" search={{ redirect: `/catalog/${resourceId}` }}>
                登录参与
              </Link>
            </Button>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-3 py-2" aria-hidden>
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="animate-pulse space-y-1.5 rounded-lg border p-3">
                <div className="h-3 w-28 rounded bg-muted" />
                <div className="h-3 w-full rounded bg-muted" />
              </div>
            ))}
          </div>
        ) : isError ? (
          <p className="py-2 text-sm text-muted-foreground">
            评论加载失败，
            <button className="text-primary hover:underline" onClick={() => refetch()}>
              重试
            </button>
          </p>
        ) : total === 0 ? (
          <EmptyState title="还没有评论" description="第一条评论的位置留给你。" />
        ) : (
          <ul className="space-y-3">
            {data!.data.map((c) => {
              const mine = user?.id === c.user_id
              return (
                <li key={c.id} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {c.author_avatar_url ? (
                        <img src={c.author_avatar_url} alt="" className="h-5 w-5 rounded-full object-cover" />
                      ) : null}
                      <p className="text-sm font-medium">{c.author_name}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <time className="text-xs text-muted-foreground">
                        {formatDateTime(c.created_at)}
                      </time>
                      {(mine || user?.is_admin) && (
                        <button
                          onClick={() => onDelete(c.id)}
                          disabled={deleteMut.isPending}
                          aria-label="删除评论"
                          className="text-muted-foreground transition-colors hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                  <LongText text={c.body} />
                </li>
              )
            })}
          </ul>
        )}

        {data && data.meta.total_pages > 1 && (
          <div className="flex items-center justify-between text-sm">
            <Button
              variant="ghost"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </Button>
            <span className="text-xs text-muted-foreground">
              第 {data.meta.page} / {data.meta.total_pages} 页
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={page >= data.meta.total_pages}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
