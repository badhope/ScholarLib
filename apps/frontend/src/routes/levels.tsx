import { createFileRoute, Link } from '@tanstack/react-router'
import {
  Award,
  BookOpen,
  CalendarCheck,
  Coins,
  Flame,
  Layers,
  Lock,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'
import { useCheckinStatus, useDailyCheckin, useLadder, useQualityRubric } from '@/hooks/api/use-modules'
import { RoleApplicationsSection } from '@/components/common/role-applications'
import { useAuth } from '@/hooks/use-auth'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/levels')({
  component: LevelsPage,
})

const GRADE_STYLES: Record<string, string> = {
  'A+': 'bg-primary text-primary-foreground',
  A: 'bg-primary/80 text-primary-foreground',
  B: 'bg-primary/20 text-primary',
  C: 'bg-muted text-foreground',
  D: 'bg-destructive/10 text-destructive',
}

/** 每日签到与积分来源说明：货币体系（XP）的入口页说明 + 一键签到。 */
function CheckinSection({ authenticated }: { authenticated: boolean }) {
  const status = useCheckinStatus({ enabled: authenticated })
  const checkin = useDailyCheckin()
  const st = status.data

  const onCheckin = async () => {
    try {
      const r = await checkin.mutateAsync()
      if (r.bonus_awarded) toast.success(`连续签到 ${r.streak} 天，额外 +${r.weekly_bonus_xp} XP！`)
      else if (r.awarded) toast.success(`签到成功，+${r.daily_xp} XP`)
      else toast.info('今天已经签到过了')
    } catch {
      toast.error('签到失败，请稍后再试')
    }
  }

  const SOURCES: [string, string][] = [
    ['每日签到', '每天 +2，连续每满 7 天再 +5'],
    ['阅读资源', '读完一篇 +2，完整读毕 +3'],
    ['参与讨论', '发表评论 +2（每日封顶 10）'],
    ['收藏与关注', '创建阅读列表 +3，关注作者 +2'],
    ['投稿与审稿', '投稿 +10，录用 +60，完成审稿 +25'],
  ]

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <Coins className="h-4 w-4" /> 每日签到与积分获取
      </h2>
      <Card>
        <CardContent className="space-y-4 py-5">
          {authenticated ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-4 py-3">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                  <CalendarCheck className="h-5 w-5" />
                </div>
                <p className="text-sm">
                  {st ? (
                    st.checked_in_today ? (
                      <>
                        今日已签到
                        {st.streak > 0 && (
                          <span className="ml-2 inline-flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400">
                            <Flame className="h-3.5 w-3.5" />
                            连续 {st.streak} 天 · 累计 {st.total} 天
                          </span>
                        )}
                      </>
                    ) : (
                      `已连续签到 ${st.streak} 天，今天还没签`
                    )
                  ) : (
                    '加载签到状态…'
                  )}
                </p>
              </div>
              <Button
                size="sm"
                variant={st?.checked_in_today ? 'outline' : 'default'}
                disabled={st?.checked_in_today || checkin.isPending}
                onClick={() => void onCheckin()}
              >
                {st?.checked_in_today ? '已签到' : checkin.isPending ? '签到中…' : '立即签到'}
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              登录后即可每日签到累积 XP：<Link to="/login" className="text-primary hover:underline">去登录</Link>
            </p>
          )}
          <ul className="grid gap-x-6 gap-y-1.5 text-sm text-muted-foreground sm:grid-cols-2">
            {SOURCES.map(([name, desc]) => (
              <li key={name} className="flex justify-between gap-2 border-b border-dashed pb-1.5">
                <span className="text-foreground">{name}</span>
                <span className="tabular-nums text-xs">{desc}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  )
}

function LevelsPage() {
  const ladder = useLadder()
  const rubric = useQualityRubric()
  const { isAuthenticated } = useAuth()

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-10 sm:px-6">
      <PageHeader
        title="等级体系与质量规范"
        description="Rubbish 的权限阶梯、成就体系与论文质量评分口径。全部公开、全部冻结，改版需升版本号。"
      />

      {/* 为什么有等级 */}
      <Card className="border-primary/25 bg-primary/[0.03]">
        <CardContent className="space-y-3 py-5 text-sm leading-relaxed">
          <p className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-primary" />
            两条轨道，一套阶梯
          </p>
          <p className="text-muted-foreground">
            <strong className="text-foreground">投稿轨（L1–L4）</strong>
            L1 可阅读、评论，确认投稿规范后即可投稿；L2、L3 按积分解锁，L4 必须有稿件被本刊录用——积分满 400 也只是必要条件，
            <strong className="text-foreground">投稿并录用才是升级的重磅</strong>；
            <strong className="text-foreground">职责轨（L5–L9）</strong>
            L5/L6 按下方冻结标准开放申请、编辑部审批，L7 以上由编辑部按贡献直接提拔。
          </p>
          <p className="text-muted-foreground">
            每位用户只看到自己已达到的等级与最近三个待解锁成就：等级是慢慢长出来的，
            不是一次性铺开的权限清单。
          </p>
        </CardContent>
      </Card>

      {/* 每日签到与积分获取（登录用户可见签到条；游客看到玩法说明） */}
      <CheckinSection authenticated={isAuthenticated} />

      {/* 职责轨申请通道（L5/L6）：资格画像 + 提交 + 记录 */}
      <RoleApplicationsSection />

      {/* 四种身份：与后端 require_* 门禁一一对应 */}
      <section>
        <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
          <Layers className="h-4 w-4" /> 四种身份
        </h2>
        {ladder.isLoading ? (
          <Loading />
        ) : ladder.isError || !ladder.data ? (
          <ErrorState message="加载身份体系失败" onRetry={() => ladder.refetch()} />
        ) : (
          <div className="space-y-3">
            {ladder.data.identities.map((item) => (
              <div
                key={item.slug}
                className={cn(
                  'rounded-xl border p-4 sm:p-5',
                  item.slug === 'reader' || item.slug === 'author' ? 'bg-card' : 'bg-muted/30',
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex h-7 items-center rounded-full px-2.5 text-xs font-semibold tabular-nums',
                      item.slug === 'reviewer' || item.slug === 'editor'
                        ? 'bg-primary/15 text-primary'
                        : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {item.name}
                  </span>
                  <h3 className="text-base font-semibold">{item.name}</h3>
                  <Badge variant="outline" className="text-[10px]">
                    {/* 身份 3.0：granted_by 是唯一获得方式说明（XP 不再是
                        任何身份的条件）。旧字段 track 保留兼容但不再展示。 */}
                    {item.granted_by ?? '身份'}
                  </Badge>
                </div>
                <p className="mt-1.5 text-sm text-muted-foreground">{item.description}</p>
                <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {item.capabilities.map((c) => (
                    <li key={c} className="flex items-center gap-1">
                      <Sparkles className="h-3 w-3 text-primary/70" />
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 成就 */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <Award className="h-4 w-4" /> 成就体系
        </h2>
        <Card>
          <CardContent className="space-y-3 py-5 text-sm leading-relaxed text-muted-foreground">
            <p>
              成就分四档：铜（入门）· 银（常态参与）· 金（长期贡献）· 特别（稀有行为）。
              共 27 枚，覆盖阅读、讨论、收藏、关注、投稿、审稿、编辑、习惯、探索九类。
            </p>
            <p>
              解法不一：有的是累计量（读完 50 篇），有的是连续行为（连续 30 天有阅读），
              有的是稀有场景（凌晨三点读完一篇）。隐藏成就只在解锁后显示，
              最高权限（L9）可查看完整成就表。
            </p>
            <p className="text-xs">
              个人中心只展示「已解锁 + 最近三个待解锁」，成就墙随等级逐步展开。
            </p>
            <Button asChild size="sm" variant="outline">
              <Link to="/profile">进入我的个人中心</Link>
            </Button>
          </CardContent>
        </Card>
      </section>

      {/* 质量评分 */}
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <BookOpen className="h-4 w-4" /> 论文质量评分（RQS v1.0）
        </h2>
        {rubric.isLoading ? (
          <Loading />
        ) : rubric.isError || !rubric.data ? (
          <ErrorState message="加载评分规范失败" onRetry={() => rubric.refetch()} />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(rubric.data.profiles).map(([key, profile]) => (
                <Card key={key} className="bg-card/60">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{profile.label}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-[11px] text-muted-foreground">
                      {Object.entries(profile.weights).map(([dim, weight]) => {
                        const dimLabel =
                          rubric.data.dimensions.find((d) => d.key === dim)?.label ?? dim
                        return (
                          <li key={dim} className="flex justify-between gap-2">
                            <span>{dimLabel}</span>
                            <span className="tabular-nums">{weight}</span>
                          </li>
                        )
                      })}
                    </ul>
                  </CardContent>
                </Card>
              ))}
            </div>
            <Card>
              <CardContent className="space-y-3 py-5 text-sm">
                <div className="flex flex-wrap gap-2">
                  {rubric.data.grades.map((g) => (
                    <span
                      key={g.code}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
                        GRADE_STYLES[g.code],
                      )}
                    >
                      {g.code} {g.label}
                      <span className="tabular-nums opacity-70">
                        {g.min}–{g.max}
                      </span>
                    </span>
                  ))}
                </div>
                <p className="text-muted-foreground">
                  评分七维加权满分 100；纯度系数（QC）＝ RQS ÷ 50，范围 0.00–2.00，
                  仅作展示用，不构成任何影响因子。评分口径按稿件类型（研究论文 / 综述 / 随笔 / 研究简报）
                  分别加权，权重冻结在代码里，保证不同月份入库的文章可比较。
                </p>
                <p className="text-xs text-muted-foreground">
                  结构要求（研究论文）：{rubric.data.profile_sections.research?.join('、')}；
                  参考文献下限 {rubric.data.min_references.research} 条；摘要 {rubric.data.abstract_band[0]}–
                  {rubric.data.abstract_band[1]} 字。
                </p>
              </CardContent>
            </Card>
          </div>
        )}
      </section>

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
          <span className="flex items-center gap-2 text-muted-foreground">
            <Lock className="h-4 w-4" /> 完整投稿规范见「作者指南」与「政策规范」。
          </span>
          <div className="flex gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to="/authors">作者指南</Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to="/policies">政策规范</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
