import { useState } from 'react'
import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import {
  ArrowRight,
  BookOpen,
  CalendarCheck,
  ClipboardCheck,
  ClipboardList,
  Clock3,
  Flame,
  Lightbulb,
  Bell,
  Library,
  PlayCircle,
  ScrollText,
  Trophy,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import { recommendationReason } from '@/lib/resource-labels'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { useAuth } from '@/hooks/use-auth'
import {
  useCatalogStats,
  useCheckinStatus,
  useDailyCheckin,
  useGamificationProfile,
  useMyRecommendations,
  useMyReviewAssignments,
  useMySubmissions,
  useNotifications,
  usePendingSubmissions,
  useReadingHistory,
  useReadingLists,
  useUnreadCount,
} from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { StatTile } from '@/components/mobile/StatTile'

export const Route = createFileRoute('/dashboard')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) {
      throw redirect({ to: '/login', search: { redirect: '/dashboard' } })
    }
  },
  component: DashboardPage,
})

interface StatCard {
  label: string
  value: string | number
  to: string
  icon: LucideIcon
}

function SectionHeading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mt-8 mb-3">
      <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      {hint ? (
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
}

/** 每日签到横幅：一行收拢——按钮、连续天数、本周进度，不占第二屏。 */
function CheckinBanner() {
  const status = useCheckinStatus()
  const checkin = useDailyCheckin()
  const st = status.data
  // 签到成功的一瞬间给按钮一个"弹一下+金圈"反馈，替代廉价的整页动画
  const [pulse, setPulse] = useState(false)

  const onCheckin = async () => {
    try {
      const r = await checkin.mutateAsync()
      if (r.bonus_awarded) {
        toast.success(
          `连续签到 ${r.streak} 天，额外 +${r.weekly_bonus_xp} XP！`,
        )
      } else if (r.awarded) {
        toast.success(`签到成功，+${r.daily_xp} XP`)
      } else {
        toast.info('今天已经签到过了')
      }
      if (r.awarded) {
        setPulse(true)
        window.setTimeout(() => setPulse(false), 1600)
      }
    } catch {
      toast.error('签到失败，请稍后再试')
    }
  }

  if (status.isLoading) return <Skeleton className="h-16 w-full rounded-lg" />

  const weekProgress = st ? st.streak % 7 : 0
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3"
      data-testid="checkin-banner"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
          <CalendarCheck className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-medium">
            每日签到
            {st && st.streak > 0 && (
              <span className="ml-2 inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400">
                <Flame className="h-3.5 w-3.5" />
                连续 {st.streak} 天
              </span>
            )}
          </p>
          <p className="text-xs text-muted-foreground">
            {st
              ? st.checked_in_today
                ? `今日已签到 · 本周进度 ${weekProgress}/7 · 累计 ${st.total} 天`
                : `签到 +${st.daily_xp} XP · 连续每满 7 天 +${st.weekly_bonus_xp} XP`
              : '加载中…'}
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant={st?.checked_in_today ? 'outline' : 'default'}
        disabled={st?.checked_in_today || checkin.isPending}
        onClick={() => void onCheckin()}
        data-testid="checkin-button"
        className={
          pulse
            ? 'animate-in zoom-in-95 duration-500 ring-2 ring-amber-400 ring-offset-2 ring-offset-background'
            : undefined
        }
      >
        {st?.checked_in_today
          ? '已签到'
          : checkin.isPending
            ? '签到中…'
            : '签到'}
      </Button>
    </div>
  )
}

/** 审稿人 Today：只回答“今天有几件事、先点哪里”，不把审稿台再抄一遍。 */
function ReviewerTodayCard() {
  const { user, isAdmin } = useAuth()
  const roles = user?.roles ?? []
  const canReview =
    isAdmin ||
    roles.some((role) =>
      ['reviewer', 'senior_reviewer', 'editor_in_chief'].includes(role),
    )
  const pending = useMyReviewAssignments('pending', 1, 5, {
    enabled: canReview,
  })
  const accepted = useMyReviewAssignments('accepted', 1, 5, {
    enabled: canReview,
  })

  if (!canReview) return null

  const pendingRows = pending.data?.data ?? []
  const acceptedRows = accepted.data?.data ?? []
  const pendingCount = pending.data?.meta.total ?? pendingRows.length
  const acceptedCount = accepted.data?.meta.total ?? acceptedRows.length
  const nextDue = [...pendingRows, ...acceptedRows]
    .map((row) => row.due_date)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0]
  const loading = pending.isLoading || accepted.isLoading

  return (
    <div
      className="mt-3 rounded-lg border bg-card px-4 py-3"
      data-testid="reviewer-today"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300">
            <ClipboardCheck className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-medium">今天要审的稿</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {loading
                ? '正在读取审稿任务…'
                : pendingCount + acceptedCount > 0
                  ? `待回应 ${pendingCount} 个邀请 · 已接受 ${acceptedCount} 篇待完成`
                  : '今天没有待审任务，保持这个节奏。'}
            </p>
          </div>
        </div>
        <Link
          to="/review/assignments"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          审稿台 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Link
          to="/review/assignments"
          search={{ status: 'pending' }}
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="text-xs text-muted-foreground">待回应邀请</span>
          <span className="font-semibold tabular-nums">{pendingCount}</span>
        </Link>
        <Link
          to="/review/assignments"
          search={{ status: 'accepted' }}
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock3 className="h-3.5 w-3.5" />
            {nextDue
              ? `最近截止 ${new Date(nextDue).toLocaleDateString('zh-CN')}`
              : '最近截止 待定'}
          </span>
          <span className="font-semibold tabular-nums">{acceptedCount}</span>
        </Link>
      </div>
    </div>
  )
}

/** 继续阅读卡：只在上次没读完时出现——把"上次读到哪"变成一键回来的入口。 */
function ContinueReadingCard() {
  const history = useReadingHistory(1, 5)
  const items = (history.data?.data ?? [])
    .filter((h) => !h.completed && (h.progress_percent ?? 0) > 1 && h.title)
    .slice(0, 2)
  if (history.isLoading || items.length === 0) return null
  return (
    <Card className="border-primary/25 bg-primary/[0.03]">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <PlayCircle className="h-4 w-4 text-primary" />
          继续阅读
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.map((h) => (
          <Link
            key={h.resource_id}
            to="/catalog/$resourceId"
            params={{ resourceId: String(h.resource_id) }}
            hash="article"
            className="block rounded-lg border bg-card px-3 py-2 transition-colors hover:border-primary/40"
          >
            <p className="line-clamp-1 text-sm font-medium">{h.title}</p>
            <div className="mt-1.5 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary/70"
                  style={{
                    width: `${Math.min(100, Math.round(h.progress_percent ?? 0))}%`,
                  }}
                />
              </div>
              <span className="text-xs tabular-nums text-muted-foreground">
                {Math.round(h.progress_percent ?? 0)}%
              </span>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}

/** 成就进度条：展示离解锁最近的 2 枚成就——让"再读 3 篇就能解锁"可见。 */
function BadgeProgressStrip() {
  const profile = useGamificationProfile()
  const badges = profile.data?.badges ?? []
  const next = badges
    .filter((b) => !b.unlocked && b.threshold > 0)
    .sort((a, b) => b.current / b.threshold - a.current / a.threshold)
    .slice(0, 2)
  if (profile.isLoading || next.length === 0) return null
  return (
    <div
      className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border bg-card px-4 py-3"
      data-testid="badge-progress"
    >
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Trophy className="h-3.5 w-3.5 text-amber-500" />
        即将解锁
      </span>
      {next.map((b) => {
        const pct = Math.min(100, Math.round((b.current / b.threshold) * 100))
        return (
          <div key={b.key} className="min-w-40 flex-1">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-medium">{b.name}</span>
              <span className="tabular-nums text-muted-foreground">
                {b.current}/{b.threshold}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-amber-500/80"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
      <Link to="/profile" className="text-xs text-primary hover:underline">
        成就墙
      </Link>
    </div>
  )
}

function DashboardPage() {
  const { user, isAdmin } = useAuth()
  const roles = user?.roles ?? []
  const isEditorial =
    isAdmin ||
    roles.some((r) =>
      ['editor', 'section_editor', 'editor_in_chief'].includes(r),
    )

  const profile = useGamificationProfile()
  const stats = useCatalogStats()
  const recs = useMyRecommendations(5)
  // 未读数走 /notifications/unread-count：列表接口的 meta.total 是
  // 「通知总数」，跟「未读」根本不是一回事。
  const notifs = useNotifications(1, 5)
  const unread = useUnreadCount({ enabled: true })
  // 这里要的是「我自己的投稿数」。以前调 /submissions/pending，那是编辑的
  // 待审队列（require_editor），普通用户只会拿到 403 而永远显示 "—"。
  const mine = useMySubmissions(undefined, 1, 1)
  // 编辑部成员才查待审队列，普通读者不触发 403 请求。
  const pending = usePendingSubmissions(1, 1, { enabled: isEditorial })
  const lists = useReadingLists(1, 5)
  const isMobile = useIsMobile()

  // 角色感知统计：所有人看得到的通知/目录 + 按身份就近放最常用的两块。
  // 一次最多 4 张，避免信息过载（渐进披露：完整列表点卡片进入对应页）。
  const cards: StatCard[] = [
    {
      label: '资源总数',
      value: stats.data?.total ?? '—',
      to: '/catalog',
      icon: BookOpen,
    },
    {
      label: '未读通知',
      value: unread.data?.unread ?? '—',
      to: '/notifications',
      icon: Bell,
    },
  ]
  if (isEditorial) {
    cards.push({
      label: '待审稿件',
      value: pending.data?.meta.total ?? '—',
      to: '/submissions/pending',
      icon: ClipboardList,
    })
  } else if (
    roles.includes('author') ||
    (profile.data?.level.level ?? 0) >= 3
  ) {
    cards.push({
      label: '我的投稿',
      value: mine.data?.meta.total ?? '—',
      to: '/submissions',
      icon: ScrollText,
    })
  }
  if (cards.length < 4) {
    cards.push({
      label: '阅读列表',
      value: lists.data?.meta.total ?? '—',
      to: '/library',
      icon: Library,
    })
  }
  if (cards.length < 4) {
    cards.push({
      label: '我的推荐',
      value: recs.data?.meta.total ?? '—',
      to: '/recommendations',
      icon: Lightbulb,
    })
  }

  const level = profile.data?.level

  return (
    <div>
      <PageHeader
        title="概览"
        description={`${greeting()}，${user?.username ?? '读者'}。你的 Rubbish 工作台一览。`}
        actions={
          level ? (
            <Badge variant="secondary" className="text-xs">
              {level.name} · {profile.data?.xp ?? 0} XP
            </Badge>
          ) : undefined
        }
      />

      <SectionHeading
        title="今日与成长"
        hint="签到、等级进度与连续阅读，先看今天要做什么。"
      />
      <CheckinBanner />
      <ReviewerTodayCard />

      <div className="mt-3">
        <BadgeProgressStrip />
      </div>

      <SectionHeading
        title="阅读与发现"
        hint="继续上次的阅读，或从推荐里找下一篇。"
      />
      <div className="mt-3">
        <ContinueReadingCard />
      </div>

      {/* 移动端：2 列大数据块 + 快捷操作；桌面端：4 列小卡 */}
      {isMobile ? (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {cards.map((c) => (
              <StatTile
                key={c.to}
                label={c.label}
                value={
                  stats.isLoading && c.label === '资源总数' ? (
                    <Skeleton className="h-7 w-12" />
                  ) : (
                    c.value
                  )
                }
                to={c.to}
                icon={c.icon}
              />
            ))}
          </div>
          <div
            className="mt-4 grid grid-cols-3 gap-3"
            data-testid="mobile-quick-actions"
          >
            <Button asChild className="flex-col gap-1 py-3" variant="outline">
              <Link to="/catalog">
                <BookOpen className="h-5 w-5" />
                <span className="text-xs">浏览目录</span>
              </Link>
            </Button>
            <Button asChild className="flex-col gap-1 py-3" variant="outline">
              <Link to="/submissions">
                <ScrollText className="h-5 w-5" />
                <span className="text-xs">我的提交</span>
              </Link>
            </Button>
            <Button asChild className="flex-col gap-1 py-3" variant="outline">
              <Link to="/recommendations">
                <Lightbulb className="h-5 w-5" />
                <span className="text-xs">推荐</span>
              </Link>
            </Button>
          </div>
        </>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          {cards.map((c) => {
            const Icon = c.icon
            return (
              <Link
                key={c.to}
                to={c.to}
                className="block transition-transform hover:-translate-y-0.5"
              >
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-xs font-medium text-muted-foreground">
                      {c.label}
                    </CardTitle>
                    <Icon className="h-4 w-4 text-muted-foreground" />
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-semibold">
                      {stats.isLoading && c.label === '资源总数' ? (
                        <Skeleton className="h-7 w-12" />
                      ) : (
                        c.value
                      )}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}

      <SectionHeading
        title="社区与消息"
        hint="推荐、通知与社区动态按用途分开，不再混在一条信息流里。"
      />
      <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">为你推荐</CardTitle>
            <Link
              to="/recommendations"
              className="text-xs text-primary hover:underline"
            >
              查看全部
            </Link>
          </CardHeader>
          <CardContent>
            {recs.isLoading ? (
              <Loading />
            ) : recs.isError ? (
              <ErrorState message="加载推荐失败" />
            ) : recs.data?.data.length ? (
              <ul className="space-y-3">
                {recs.data.data.slice(0, 5).map((r) => (
                  <li
                    key={r.id}
                    className="border-b pb-2 last:border-0 last:pb-0"
                  >
                    <Link
                      to="/catalog/$resourceId"
                      params={{ resourceId: String(r.id) }}
                      className="block hover:text-primary"
                    >
                      <p className="line-clamp-1 text-sm font-medium">
                        {r.title}
                      </p>
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                        {r.authors.join(', ')} ·{' '}
                        {recommendationReason(r.reason)}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                compact
                title="暂无推荐"
                description="阅读几篇资源后即可获得个性化推荐"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">最新通知</CardTitle>
            <Link
              to="/notifications"
              className="text-xs text-primary hover:underline"
            >
              查看全部
            </Link>
          </CardHeader>
          <CardContent>
            {notifs.isLoading ? (
              <Loading />
            ) : notifs.isError ? (
              <ErrorState message="加载通知失败" />
            ) : notifs.data?.data.length ? (
              <ul className="space-y-3">
                {notifs.data.data.slice(0, 5).map((n) => (
                  <li
                    key={n.id}
                    className="border-b pb-2 last:border-0 last:pb-0"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1">
                        <p className="text-sm font-medium">{n.title}</p>
                        {n.body && (
                          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                            {n.body}
                          </p>
                        )}
                      </div>
                      {!n.is_read && (
                        <Badge variant="secondary" className="shrink-0">
                          新
                        </Badge>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState compact title="暂无通知" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
