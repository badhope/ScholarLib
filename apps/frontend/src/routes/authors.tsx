import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Download,
  FileText,
  PenLine,
  ShieldCheck,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useAuth } from '@/hooks/use-auth'
import { useAcceptAuthorRules, useGamificationProfile } from '@/hooks/api/use-modules'

export const Route = createFileRoute('/authors')({
  // 投稿指南与操作指南合并为 /guide 的两个页签，旧入口只做跳转。
  beforeLoad: () => {
    throw redirect({ to: '/guide', search: { tab: 'authors' } })
  },
  component: AuthorsPage,
})

const ACCEPT_CRITERIA: Array<{ title: string; body: string }> = [
  {
    title: '原创性',
    body: '稿件必须为作者原创且未在其他刊物或平台发表（预印本不在此列）。一稿多投在审稿期内视为违规。',
  },
  {
    title: '可核查性',
    body: '涉及数据、实验或调查的稿件，应能说明方法与来源；我们不做开放式数据强制存放，但拒绝无法自洽的凭空数据。',
  },
  {
    title: '学术规范',
    body: '引用他人观点必须注明出处；署名作者须对内容有实质贡献；AI 辅助写作需在致谢中声明。',
  },
  {
    title: '清晰的写作',
    body: '论文轨（学术论文与荒诞论文）都要写全摘要、引言、方法（或论证）、结论与参考文献；副刊轨不强制论文范式，标题、正文和必要说明清楚即可。',
  },
]

const ACCEPTED_KINDS = [
  {
    icon: BookOpenCheck,
    title: '论文轨 · 学术 / 荒诞',
    body: '论文内部再分两区：学术论文做真实研究（实证、综述、方法论、案例分析）；荒诞论文严格按论文格式，用可核查材料一本正经地论证荒诞命题。两者都走匿名同行评审、五维两段式百分制评分，计分并进入 R 因子。',
  },
  {
    icon: Sparkles,
    title: '副刊轨',
    body: '小说、随笔、评论、诗歌、指南和整活，统一归入 Rubbish Supplement（副刊）。副刊是正式期刊的一种，不走学术同行评审、不计分、不进 R 因子；只做格式、版权与社区规范检查。发表后按小说故事、评论杂谈、指南攻略、随笔、吐槽细分。',
  },
]

const NOT_ACCEPTED = [
  '违反法律法规或伤害特定群体的内容',
  '抄袭、代写、数据造假',
  '纯广告或营销软文（再好玩也不行）',
  '针对真实个人的影射或骚扰',
  '已在外部刊物正式发表的内容',
]

export function AuthorsPage() {
  const { isAuthenticated } = useAuth()
  const profile = useGamificationProfile({ enabled: isAuthenticated })
  const acceptRules = useAcceptAuthorRules()
  const rulesAccepted = profile.data?.rules_accepted ?? false

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
        title="作者指南"
        description="投稿要求、结构规范、图表与引用细则、格式模板——一份读完就能动笔的指南。"
      />

      <div className="space-y-10">
        <RevealSection>
          <h2 className="text-xl font-medium">收录范围</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Rubbish 是一家严肃格式与自由主题兼容的开放获取期刊。所有稿件共用同一套伦理底线与排版清洁标准，
            但分两条轨道运行：论文轨再分「学术论文 / 荒诞论文」两个独立区，都走同行评审与百分制计分；副刊轨独立成刊，不用论文体，只做格式与合规检查，不计分、不进 R 因子。
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {ACCEPTED_KINDS.map(({ icon: Icon, title, body }) => (
              <Card key={title} className="h-full">
                <CardContent className="p-5">
                  <p className="flex items-center gap-2 font-medium">
                    <Icon className="h-4 w-4 text-primary" />
                    {title}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">收录标准</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {ACCEPT_CRITERIA.map((c, i) => (
              <Card key={c.title}>
                <CardContent className="p-5">
                  <p className="text-sm font-medium">
                    <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs text-primary">
                      {i + 1}
                    </span>
                    {c.title}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">发表要求</h2>
          <div className="mt-4 grid gap-6 lg:grid-cols-2">
            <div className="rounded-lg border bg-card p-5">
              <h3 className="flex items-center gap-2 text-sm font-medium text-primary">
                <CheckCircle2 className="h-4 w-4" />
                我们要求
              </h3>
              <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
                <li>· 稿件为 Markdown / PDF / Word 任一格式，图表清晰</li>
                <li>· 中文为主，英文稿件亦可（目录会标注语言）</li>
                <li>· 摘要 200–350 字，关键词 4–6 个，含 JEL/MSC 分类更佳</li>
                <li>· 篇幅分三档：短篇 2,500–5,000 字 / 中篇 5,000–8,000 字 / 长篇 8,000 字以上（须经「特别篇」篇幅特许）</li>
                <li>· 结构含「方法（或论证框架）」与「讨论」两节，缺一不可</li>
                <li>· 图表编号 + 标题 + 正文引用；图 ≥ 300 dpi，表用三线表</li>
                <li>· 参考文献 ≥ 8 条，全部可在 DOI 或公开数据库核实，格式统一为 GB/T 7714-2015</li>
                <li>· 必须有「数据可用性」「作者贡献」「利益冲突」三段声明</li>
                <li>· 全体作者同意署名与排序，投稿后不可增删作者（只可勘误）</li>
              </ul>
            </div>
            <div className="rounded-lg border bg-card p-5">
              <h3 className="flex items-center gap-2 text-sm font-medium text-destructive">
                <XCircle className="h-4 w-4" />
                我们不要求
              </h3>
              <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
                <li>· 版面费、审稿费、加速费——本刊一切免费</li>
                <li>· 单位介绍信、导师签字、纸质公函</li>
                <li>· 作者职称、头衔、学历门槛（本科生与教授同等待遇）</li>
                <li>· 英文摘要（中文稿件不需要凑英文 ABSTRACT）</li>
                <li>· 基金项目编号（有就写，没有不扣分）</li>
                <li>· CLC 分类号等纸媒时代的遗产</li>
              </ul>
            </div>
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">不予收录</h2>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {NOT_ACCEPTED.map((item) => (
              <li
                key={item}
                className="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-muted-foreground"
              >
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive/70" />
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            玩梗研究同样适用伦理底线：可以离谱，不可以伤人。详见
            <Link to="/policies" className="mx-1 text-primary hover:underline">
              期刊政策与社区规范
            </Link>
            。
          </p>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">结构规范</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            本刊采用「结构化写作」：每一节都有明确的功能，不按功能写的稿件会在初审被退回补全，
            而不是直接拒稿。以下规范对全部稿件同等适用——玩梗选题的论证同样要经得起结构审查。
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {[
              {
                title: '必须有的六节',
                body: '引言（现象—缺口—贡献）、相关工作（有立场的分组梳理）、方法或论证框架、结果、讨论（含义—局限—含义）、结论。缺「方法」与「讨论」两节直接退修。',
              },
              {
                title: '摘要四要素',
                body: '200–350 字，写清「问题 / 方法 / 结果 / 结论」。不写「本文具有重要意义」这类空转句；玩梗选题也要让读者读完摘要就知道你认真地在论证什么。',
              },
              {
                title: '图表三原则',
                body: '自明（不读正文也能懂）、有编号与标题（图下表上）、正文显式引用。图 ≥ 300 dpi；表用三线表，不用竖线；图注末尾写数据来源。',
              },
              {
                title: '引用纪律',
                body: 'GB/T 7714-2015 顺序编码制，≥ 8 条，全部可在 DOI 或公开数据库核实。编造引用一经发现即退稿并记入作者信用记录——这条没有例外，玩梗选题也一样。',
              },
              {
                title: '三段声明',
                body: '数据与代码可用性（已公开 / 可索取 / 受限说明）、作者贡献（CRediT 分类）、利益冲突。三段都不能空着，写「无」也是写。',
              },
              {
                title: '篇幅三档',
                body: '短篇 2,500–5,000 字、中篇 5,000–8,000 字、长篇 8,000 字以上。超过 8,000 字默认不予刊发，只有编辑部/审稿人确认必要的「特别篇」才可特许，并在目录与正文页显式标注。短篇不因短而减分，长篇不因长而加分，但内容必须撑得住。',
              },
            ].map((c) => (
              <Card key={c.title}>
                <CardContent className="p-5">
                  <p className="text-sm font-medium">{c.title}</p>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            完整细则见《Rubbish 编辑规范》（可在下方模板首段找到自检清单）；
            模板为 Markdown 与 LaTeX 两版，等价，任选其一。
          </p>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">关于 AI 辅助写作</h2>
          <div className="mt-3 space-y-3 text-sm leading-relaxed text-muted-foreground">
            <p>
              本刊不禁止 AI 辅助写作，但禁止<strong className="text-foreground">用 AI 掩盖内容的空洞</strong>。
              两者的区别在初审时很容易看出来：真正改过的稿子有具体的人、地、时与真实数据；
              生成后没碰过的稿子，语法无瑕但读完不知道作者到底做了什么。
            </p>
            <p>
              我们的判断只看三件事：<strong className="text-foreground">因果是否成立</strong>、
              <strong className="text-foreground">引用是否可核实</strong>、
              <strong className="text-foreground">结论是否超出证据</strong>。
              这三项不过，文风再好也退；三项都过，用不用 AI 不是问题。
            </p>
            <p>
              完整的核查项（含常见症状与改写示例）见下方「AI 写作核查表」。
              我们不使用 AI 检测工具的分数做判定——已有研究显示这类工具对非英语母语作者存在系统性误判。
            </p>
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">格式模板</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            不强制使用，但用模板能显著降低编辑部的排版时间——你的论文会更快见刊。
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                href: '/templates/rubbish-submission-template.docx',
                icon: FileText,
                title: 'Word 模板（推荐）',
                body: '官方排版模板，直接在样式上填写即可：题名/作者/摘要/关键词/三级标题/图表题注/利益冲突声明/国标参考文献一应俱全。',
              },
              {
                href: '/templates/rubbish-submission-template.md',
                icon: FileText,
                title: 'Markdown 模板',
                body: '结构齐全，站点导入与在线阅读器最友好；喜欢纯文本写作流可用它。',
              },
              {
                href: '/templates/rubbish-submission-template.tex',
                icon: FileText,
                title: 'LaTeX 模板',
                body: '公式多的正经研究用它；xelatex 编译出 PDF 后直接投稿。',
              },
              {
                href: '/templates/rubbish-submission-template-word.md',
                icon: FileText,
                title: 'Word 排版要求',
                body: '页面/字体/标题层级/三线表/参考文献的逐项设置说明，与 Word 模板配套。',
              },
              {
                href: '/templates/rubbish-editorial-standards.md',
                icon: BookOpenCheck,
                title: '编辑规范（完整版）',
                body: '篇幅分档、结构规范、图表与引用细则、提交清单——投稿前必读。',
              },
              {
                href: '/templates/rubbish-ai-writing-checklist.md',
                icon: ShieldCheck,
                title: 'AI 写作核查表',
                body: '把「AI 味」逐条拆成可检查的项：因果、引用、数据、语气、结构。含编辑部判定流程。',
              },
            ].map((t) => (
              <Card key={t.href}>
                <CardContent className="flex items-start gap-4 p-5">
                  <t.icon className="mt-0.5 h-8 w-8 shrink-0 text-primary/70" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{t.title}</p>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t.body}</p>
                    <a
                      href={t.href}
                      download
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      <Download className="h-3 w-3" />
                      下载模板
                    </a>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </RevealSection>

        <RevealSection>
          <h2 className="text-xl font-medium">评审流程</h2>
          <ol className="mt-4 space-y-3">
            {[
              ['提交', '注册后在「我的提交」创建稿件并上传文件，状态变为「待审」。'],
              ['初审', '编辑部检查格式与收录标准，不合适会被退回并附理由。'],
              ['同行评审', '匿名评审：默认双方互不知情；编辑可按稿件选择单盲或双盲。'],
              ['修订', '小修/大修意见返回作者；修订重投不另收任何费用。'],
              ['录用见刊', '录用后进入刊前整理，刊出后自动进入目录并计入期刊指标。'],
            ].map(([title, body], i) => (
              <li key={title} className="flex gap-4">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">
                  {i + 1}
                </span>
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-4 flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            每次裁决与版本变更均写入审计日志；审稿过程中编辑部不会向任何人泄露你的稿件内容。
          </p>
        </RevealSection>

        <RevealSection className="rounded-xl border bg-gradient-to-br from-primary/5 to-accent/10 p-8 text-center">
          <PenLine className="mx-auto h-8 w-8 text-primary" />
          <h2 className="mt-3 text-xl font-medium">准备好了？</h2>
          {!isAuthenticated ? (
            <>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                注册后阅读并确认投稿规范，即可投稿，无需达到特定等级。
              </p>
              <Button asChild className="mt-5">
                <Link to="/register">
                  免费注册 <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </>
          ) : rulesAccepted ? (
            <>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                你已确认本版《投稿与编辑规范》，现在可以新建投稿了。
              </p>
              <Button asChild className="mt-5">
                <Link to="/submissions">
                  进入我的投稿
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </>
          ) : (
            <>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                阅读本页后，请确认投稿规范以开放投稿入口。确认可获得积分，等级按积分规则计算。
              </p>
              <Button
                className="mt-5"
                disabled={acceptRules.isPending}
                onClick={() =>
                  acceptRules.mutate(undefined, {
                    onSuccess: () => toast.success('已确认投稿规范，投稿权限已解锁'),
                    onError: () => toast.error('确认失败，请稍后重试'),
                  })
                }
              >
                {acceptRules.isPending ? '提交中…' : '我已读完并接受投稿规范'}
                <ArrowRight className="h-4 w-4" />
              </Button>
            </>
          )}
        </RevealSection>
      </div>
    </div>
  )
}
