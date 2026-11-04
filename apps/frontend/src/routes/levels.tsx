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

// RQS v3.0 的 13 档等级配色（A+ ~ F，见 quality/rubric.py GRADE_BANDS）。缺键兜底走末尾的 `?? ''` 链式默认：
// 新增档位时这里同步即可，页面不会因缺键崩坏。
const GRADE_STYLES: Record<string, string> = {
  'A+': 'bg-amber-300 text-amber-950',
  A: 'bg-amber-200/80 text-amber-950',
  'A-': 'bg-amber-100 text-amber-900',
  'B+': 'bg-primary/20 text-primary',
  B: 'bg-primary/15 text-primary',
  'B-': 'bg-primary/10 text-primary',
  'C+': 'bg-muted text-foreground',
  C: 'bg-muted text-foreground',
  'C-': 'bg-muted text-foreground',
  'D+': 'bg-muted text-muted-foreground',
  D: 'bg-muted text-muted-foreground',
  'D-': 'bg-muted text-muted-foreground',
  F: 'bg-muted text-foreground',
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
        title="身份体系与质量规范"
        description="四种身份、贡献积分与论文质量评分口径。全部公开、全部冻结，改版需升版本号。"
      />

      {/* 身份 vs 积分：两者的区别是这一页最重要的一句话 */}
      <Card className="border-primary/25 bg-primary/[0.03]">
        <CardContent className="space-y-3 py-5 text-sm leading-relaxed">
          <p className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-primary" />
            身份管权限，积分只是荣誉
          </p>
          <p className="text-muted-foreground">
            本刊有<strong className="text-foreground">四种身份</strong>：读者、作者、审稿人、编辑。
            能做什么由身份决定——读者注册即得，作者确认《投稿规范》即得，
            审稿人与编辑由编辑部授予。<strong className="text-foreground">积分（XP）
            不再决定任何权限</strong>，它只回答"这个人参与了多少"：谁在持续读、
            持续写、持续审。把参与度当成权限，只会让新读者在"还差 28 积分"
            的提示里失去兴趣。
          </p>
          <p className="text-muted-foreground">
            申请审稿人走「申请 → 编辑部审批」；编辑由编辑部按贡献提拔，不开放申请。
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
          <BookOpen className="h-4 w-4" /> 论文质量评分（RQS v3.0）
        </h2>
        {rubric.isLoading ? (
          <Loading />
        ) : rubric.isError || !rubric.data ? (
          <ErrorState message="加载评分规范失败" onRetry={() => rubric.refetch()} />
        ) : (
          <div className="space-y-4">
            {/* 维度说明：v3.0 的核心变化是「评价值」而非「评形式」，
                必须让读者看懂每一维到底在问什么。 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">评价维度（每一维都要求评分者写理由）</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {rubric.data.dimensions.map((d) => (
                    <li key={d.key} className="rounded-md border bg-muted/30 px-3 py-2">
                      <p className="text-[13px] font-medium">{d.label}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {(d as { hint?: string }).hint}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
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
                  七个学术价值维度加权满分 100（v3.0 严厉客观制：A+ 95–100 为典范水准，
                  极少达到，多数稿子落在 C/D）。权重按稿件类型（研究论文 / 综述 / 随笔 /
                  研究简报）分别设定，冻结在代码里，保证不同月份入库的文章可比较。
                </p>
                <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                  <strong className="text-foreground">处置语义（v3.0）</strong>：
                  F（40–54）= 合格，可以阅读、仍可发表；55–57（D-）为边缘稿，提示编辑谨慎；
                  <strong className="text-foreground">只有低于 40 分才不予发表</strong>——
                  不合格稿件打回审稿人补审或要求作者修改，把逐条修改要求发给作者。
                </p>
                <p className="text-xs text-muted-foreground">
                  学术诚信维度为<strong>一票否决</strong>：发现编造数据或引用，该维度记 0 分，
                  全篇按不合格处理（不予发表）——无论其他维度多高。
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
