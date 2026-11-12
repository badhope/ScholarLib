import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import {
  ArrowRight,
  BadgeCheck,
  Coins,
  Crosshair,
  Crown,
  Eye,
  FileText,
  Info,
  PenLine,
  ShieldAlert,
  ShieldCheck,
  User,
  Users,
} from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/levels')({
  beforeLoad: () => {
    throw redirect({ to: '/rules', search: { tab: 'levels' } })
  },
  component: LevelsPage,
})

// ---------------------------------------------------------------------------
// 口径来源（与后端保持一致，前端只读展示，不参与任何计算）：
//   - 权限轴：apps/backend/app/api/me.py  PERMISSION_LABELS / _PERMISSIONS
//   - 等级阈值：apps/backend/app/modules/gamification/levels_axis.py  LEVEL_BANDS
//   - 积分规则：同文件 POINT_RULES
// 术语与 /me 页严格对齐：identity key = author / reviewer / editor；
// 权限层 = user / reviewer / editor / editor_in_chief。
// ---------------------------------------------------------------------------

type PermissionKey = 'visitor' | 'user' | 'reviewer' | 'editor' | 'editor_in_chief'

interface PermissionLayer {
  key: PermissionKey
  label: string
  icon: typeof Eye
  /** 该层「新增」的能力（不含从下一层继承来的）。展示时按层级累计。 */
  adds: string[]
  granted: string
  tint: string
}

const PERMISSION_LAYERS: PermissionLayer[] = [
  {
    key: 'visitor',
    label: '访客',
    icon: Eye,
    adds: ['浏览公开目录与已发表文章摘要'],
    granted: '无需注册',
    tint: 'bg-muted text-muted-foreground',
  },
  {
    key: 'user',
    label: '用户（读者 / 作者）',
    icon: User,
    adds: [
      '阅读全部已发表文章、下载 PDF / Markdown',
      '收藏到阅读列表、关注作者',
      '发表评论与论坛讨论',
      '提交稿件（需先确认当前版《投稿规范》）',
    ],
    granted: '注册即得；确认规范后获得作者轨',
    tint: 'bg-muted text-foreground',
  },
  {
    key: 'reviewer',
    label: '审稿人',
    icon: BadgeCheck,
    adds: [
      '接收审稿邀请',
      '阅读匿名稿并提交评审意见与评分',
      '查看自己完成的审稿历史',
    ],
    granted: '编辑部审批授予',
    tint: 'bg-sky-500/15 text-sky-600',
  },
  {
    key: 'editor',
    label: '栏目编辑',
    icon: PenLine,
    adds: [
      '初审稿件、分配与撤销审稿人',
      '编排卷期、管理目录',
      '查看编辑工作台',
    ],
    granted: '编辑部按贡献任命',
    tint: 'bg-amber-500/15 text-amber-600',
  },
  {
    key: 'editor_in_chief',
    label: '主编',
    icon: Crown,
    adds: [
      '作出录用 / 修回 / 拒稿最终决定',
      '审批角色申请与作者认领',
      '站点设置与审计日志',
    ],
    granted: '编辑部最高任命',
    tint: 'bg-primary text-primary-foreground',
  },
]

interface LevelBandRow {
  label: string
  range: string
  note: string
}

interface LevelTrack {
  identity: 'author' | 'reviewer' | 'editor'
  name: string
  unit: string
  bands: LevelBandRow[]
}

const LEVEL_TRACKS: LevelTrack[] = [
  {
    identity: 'author',
    name: '作者',
    unit: '分',
    bands: [
      { label: 'L1', range: '0 – 49', note: '起步作者' },
      { label: 'L2', range: '50 – 149', note: '稳定投稿' },
      { label: 'L3', range: '150 – 299', note: '持续贡献' },
      { label: 'L4', range: '300 – 499', note: '核心作者' },
      { label: 'L5', range: '500 及以上', note: '资深作者' },
    ],
  },
  {
    identity: 'reviewer',
    name: '审稿人',
    unit: '份审稿报告',
    bands: [
      { label: 'R1', range: '0 – 2', note: '新晋审稿人' },
      { label: 'R2', range: '3 – 7', note: '成熟审稿人' },
      { label: 'R3', range: '8 及以上', note: '资深审稿人' },
    ],
  },
  {
    identity: 'editor',
    name: '栏目编辑',
    unit: '分',
    bands: [
      { label: 'E1', range: '0 – 19', note: '见习编辑' },
      { label: 'E2', range: '20 – 59', note: '责任编辑' },
      { label: 'E3', range: '60 及以上', note: '资深编辑' },
    ],
  },
]

interface PointRule {
  identity: 'author' | 'reviewer' | 'editor'
  label: string
  delta: number
  counts: boolean
}

const POINT_RULES: PointRule[] = [
  { identity: 'author', label: '正式论文被录用', delta: 60, counts: true },
  { identity: 'author', label: '作者认领审核通过', delta: 20, counts: true },
  { identity: 'author', label: '副刊 / 吐槽类稿件录用', delta: 0, counts: false },
  { identity: 'reviewer', label: '按时完成审稿报告并提交', delta: 1, counts: true },
  { identity: 'editor', label: '对稿件作出编辑裁决', delta: 8, counts: true },
]

const IDENTITY_BADGE: Record<string, string> = {
  author: 'bg-muted text-foreground',
  reviewer: 'bg-sky-500/15 text-sky-600',
  editor: 'bg-amber-500/15 text-amber-600',
}

const IDENTITY_NAME: Record<string, string> = {
  author: '作者轨',
  reviewer: '审稿人轨',
  editor: '编辑轨',
}

export function LevelsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-10 sm:px-6">
      <PageHeader
        title="身份与等级体系"
        description="两条轴：身份决定你能做什么；等级只在你自己的身份里涨。互不混排、互不兑换。"
      />

      {/* 双轴总览：一句话讲清楚这一页在说什么 */}
      <Card className="border-primary/25 bg-primary/[0.03]">
        <CardContent className="space-y-3 py-5 text-sm leading-relaxed">
          <p className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-primary" />
            先看身份，再看等级
          </p>
          <p className="text-muted-foreground">
            <strong className="text-foreground">身份（权限轴）</strong>回答的是「你能做什么」——
            从访客到主编共五层，高层级天然包含低层级的全部权限。
            <strong className="text-foreground">等级（激励轴）</strong>回答的是「你在当前身份里做得多深」——
            作者 L1–L5、审稿人 R1–R3、栏目编辑 E1–E3，三套数字各算各的。
          </p>
          <p className="text-muted-foreground">
            一个人可以同时是作者和审稿人，但你永远不会看到「作者 L3 比审稿人 R2 高 / 低」这种比较——
            它们不在同一根轴上。
          </p>
        </CardContent>
      </Card>

      {/* 一、权限轴五层 */}
      <section>
        <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
          <Users className="h-4 w-4" /> 权限轴：五层身份
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          大身份包含小身份的全部权限。例如成为主编，就同时拥有栏目编辑、审稿人、用户的所有能力；
          主编就是主编，不再额外叠加「我是编辑」这种小标签。
        </p>
        <div className="space-y-3">
          {PERMISSION_LAYERS.map((layer, idx) => {
            const Icon = layer.icon
            return (
              <div
                key={layer.key}
                className="relative rounded-xl border bg-card p-4 sm:p-5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-semibold',
                      layer.tint,
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {idx + 1}. {layer.label}
                  </span>
                  <Badge variant="outline" className="text-[10px]">
                    {layer.granted}
                  </Badge>
                </div>
                <p className="mt-2 text-xs font-medium text-muted-foreground">
                  本层新增能力：
                </p>
                <ul className="mt-1 grid gap-1 text-sm text-muted-foreground sm:grid-cols-2">
                  {layer.adds.map((c) => (
                    <li key={c} className="flex items-start gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                      <span className="min-w-0 break-words">{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </section>

      {/* 二、等级轴三套 */}
      <section>
        <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
          <Crosshair className="h-4 w-4" /> 等级轴：三套独立阈值表
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          等级只在同一身份内累加。下表数值与后端配置一致，不同身份之间不比较、不并列、不进同一榜单。
        </p>
        <div className="grid gap-4 lg:grid-cols-3">
          {LEVEL_TRACKS.map((track) => (
            <Card key={track.identity} className="flex flex-col">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  <span className="flex items-center gap-2">
                    <Badge
                      variant="secondary"
                      className={cn('text-[11px]', IDENTITY_BADGE[track.identity])}
                    >
                      {track.name}
                    </Badge>
                  </span>
                  <span className="text-xs font-normal text-muted-foreground">
                    单位：{track.unit}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex-1 pt-0">
                <ul className="divide-y">
                  {track.bands.map((band) => (
                    <li
                      key={band.label}
                      className="flex items-center justify-between gap-2 py-2 text-sm"
                    >
                      <span className="inline-flex h-6 w-10 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold tabular-nums text-primary">
                        {band.label}
                      </span>
                      <span className="tabular-nums text-muted-foreground">
                        {band.range}
                      </span>
                      <span className="hidden text-xs text-muted-foreground sm:inline">
                        {band.note}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* 三、积分怎么涨 */}
      <section>
        <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold">
          <Coins className="h-4 w-4" /> 积分怎么涨：只服务同身份升级
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">
          下面这些行为会计入对应身份的积分。同一篇稿件 / 同一份审稿只计一次，重复触发不重复加分。
        </p>
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y">
              {POINT_RULES.map((rule, i) => (
                <li
                  key={i}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <Badge
                      variant="secondary"
                      className={cn('shrink-0 text-[11px]', IDENTITY_BADGE[rule.identity])}
                    >
                      {IDENTITY_NAME[rule.identity]}
                    </Badge>
                    <span className="min-w-0 break-words">{rule.label}</span>
                  </div>
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {rule.counts ? (
                      <>+{rule.delta} 分</>
                    ) : (
                      <span className="text-xs">
                        <ShieldAlert className="mr-1 inline h-3.5 w-3.5" />
                        不计分（仅记活跃度）
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <p className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:text-amber-400">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            副刊 / 吐槽类稿件（随笔、吐槽、非正式论文）录用后只记一条活跃度流水，
            <strong>不推进任何等级</strong>，也不折算成作者轨积分。想在作者轨升级，靠的是正式论文与认领。
          </span>
        </p>
      </section>

      {/* 四、三条红线 */}
      <section>
        <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
          <ShieldAlert className="h-4 w-4" /> 三条硬规则
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            {
              title: '等级不跨身份比较',
              body: '作者 L 与审稿人 R、编辑 E 是三套独立数字，不排进同一张表，也不放在同一个卡片里对比。',
            },
            {
              title: '不设全站排行榜',
              body: '全站总榜、积分榜、名人墙一律不做。个人页面只显示你当前身份 + 该身份等级 + 距下一级还差多少。',
            },
            {
              title: '积分不兑换权限',
              body: '积分高不会自动变成审稿人或编辑。权限走五层身份，由编辑部授予；积分只在你已有身份内推动等级。',
            },
          ].map((rule) => (
            <Card key={rule.title} className="bg-muted/30">
              <CardContent className="space-y-1.5 py-4">
                <p className="text-sm font-semibold">{rule.title}</p>
                <p className="text-xs leading-relaxed text-muted-foreground">{rule.body}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* 结尾 CTA */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
          <span className="flex items-center gap-2 text-muted-foreground">
            <FileText className="h-4 w-4" />
            登录后在「我的」页查看你当前的身份与各身份等级进度。
          </span>
          <Button asChild size="sm">
            <Link to="/me">
              去看我的身份
              <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
