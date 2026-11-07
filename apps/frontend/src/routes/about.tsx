import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Building2, Globe, Mail, Newspaper, ScrollText } from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { CoverArt } from '@/components/common/cover-art'
import { RevealSection } from '@/components/common/reveal-section'

export const Route = createFileRoute('/about')({
  component: AboutPage,
})

// 关于本刊：定位、理念、编委会、卷期与联系方式。
// 编委会为编辑部化名的虚构阵容（本刊自己就是一本正经与玩梗并存的刊物，
// 编委信息按刊物设定的方式呈现，不指向任何真实人物）。

const BOARD = [
  {
    name: '陆止于海',
    role: '主编',
    affiliation: 'Rubbish 编辑部 · 风格观察站',
    note: '主张「严肃的格式，自由的主题」，创刊口号撰写人。',
  },
  {
    name: '沈知非',
    role: '副主编 · 学术质量',
    affiliation: '开放获取出版研究室',
    note: '负责学术质量与评审流程：统一标准，离谱选题也不能放松格式。',
  },
  {
    name: '顾荒唐',
    role: '副主编 · 选题把关',
    affiliation: '应用风格研究中心（筹）',
    note: '负责选题把关与内容风格定位，格言：「可以离谱，不可以伤人」。',
  },
  {
    name: '白鹿原上',
    role: '编委 · 审稿协调',
    affiliation: '编辑部',
    note: '维护双盲评审的匿名管道与审稿人队伍。',
  },
  {
    name: '林一苇',
    role: '编委 · 出版伦理',
    affiliation: '编辑部',
    note: '负责学术不端调查与撤稿流程。',
  },
  {
    name: 'R. 编辑部',
    role: '编委 · 技术出版',
    affiliation: 'Rubbish 平台组',
    note: '维护投稿、评审与阅读系统，本站即其作品。',
  },
]

const TIMELINE = [
  ['2026 年 10 月', '创刊。首卷第 1 期上线，投稿、双盲评审、在线阅读全流程开放。'],
  ['2026 年 10 月', '引入 R 因子，建立基于站内互动的全刊热度指标。'],
  ['今天', '等你投稿。'],
]

function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl py-8">
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
          <h2 className="text-xl font-medium">编辑部</h2>
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
            编委署名为编辑部化名。本刊实行双盲评审，真实审稿人身份仅编辑部掌握。
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
              { icon: Globe, label: '出版形式', value: '纯数字出版 · 滚动刊出 + 不定期合卷' },
              { icon: ScrollText, label: '收录范围', value: '严肃格式与自由主题统一评审 · 学术/娱乐/吐槽分类呈现' },
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
            编辑部邮箱：<span className="font-medium">editorial@argjiemi.cn</span>
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
