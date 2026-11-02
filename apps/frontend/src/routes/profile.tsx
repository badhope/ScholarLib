import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import {
  Award,
  BookOpen,
  CircleCheck,
  Flame,
  GraduationCap,
  Lock,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { getAuthState } from '@/lib/auth'
import { useAuth } from '@/hooks/use-auth'
import { useMe } from '@/hooks/api/use-auth'
import {
  useAcceptAuthorRules,
  useAcknowledgeCommunity,
  useGamificationProfile,
} from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState, Loading } from '@/components/common/state'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { BadgeItem, LevelCapability } from '@/lib/types'

export const Route = createFileRoute('/profile')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: ProfilePage,
})

const TIER_STYLES: Record<BadgeItem['tier'], string> = {
  bronze: 'from-amber-700/20 to-amber-500/5 border-amber-600/30',
  silver: 'from-slate-400/20 to-slate-300/5 border-slate-400/40',
  gold: 'from-amber-400/25 to-yellow-200/5 border-amber-500/40',
  special: 'from-primary/25 to-primary/5 border-primary/40',
}

const TIER_LABELS: Record<BadgeItem['tier'], string> = {
  bronze: '铜',
  silver: '银',
  gold: '金',
  special: '特别',
}

const XP_LABELS: Record<string, string> = {
  register: '注册账号',
  'onboarding.ack_rules': '确认社区规范',
  'onboarding.author': '确认投稿规范',
  'read.article': '阅读文章',
  'comment.create': '发表评论',
  'library.create': '建立阅读列表',
  'submission.create': '提交稿件',
  'submission.accepted': '稿件录用',
  'submission.rejected': '稿件退修',
  'review.completed': '完成审稿',
  'editor.decision': '编辑裁决',
  'admin.grant': '编辑部奖励',
}

function LevelBadge({ level }: { level: number }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 items-center rounded-full px-2.5 text-xs font-semibold tabular-nums',
        level >= 9
          ? 'bg-primary text-primary-foreground'
          : level >= 5
            ? 'bg-primary/15 text-primary'
            : 'bg-muted text-muted-foreground',
      )}
    >
      L{level}
    </span>
  )
}

function Ladder({ levels, current }: { levels: LevelCapability[]; current: number }) {
  return (
    <ol className="space-y-2">
      {levels.map((item) => {
        const reached = item.level <= current
        return (
          <li
            key={item.level}
            className={cn(
              'rounded-lg border px-3 py-2.5 transition-colors',
              item.level === current
                ? 'border-primary/50 bg-primary/[0.06]'
                : reached
                  ? 'border-border/70'
                  : 'border-dashed border-border/50 opacity-60',
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <LevelBadge level={item.level} />
              <span className="text-sm font-medium">{item.name}</span>
              <Badge variant="outline" className="text-[10px]">
                {item.track === 'merit' ? '积分解锁' : '编辑部授予'}
              </Badge>
              {item.level === current && (
                <Badge className="text-[10px]">当前</Badge>
              )}
              {!reached && <Lock className="h-3 w-3 text-muted-foreground" />}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {item.description}
            </p>
            {reached && (
              <p className="mt-1 text-[11px] text-muted-foreground/90">
                {item.capabilities.slice(0, 3).join(' · ')}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function BadgeCard({ badge }: { badge: BadgeItem }) {
  const pct = badge.threshold > 0 ? Math.min(100, (badge.current / badge.threshold) * 100) : 0
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border bg-gradient-to-br p-4',
        badge.unlocked ? TIER_STYLES[badge.tier] : 'border-dashed border-border/60 bg-none opacity-70',
      )}
      title={badge.description}
    >
      <div className="flex items-start justify-between gap-2">
        <Award className={cn('h-5 w-5', badge.unlocked ? 'text-primary' : 'text-muted-foreground')} />
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          {TIER_LABELS[badge.tier]}
        </span>
      </div>
      <p className="mt-2 text-sm font-medium">{badge.name}</p>
      <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
        {badge.description}
      </p>
      {badge.unlocked ? (
        <p className="mt-2 flex items-center gap-1 text-[11px] text-primary">
          <CircleCheck className="h-3 w-3" />
          {badge.unlocked_at ? new Date(badge.unlocked_at).toLocaleDateString('zh-CN') : '已解锁'}
        </p>
      ) : (
        <div className="mt-2">
          <div className="h-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary/60" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1 text-[10px] tabular-nums text-muted-foreground">
            {badge.current} / {badge.threshold}
          </p>
        </div>
      )}
    </div>
  )
}

function ProfilePage() {
  const { user } = useAuth()
  const { data, isLoading, isError, refetch } = useGamificationProfile()
  const { data: me } = useMe()
  const ackCommunity = useAcknowledgeCommunity()
  const acceptRules = useAcceptAuthorRules()

  if (isLoading) return <Loading />
  if (isError || !data) return <ErrorState message="加载个人中心失败" onRetry={() => refetch()} />

  const level = data.level
  const unlocked = data.badges.filter((b) => b.unlocked)
  const locked = data.badges.filter((b) => !b.unlocked)
  const needsCommunity = level.level < 2
  const needsAuthor = !data.rules_accepted

  return (
    <div className="space-y-6">
      <PageHeader
        title="个人中心"
        description="等级、成就与参与记录。等级只升不降，权限随等级逐步解锁。"
      />

      {/* 等级卡 */}
      <Card className="overflow-hidden">
        <div className="bg-gradient-to-br from-primary/[0.08] to-transparent p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <LevelBadge level={level.level} />
                <h2 className="text-xl font-semibold">{level.name}</h2>
                <Badge variant="outline">{level.title}</Badge>
              </div>
              <p className="mt-1.5 text-sm text-muted-foreground">{level.description}</p>
              {me?.bio ? (
                <p className="mt-1 text-sm italic text-foreground/80">「{me.bio}」</p>
              ) : null}
              <p className="mt-2 text-xs text-muted-foreground">
                总积分 <span className="font-semibold tabular-nums text-foreground">{level.xp}</span>
                {/* 身份 3.0：积分是荣誉统计，不再是"距下一等级"的进度条。 */}
                {level.next_identity && (
                  <>
                    {' · '}
                    {level.next_identity.name}：{level.next_identity.how}
                  </>
                )}
                {' · '}角色：{level.roles.length ? level.roles.join('、') : '读者'}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">已解锁成就</p>
              <p className="text-3xl font-semibold tabular-nums">
                {data.unlocked_count}
                <span className="text-base font-normal text-muted-foreground">
                  {' '}/ {data.total_badges}
                </span>
              </p>
            </div>
          </div>
          {/* 身份没有"进度条"：身份要么有（授予/确认），要么没有（去申请）。
              用下一步动作替代旧版的 XP 进度条。 */}
          {level.next_identity && (
            <div className="mt-4 rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              下一步：<span className="font-medium text-foreground">{level.next_identity.name}</span>
              {' — '}
              {level.next_identity.how}
            </div>
          )}
        </div>
      </Card>

      {/* 待办：两条引导 */}
      {(needsCommunity || needsAuthor) && (
        <div className="grid gap-4 md:grid-cols-2">
          {needsCommunity && (
            <Card className="border-primary/30">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Sparkles className="h-4 w-4 text-primary" /> 第 1 步：加入社区
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
 L1 即可阅读和评论。阅读社区规范并确认可获得积分，等级由积分决定。
 </p>
 <Button asChild size="sm" variant="outline">
 <Link to="/policies">阅读社区规范</Link>
 </Button>
 <Button
                  size="sm"
                  onClick={() => ackCommunity.mutate()}
                  disabled={ackCommunity.isPending}
                >
                  {ackCommunity.isPending ? '处理中…' : '我已阅读，加入社区'}
                </Button>
              </CardContent>
            </Card>
          )}
          {needsAuthor && (
            <Card className={needsCommunity ? '' : 'border-primary/30'}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <GraduationCap className="h-4 w-4 text-primary" /> 第 2 步：成为作者
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  阅读并接受《投稿与编辑规范》后即可投稿，无需达到 L3。规范改版后需重新确认。
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button asChild size="sm" variant="outline">
                    <Link to="/authors">先读规范</Link>
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => acceptRules.mutate()}
                    disabled={acceptRules.isPending}
                  >
                    {acceptRules.isPending ? '处理中…' : '我已读完，接受规范'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* 等级阶梯 */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" /> 等级阶梯
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Ladder levels={data.ladder} current={level.level} />
            <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
              L2、L3 按积分解锁；L4还需稿件录用；L5 起由编辑部授予。
            </p>
          </CardContent>
        </Card>

        {/* 勋章墙 */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Award className="h-4 w-4" /> 成就墙
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {unlocked.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground">
                  已解锁 · {unlocked.length}
                </p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {unlocked.map((b) => (
                    <BadgeCard key={b.key} badge={b} />
                  ))}
                </div>
              </div>
            )}
            {locked.length > 0 && (
              <div>
                <p className="mb-2 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                  <Lock className="h-3 w-3" /> 即将解锁 · 只展示最近 3 个
                </p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {locked.map((b) => (
                    <BadgeCard key={b.key} badge={b} />
                  ))}
                </div>
              </div>
            )}
            {unlocked.length === 0 && locked.length === 0 && (
              <p className="text-sm text-muted-foreground">开始阅读第一篇，就会点亮第一枚徽章。</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 积分明细 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Flame className="h-4 w-4" /> 最近积分
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_xp.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有积分记录。</p>
          ) : (
            <ul className="divide-y text-sm">
              {data.recent_xp.map((e, i) => (
                <li key={i} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0 truncate">
                    {XP_LABELS[e.action] ?? e.action}
                    {e.note ? <span className="text-muted-foreground"> · {e.note}</span> : null}
                  </span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    +{e.points} XP
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
          <span className="flex items-center gap-2 text-muted-foreground">
            <BookOpen className="h-4 w-4" />
            想先看有哪些文章值得读？创刊号已上线。
          </span>
          <Button asChild size="sm" variant="outline">
            <Link to="/catalog">浏览目录</Link>
          </Button>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        当前账号：{user?.username ?? data.username} · 等级体系口径 v1.0（冻结）
      </p>
    </div>
  )
}
