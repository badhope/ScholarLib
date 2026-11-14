import { useState } from 'react'
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { CheckCheck, ExternalLink, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  useDeleteNotification,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUnreadCount,
  type NotificationCategory,
} from '@/hooks/api/use-modules'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/notifications')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: NotificationsPage,
})

const PAGE_SIZE = 20

type CategoryTab = 'all' | NotificationCategory

const CATEGORY_TABS: { value: CategoryTab; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'review', label: '审稿' },
  { value: 'submission', label: '投稿' },
  { value: 'claim', label: '认领' },
  { value: 'community', label: '社区' },
  { value: 'feedback', label: '反馈' },
  { value: 'system', label: '系统' },
]

// 「全部」里也不再把类型混成一锅：每条通知带一个类型短标签。
const TYPE_LABELS: Record<string, string> = {
  'review.invited': '审稿邀请',
  'review.reminder': '催审',
  'review.accepted': '审稿接受',
  'review.submitted': '审稿提交',
  'submission.decision': '投稿裁决',
  'submission.resubmitted': '重新投稿',
  'submission.rework_requested': '返修',
  'claim.created': '认领申请',
  'claim.decision': '认领结果',
  'site.feedback': '站点反馈',
  'comment.new': '文章评论',
  'forum.reply': '论坛回复',
  system: '系统',
  'gamification.role_application': '角色申请',
}

/**
 * 把通知的 related_type / related_id 解析成站内目标。
 *
 * 后端在写通知时就带上了这对指针（见 notifications/models.py），
 * 但前端一直没消费它 —— 用户只能看到"您的稿件收到编辑决定"，
 * 却没有任何一跳能到达那篇稿件。这里补上这条链路。
 *
 * 返回 null 表示该通知没有可跳转的目标（如纯系统公告）。
 */
function resolveTarget(
  relatedType?: string | null,
  relatedId?: string | null,
): { to: string; params?: Record<string, string>; label: string } | null {
  if (!relatedType || !relatedId) return null
  switch (relatedType) {
    case 'resource':
      return {
        to: '/catalog/$resourceId',
        params: { resourceId: relatedId },
        label: '查看文章',
      }
    case 'submission':
      return { to: '/submissions', label: '查看稿件' }
    case 'review_assignment':
      return { to: '/review/assignments', label: '前往审稿' }
    case 'forum_topic':
      return {
        to: '/forum/$topicId',
        params: { topicId: relatedId },
        label: '查看讨论',
      }
    default:
      return null
  }
}

function formatWhen(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function NotificationsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [category, setCategory] = useState<CategoryTab>('all')
  const { data, isLoading, isError, refetch } = useNotifications(
    page,
    PAGE_SIZE,
    category === 'all' ? undefined : category,
  )
  const unread = useUnreadCount()
  const markAllMut = useMarkAllRead()
  const markMut = useMarkRead()
  const deleteMut = useDeleteNotification()

  const onMarkAll = async () => {
    try {
      const res = await markAllMut.mutateAsync()
      toast.success(`已标记 ${res.updated} 条为已读`)
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const onMarkRead = async (id: number) => {
    try {
      await markMut.mutateAsync(id)
    } catch (err) {
      toast.error(extractError(err, '标记失败'))
    }
  }

  const onDelete = async (id: number) => {
    try {
      await deleteMut.mutateAsync(id)
      toast.success('已删除')
    } catch (err) {
      toast.error(extractError(err, '删除失败'))
    }
  }

  const unreadCount = unread.data?.unread ?? 0

  return (
    <div>
      <PageHeader
        title="通知"
        description="关注、提交、提及等所有站内消息。"
        actions={
          <Button
            variant="outline"
            onClick={onMarkAll}
            disabled={unreadCount === 0 || markAllMut.isPending}
          >
            <CheckCheck className="h-4 w-4" />
            全部标为已读
          </Button>
        }
      />

      <div className="mb-4 flex items-center gap-2">
        <span className="text-sm text-muted-foreground">未读</span>
        <Badge variant={unreadCount > 0 ? 'default' : 'secondary'}>
          {unreadCount}
        </Badge>
      </div>

      <Tabs
        value={category}
        onValueChange={(v) => {
          setCategory(v as CategoryTab)
          setPage(1)
        }}
      >
        <div className="overflow-x-auto pb-1">
          <TabsList className="w-max">
            {CATEGORY_TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>

      <div className="mt-4">
        {isLoading ? (
          <LoadingSkeleton rows={5} />
        ) : isError ? (
          <ErrorState message="加载通知失败" onRetry={() => refetch()} />
        ) : !data || data.data.length === 0 ? (
          <EmptyState title="暂无通知" />
      ) : (
        <div className="space-y-3">
          {data.data.map((n) => (
            <Card
              key={n.id}
              // 未读：左侧蓝色竖线区分
              className={
                n.is_read ? 'border-l-0' : 'border-l-4 border-l-primary'
              }
            >
              <CardContent className="flex items-start gap-3 py-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary" className="shrink-0">
                      {TYPE_LABELS[n.type] ?? n.type}
                    </Badge>
                    {!n.is_read && (
                      <Badge variant="default" className="shrink-0">
                        新
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {formatWhen(n.created_at)}
                    </span>
                  </div>
                  <p className="mt-1.5 break-words text-sm font-medium leading-snug">
                    {n.title}
                  </p>
                  {n.body && (
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-muted-foreground">
                      {n.body}
                    </p>
                  )}
                  {(() => {
                    const target = resolveTarget(n.related_type, n.related_id)
                    if (!target) return null
                    return (
                      <Button
                        variant="link"
                        size="sm"
                        className="mt-1 h-auto p-0"
                        onClick={() => {
                          // 点击深链视为已读（用户已经看到并处理了这条通知）
                          if (!n.is_read) void onMarkRead(n.id)
                          void navigate({
                            to: target.to,
                            params: target.params,
                          })
                        }}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {target.label}
                      </Button>
                    )
                  })()}
                </div>
                <div className="flex shrink-0 flex-col items-center gap-1">
                  {!n.is_read && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="标为已读"
                      title="标为已读"
                      onClick={() => onMarkRead(n.id)}
                      disabled={markMut.isPending}
                    >
                      <CheckCheck className="h-4 w-4" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="删除通知"
                    title="删除通知"
                    onClick={() => onDelete(n.id)}
                    disabled={deleteMut.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      </div>

      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          onPageChange={setPage}
        />
      )}
    </div>
  )
}
