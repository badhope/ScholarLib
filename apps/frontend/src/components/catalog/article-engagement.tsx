import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Bell, BookOpen, Heart, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { extractError } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useAuthorFollowStatus,
  useDisciplineSubscriptionStatus,
  useFollowAuthor,
  useReadingProgress,
  useRemoveFromHistory,
  useSubscribeDiscipline,
  useUnfollowAuthor,
  useUnsubscribeDiscipline,
  useUpdateProgress,
} from '@/hooks/api/use-modules'

/**
 * 文章详情右侧的轻量互动区：关注作者、订阅学科、记录阅读进度。
 * v5 把阅读页并进详情页时这三块 UI 曾一起丢失，这里按同一批 hook 补回，
 * 交互保持一屏内可完成，不抢正文的注意力。
 */
export function ArticleEngagement({
  resourceId,
  authors,
  discipline,
}: {
  resourceId: number
  authors: string[]
  discipline?: string
}) {
  const author = authors[0]?.trim() || ''
  const { data: follow } = useAuthorFollowStatus(author)
  const followMut = useFollowAuthor()
  const unfollowMut = useUnfollowAuthor()
  const { data: subscription } = useDisciplineSubscriptionStatus(discipline ?? '')
  const subscribeMut = useSubscribeDiscipline()
  const unsubscribeMut = useUnsubscribeDiscipline()

  const toggleFollow = async () => {
    if (!author) return
    try {
      if (follow?.following) {
        await unfollowMut.mutateAsync(author)
        toast.success(`已取消关注 ${author}`)
      } else {
        await followMut.mutateAsync(author)
        toast.success(`已关注 ${author}`)
      }
    } catch (err) {
      toast.error(extractError(err, '关注操作失败'))
    }
  }

  const toggleSubscribe = async () => {
    if (!discipline) return
    try {
      if (subscription?.subscribed) {
        await unsubscribeMut.mutateAsync(discipline)
        toast.success(`已取消订阅 ${discipline}`)
      } else {
        await subscribeMut.mutateAsync(discipline)
        toast.success(`已订阅 ${discipline}`)
      }
    } catch (err) {
      toast.error(extractError(err, '订阅操作失败'))
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Heart className="h-3.5 w-3.5 text-primary" />
          关注与进度
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {author && (
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="min-w-0 truncate text-muted-foreground">{author}</span>
            <Button
              variant={follow?.following ? 'secondary' : 'outline'}
              size="sm"
              className="shrink-0"
              disabled={followMut.isPending || unfollowMut.isPending}
              onClick={() => void toggleFollow()}
            >
              {follow?.following ? '已关注' : '关注'}
            </Button>
          </div>
        )}
        {discipline && (
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="min-w-0 truncate text-muted-foreground">{discipline}</span>
            <Button
              variant={subscription?.subscribed ? 'secondary' : 'outline'}
              size="sm"
              className="shrink-0"
              disabled={subscribeMut.isPending || unsubscribeMut.isPending}
              onClick={() => void toggleSubscribe()}
            >
              <Bell className="mr-1 h-3 w-3" />
              {subscription?.subscribed ? '已订阅' : '订阅'}
            </Button>
          </div>
        )}
        <ReadingProgressBlock resourceId={resourceId} />
      </CardContent>
    </Card>
  )
}

function ReadingProgressBlock({ resourceId }: { resourceId: number }) {
  const navigate = useNavigate()
  const { data: progress, isPending: isProgressLoading } = useReadingProgress(resourceId)
  const update = useUpdateProgress()
  const remove = useRemoveFromHistory()
  const [page, setPage] = useState('1')
  const [percent, setPercent] = useState(0)
  const loadedResourceRef = useRef<number | null>(null)

  useEffect(() => {
    if (isProgressLoading || loadedResourceRef.current === resourceId) return
    loadedResourceRef.current = resourceId
    setPage(String(progress?.page ?? 1))
    setPercent(Math.round(progress?.progress_percent ?? 0))
  }, [isProgressLoading, progress, resourceId])

  const save = async () => {
    try {
      await update.mutateAsync({
        resourceId,
        body: {
          page: Number(page) || 1,
          progress_percent: percent,
        },
      })
      toast.success('进度已保存')
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  const clear = async () => {
    try {
      await remove.mutateAsync(resourceId)
      toast.success('已从阅读历史移除')
      void navigate({ to: '/library' })
    } catch (err) {
      toast.error(extractError(err, '移除失败'))
    }
  }

  return (
    <div className="rounded-lg border bg-muted/25 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
        <BookOpen className="h-3.5 w-3.5 text-primary" />
        阅读进度
        {progress?.duration_sec != null && (
          <span className="ml-auto font-normal text-muted-foreground">
            {Math.max(0, Math.round(progress.duration_sec / 60))} 分钟
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[11px] text-muted-foreground">
          页码
          <Input
            aria-label="页码"
            className="mt-1 h-8"
            inputMode="numeric"
            value={page}
            onChange={(e) => setPage(e.target.value.replace(/[^\d]/g, ''))}
          />
        </label>
        <label className="text-[11px] text-muted-foreground">
          进度：{percent}%
          <input
            aria-label="进度"
            type="range"
            min={0}
            max={100}
            value={percent}
            onChange={(e) => setPercent(Number(e.target.value))}
            className="mt-3 h-2 w-full accent-primary"
          />
        </label>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button size="sm" className="flex-1" disabled={update.isPending} onClick={() => void save()}>
          保存进度
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          aria-label="移除阅读历史"
          disabled={remove.isPending}
          onClick={() => void clear()}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
