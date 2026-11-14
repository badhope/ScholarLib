import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowRight, Feather, Gavel, ReceiptText } from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { Card, CardContent } from '@/components/ui/card'

export const Route = createFileRoute('/desk')({
  component: DeskPage,
})

const PILLARS = [
  {
    title: '格式的尊严',
    body:
      '我们不把“学术”当成题材审查。论文要有可复核的方法与证据，荒诞文要有自洽的设定与完成度；两条轨道各自严格，但不互相冒充。',
    to: '/about',
    label: '本刊定位',
    icon: Feather,
  },
  {
    title: '评审不是投票',
    body:
      '五维评分要求逐项写理由与正文证据；没有证据的判断不计分。审稿人身份不公开，编辑的终审理由留在站内审计链里。',
    to: '/authors',
    label: '投稿与评审规范',
    icon: Gavel,
  },
  {
    title: '底刊也要有账本',
    body:
      '服务器、域名、存储与排版工具都要花钱。赞助完全自愿，不与投稿、评审、展示位置挂钩；本刊不卖版面。',
    to: '/support',
    label: '赞助去向',
    icon: ReceiptText,
  },
]

const NOTES = [
  {
    issue: '06',
    title: '新一卷从“把稿子修好”开始',
    body:
      '这一期按栏目分部分：Articles 收完整研究，Reviews 收综述与再评价；更正与撤稿单独成栏，不再混进正文。',
  },
  {
    issue: '05',
    title: '游戏是田野，也是镜子',
    body:
      '玩家在规则里 improvisation，研究者在截图与日志里找证据。认真玩，和认真研究，本来就不冲突。',
  },
  {
    issue: '04',
    title: '语言是人格的外套',
    body:
      '这一期我们关心口音、措辞、沉默，以及一个人在另一个语言里变成另一个自己的瞬间。',
  },
]

function DeskPage() {
  return (
    <div className="mx-auto w-full max-w-4xl">
      <Link
        to="/"
        className="mb-4 inline-flex items-center text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowRight className="mr-1 h-4 w-4 rotate-180" />
        返回首页
      </Link>

      <PageHeader
        title="主编桌"
        description="陆止于海，Rubbish 主编。这里不是期刊首页的主编专栏，而是公开的工作笔记：为什么做、怎么判断、钱花在哪。"
      />

      <div className="grid gap-4 sm:grid-cols-3">
        {PILLARS.map((pillar) => {
          const Icon = pillar.icon
          return (
            <RevealSection key={pillar.title}>
              <Card className="h-full">
                <CardContent className="flex h-full flex-col p-5">
                  <Icon className="h-5 w-5 text-primary" aria-hidden />
                  <h2 className="mt-3 font-serif text-lg font-medium">
                    {pillar.title}
                  </h2>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">
                    {pillar.body}
                  </p>
                  <Link
                    to={pillar.to}
                    className="mt-4 inline-flex items-center gap-1 text-sm text-primary hover:underline"
                  >
                    {pillar.label}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </CardContent>
              </Card>
            </RevealSection>
          )
        })}
      </div>

      <section className="mt-10">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-serif text-xl font-medium">最近的主编手记</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              每期卷首的几句话，按刊出顺序留档。
            </p>
          </div>
          <Link
            to="/archive"
            className="text-sm text-primary hover:underline"
          >
            全部卷期
          </Link>
        </div>
        <div className="space-y-3">
          {NOTES.map((note) => (
            <RevealSection key={note.issue}>
              <Link
                to="/archive/$issue"
                params={{ issue: note.issue }}
                className="block rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-muted/20"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      第 {Number(note.issue)} 期
                    </p>
                    <h3 className="mt-1 font-medium">{note.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                      {note.body}
                    </p>
                  </div>
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
                </div>
              </Link>
            </RevealSection>
          ))}
        </div>
      </section>

      <section className="mt-10 rounded-lg border border-dashed bg-muted/20 p-5">
        <h2 className="font-serif text-lg font-medium">编辑部的边界</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          主编对每篇稿件的最终去留有决定权，但不能替作者补实验、不能绕过审稿证据，也不能把赞助关系带进判断。
          可核对的口径写在
          <Link to="/policies" className="mx-1 text-primary hover:underline">
            期刊政策
          </Link>
          与
          <Link to="/about" search={{ tab: 'about' }} className="mx-1 text-primary hover:underline">
            关于本刊
          </Link>
          里；发现流程问题，可以通过
          <Link to="/feedback" className="mx-1 text-primary hover:underline">
            反馈墙
          </Link>
          留下可追踪的记录。
        </p>
      </section>
    </div>
  )
}
