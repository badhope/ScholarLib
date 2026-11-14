import { createFileRoute, Link, useSearch } from '@tanstack/react-router'
import { ArrowLeft, Building2, Globe, Mail, Newspaper, ScrollText } from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { CoverArt } from '@/components/common/cover-art'
import { RevealSection } from '@/components/common/reveal-section'
import { JournalMetricsPage } from './journal-metrics'

export const Route = createFileRoute('/about')({
  validateSearch: (search: Record<string, unknown>) => ({
    tab: search.tab === 'metrics' ? 'metrics' : 'about',
  }),
  component: AboutPage,
})

function AboutTabs({ active }: { active: 'about' | 'metrics' }) {
  return (
    <div className="mb-6 flex flex-wrap gap-2">
      <Link
        to="/about"
        search={{ tab: 'about' }}
        data-active={active === 'about'}
        className="seg-link px-3.5 py-2 text-sm font-medium"
      >
        关于本刊
      </Link>
      <Link
        to="/about"
        search={{ tab: 'metrics' }}
        data-active={active === 'metrics'}
        className="seg-link px-3.5 py-2 text-sm font-medium"
      >
        期刊指标
      </Link>
    </div>
  )
}

// 关于本刊：定位、岗位职责、刊史与联系方式。
// 本站是小型独立出版项目，不虚构编委姓名、头衔或机构。对外展示的是
// 真实存在的岗位与职责边界，而不是一套看起来像大刊的假阵容。

const BOARD = [
  {
    name: '主编岗',
    role: '终审',
    affiliation: '录用 · 修回 · 拒稿',
    note: '对每篇稿件的最终去留有决定权，并对评审口径的一致性负责。',
  },
  {
    name: '学术编辑岗',
    role: '学术质量',
    affiliation: '初筛 · 送审 · 复审',
    note: '判断选题是否成立、方法是否可复现、证据是否支撑结论；不替作者补实验。',
  },
  {
    name: '副刊编辑岗',
    role: '荒诞与文体',
    affiliation: '设定 · 结构 · 文风',
    note: '荒诞赛道按“设定是否新、内部是否自洽、执行是否完整”审，不套学术论文的样本量尺子。',
  },
  {
    name: '出版伦理岗',
    role: '诚信与更正',
    affiliation: '引用 · 数据 · 撤稿',
    note: '核查引用、数据与 AI 使用声明；受理更正、申诉与撤稿，利益冲突时回避。',
  },
  {
    name: '技术出版岗',
    role: '平台与存档',
    affiliation: '投稿 · 评审 · 阅读',
    note: '维护投稿、匿名评审、PDF/Word 导出与长期可读性；不介入学术判断。',
  },
  {
    name: '审稿人池',
    role: '同行评审',
    affiliation: '匿名 · 逐维证据',
    note: '按五维逐项写理由与正文证据；没有证据的判断不计分，审稿人身份不公开。',
  },
]

const TIMELINE = [
  ['2026 年 10 月', '创刊。首卷上线，投稿、匿名评审与在线阅读全流程开放。'],
  ['2026 年 11 月', '五入口与社区版块上线；学术轨与荒诞轨分轨评审，不再共用一把尺子。'],
  ['2026 年 11 月', 'RQS v5.0 收口：五维、逐维证据、分区硬门槛；90 分只留给顶刊级完成度。'],
  ['现在', 'ISSN 与 DOI 均不伪造：刊号申请中，官方 DOI 由作者自行决定是否注册。'],
]

function AboutPage() {
  const { tab } = useSearch({ from: '/about' })
  if (tab === 'metrics') {
    return (
      <div className="mx-auto w-full max-w-4xl">
        <AboutTabs active="metrics" />
        <JournalMetricsPage embedded />
      </div>
    )
  }
  return (
    <div className="mx-auto w-full max-w-4xl">
      <Link
        to="/"
        className="mb-4 inline-flex items-center text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        返回首页
      </Link>

      <PageHeader
        title="关于本刊"
        description="Rubbish 是一家严肃格式与自由主题兼容的开放获取学术期刊——用严格的格式，收纳一切认真的思考。"
      />
      <AboutTabs active="about" />

      <div className="space-y-10">
        <RevealSection className="grid items-center gap-6 sm:grid-cols-[auto_1fr]">
          <CoverArt seed="about" title="Rubbish" subtitle="Vol. 1 · 2026" className="w-full max-w-52" />
          <div>
            <p className="font-serif text-lg leading-relaxed">
              「学问的尊严在于格式，不在题材。」
            </p>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Rubbish（国际刊号申请中）创刊于 2026 年，是一份免费投稿、免费阅读、免费评审的
              纯开放获取期刊。我们收录标准学术研究，也正式收录传统刊物不敢收的脑洞选题——
              只要论证自洽、格式规范，玩梗也是一种严肃。
            </p>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
              不收版面费，不设学历门槛，不问出处。
            </p>
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">编辑部岗位与职责</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {BOARD.map((m) => (
              <Card key={m.name}>
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">{m.name}</p>
                    <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs text-primary">
                      {m.role}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{m.affiliation}</p>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{m.note}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            本站是小型独立出版项目，不虚构编委姓名、头衔或机构。上表是岗位与职责边界，
            不是一份看起来像大刊的假阵容；审稿人身份仅编辑部掌握。
          </p>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">刊史</h2>
          <ol className="mt-4 space-y-4 border-l border-border pl-5">
            {TIMELINE.map(([when, what]) => (
              <li key={what} className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-primary bg-background"
                />
                <p className="text-sm font-medium">{when}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">{what}</p>
              </li>
            ))}
          </ol>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">出版信息</h2>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2">
            {[
              { icon: Newspaper, label: '刊名', value: 'Rubbish（开放获取学术期刊）' },
              { icon: ScrollText, label: '刊号状态', value: 'ISSN 申请中；站内刊号不等同官方 DOI' },
              { icon: Globe, label: '出版形式', value: '纯数字出版 · 滚动刊出 + 不定期合卷' },
              { icon: ScrollText, label: '收录范围', value: '严肃格式与自由主题统一评审 · 学术/副刊/吐槽分类呈现' },
              { icon: Building2, label: '出版方', value: 'Rubbish 编辑部' },
            ].map(({ icon: Icon, label, value }) => (
              <div key={label} className="flex items-start gap-3 rounded-lg border bg-card p-4">
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <div>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-0.5 text-sm">{value}</dd>
                </div>
              </div>
            ))}
          </dl>
        </RevealSection>

        <RevealSection className="rounded-xl border bg-gradient-to-br from-primary/5 to-accent/10 p-8">
          <h2 className="flex items-center gap-2 text-lg font-medium">
            <Mail className="h-5 w-5 text-primary" />
            联系编辑部
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            投稿事宜请先读
            <Link to="/authors" className="mx-1 text-primary hover:underline">
              作者指南
            </Link>
            ；投诉与举报请在邮件主题注明「伦理」。一般咨询在 5 个工作日内回复。
          </p>
          <p className="mt-3 text-sm">
            编辑部邮箱：<a href="mailto:Rubbish_EB@qun.mail.163.com" className="font-medium text-primary hover:underline">Rubbish_EB@qun.mail.163.com</a>
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            本刊无广告、无付费墙，运行成本靠读者自愿支持：
            <Link to="/support" className="ml-1 text-primary hover:underline">
              支持本刊
            </Link>
          </p>
        </RevealSection>
      </div>
    </div>
  )
}
