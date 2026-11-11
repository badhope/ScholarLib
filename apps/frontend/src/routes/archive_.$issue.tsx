import { useMemo } from 'react'
import { createFileRoute, Link, notFound } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CalendarDays,
  Download,
  Feather,
  Printer,
  Quote,
} from 'lucide-react'
import { useIssuePlan, useResources } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { displayTypeLabel } from '@/lib/resource-labels'
import { issueTitle } from '@/lib/issue-meta'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/archive_/$issue')({
  component: IssuePage,
})

// 每期的“版面”配色：纸张底色、主色、副色。全部是印刷色，不用渐变。
const ISSUE_PALETTE: Record<
  string,
  { paper: string; ink: string; accent: string; rule: string; motif: string }
> = {
  '01': {
    paper: 'bg-[#f4efe4] dark:bg-[#191f1b]',
    ink: 'text-[#1f2a24] dark:text-[#e7e3d7]',
    accent: 'text-[#2f5d46] dark:text-[#a8cdb6]',
    rule: 'border-[#2f5d46]/30 dark:border-[#a8cdb6]/30',
    motif: 'from-[#2f5d46]/12 dark:from-[#a8cdb6]/12',
  },
  '02': {
    paper: 'bg-[#efe9dc] dark:bg-[#201a15]',
    ink: 'text-[#2a2118] dark:text-[#eadfd0]',
    accent: 'text-[#8a4b2f] dark:text-[#d19a72]',
    rule: 'border-[#8a4b2f]/30 dark:border-[#d19a72]/30',
    motif: 'from-[#8a4b2f]/12 dark:from-[#d19a72]/12',
  },
  '03': {
    paper: 'bg-[#e8eff1] dark:bg-[#131d22]',
    ink: 'text-[#152a33] dark:text-[#dbe8ec]',
    accent: 'text-[#1f5f73] dark:text-[#8ec6d6]',
    rule: 'border-[#1f5f73]/30 dark:border-[#8ec6d6]/30',
    motif: 'from-[#1f5f73]/12 dark:from-[#8ec6d6]/12',
  },
  '04': {
    paper: 'bg-[#f2eadf] dark:bg-[#1e1720]',
    ink: 'text-[#2b2019] dark:text-[#e9dce6]',
    accent: 'text-[#6b3f5e] dark:text-[#c99bc0]',
    rule: 'border-[#6b3f5e]/30 dark:border-[#c99bc0]/30',
    motif: 'from-[#6b3f5e]/12 dark:from-[#c99bc0]/12',
  },
  '05': {
    paper: 'bg-[#ecece3] dark:bg-[#1b1e16]',
    ink: 'text-[#1e241c] dark:text-[#e5e6d3]',
    accent: 'text-[#4a5d23] dark:text-[#b6c887]',
    rule: 'border-[#4a5d23]/30 dark:border-[#b6c887]/30',
    motif: 'from-[#4a5d23]/12 dark:from-[#b6c887]/12',
  },
  '06': {
    paper: 'bg-[#eceef4] dark:bg-[#161b24]',
    ink: 'text-[#1c2333] dark:text-[#e2e7f0]',
    accent: 'text-[#33456b] dark:text-[#a9b9dd]',
    rule: 'border-[#33456b]/30 dark:border-[#a9b9dd]/30',
    motif: 'from-[#33456b]/12 dark:from-[#a9b9dd]/12',
  },
}

const EDITOR_NOTES: Record<string, string> = {
  '06': '新一卷从“把稿子修好”开始。这一期按栏目分部分：Articles 收完整研究，Reviews 收综述与再评价；更正与撤稿单独成栏，不再混进正文。',
  '01': '创刊号不设题目。我们把“认真”与“好玩”放在同一张桌上，看看它们能不能好好说话。结果是：能。于是有了后面四期。',
  '02': '方法不是论文的装饰，而是让读者相信你的那条路。这一期里，有人用问卷，有人用田野，有人把模型拆到只剩骨架——争论本身比结论更好看。',
  '03': '实验室里最容易被忽略的，是人的耐心、手的温度，以及失败记录本上那些没有写进论文的页。把仪器关掉之后，研究还在继续。',
  '04': '语言既是工具，也是人格的外套。这一期我们关心口音、措辞、沉默，以及一个人在另一个语言里变成另一个自己的瞬间。',
  '05': '游戏是田野，也是镜子。玩家在规则里 improvisation，研究者在截图与日志里找证据。认真玩，和认真研究，本来就不冲突。',
}

const MONTHS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']

function fmtDate(iso: string | null): string {
  if (!iso) return '待定'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '待定'
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

function issueRange(items: { publish_at?: string | null }[]): string {
  const dates = items
    .map((r) => (r.publish_at ? new Date(r.publish_at) : null))
    .filter((d): d is Date => d !== null && !Number.isNaN(d.getTime()))
    .sort((a, b) => a.getTime() - b.getTime())
  if (!dates.length) return '滚动刊出'
  const a = dates[0]
  const b = dates[dates.length - 1]
  if (a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()) {
    return `${a.getFullYear()} 年 ${MONTHS[a.getMonth()]}月`
  }
  return `${a.getFullYear()} 年 ${MONTHS[a.getMonth()]}月 — ${b.getFullYear()} 年 ${MONTHS[b.getMonth()]}月`
}

function IssuePage() {
  const { issue: issueParam } = Route.useParams()
  // /archive/1 与 /archive/01 等价：期号在 API 里是两位补零字符串。
  const issue = issueParam.padStart(2, '0')
  const plan = useIssuePlan()
  const entry = plan.data?.entries.find((e) => e.issue === issue)
  const issueVolume = entry?.volume ?? plan.data?.volume
  const { data, isLoading, isError, refetch } = useResources(
    {
      volume: issueVolume,
      issue,
      page: 1,
      page_size: 100,
      sort: 'issue',
    },
    Boolean(issueVolume),
  )

  const items = data?.data ?? []
  const palette = ISSUE_PALETTE[issue] ?? ISSUE_PALETTE['01']
  const papers = useMemo(() => items.filter((r) => r.content_track === 'paper'), [items])
  const essays = useMemo(() => items.filter((r) => r.content_track !== 'paper'), [items])
  const highlights = useMemo(
    () => [...papers].sort((a, b) => (b.reads ?? 0) - (a.reads ?? 0)).slice(0, 3),
    [papers],
  )
  const disciplines = useMemo(
    () => Array.from(new Set(items.map((r) => r.discipline).filter(Boolean))),
    [items],
  )
  const special = items.filter((r) => r.is_special_issue).length
  const issueYear =
    entry?.publish_at && !Number.isNaN(new Date(entry.publish_at).getTime())
      ? new Date(entry.publish_at).getFullYear()
      : items[0]?.year ?? ''
  const PART_ORDER = ['Editorial', 'Features', 'Articles', 'Reviews', 'News & Views', 'Corrections']
  const paperParts = useMemo(() => {
    return papers.reduce<Record<string, typeof papers>>((acc, r) => {
      const key = r.issue_part || 'Articles'
      ;(acc[key] ??= []).push(r)
      return acc
    }, {})
  }, [papers])

  if (plan.isLoading) return <div className="p-10"><Loading /></div>
  if (!entry) throw notFound()

  const prev = plan.data?.entries.find((e) => Number(e.issue) === Number(issue) - 1 && e.state === 'live')
  const next = plan.data?.entries.find((e) => Number(e.issue) === Number(issue) + 1 && e.state === 'live')

  return (
    <div className={cn('min-h-screen', palette.paper, palette.ink)}>
      <div className="mx-auto max-w-6xl">
        {/* 报头 */}
        <div className="mb-8 flex flex-wrap items-end justify-between gap-3 border-b-2 border-current/20 pb-4">
          <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-end sm:gap-4">
            <Link to="/archive" className="mb-1 inline-flex items-center text-sm opacity-70 hover:opacity-100">
              <ArrowLeft className="mr-1 h-4 w-4" /> 卷期归档
            </Link>
            <div>
              <p className="font-serif text-3xl font-semibold tracking-tight sm:text-4xl">Rubbish</p>
              <p className="mt-1 text-[11px] uppercase tracking-[0.28em] opacity-60">A Journal of Serious Format & Free Subjects</p>
            </div>
          </div>
          <div className="text-right text-xs leading-relaxed opacity-70">
            <p>第 {issueVolume ?? '—'} 卷 · 第 {issue} 期</p>
            <p>{issueRange(items)}</p>
            <p>数字出版 · 滚动刊出</p>
          </div>
        </div>

        {/* 封面 + 本期信息 */}
        <div className="grid gap-8 lg:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]">
          <article className="relative overflow-hidden rounded-sm border border-current/15 bg-white/40 dark:bg-white/[0.05] p-6 shadow-[0_18px_50px_-30px_rgba(0,0,0,0.45)] sm:p-8">
            <div aria-hidden className={cn('pointer-events-none absolute inset-0 bg-gradient-to-br to-transparent', palette.motif)} />
            <div aria-hidden className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full border border-current/10" />
            <div aria-hidden className="pointer-events-none absolute -right-8 -top-8 h-36 w-36 rounded-full border border-current/10" />

            <div className="relative">
              <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.3em] opacity-60">
                <span>Vol. {issueVolume ?? '—'}</span>
                <span>{issueYear}</span>
              </div>
              <div className="mt-14">
                <p className="font-serif text-[86px] leading-[0.85] tracking-[-0.06em] sm:text-[116px]">
                  {String(Number(issue)).padStart(2, '0')}
                </p>
                <div className={cn('mt-6 border-t pt-4', palette.rule)}>
                  <p className={cn('text-lg font-semibold leading-snug', palette.accent)}>{issueTitle(issue)}</p>
                  <p className="mt-2 text-xs leading-relaxed opacity-70">第 {issueVolume ?? '—'} 卷 第 {issue} 期 · {issueRange(items)}</p>
                </div>
              </div>

              <div className="mt-16 flex items-end justify-between">
                <div>
                  <p className="font-serif text-2xl font-semibold">Rubbish</p>
                  <p className="mt-1 text-[10px] opacity-60">Rubbish 编辑部 · rubbish.argjiemi.cn</p>
                </div>
                <Feather className="h-7 w-7 opacity-30" />
              </div>
            </div>
          </article>

          <div className="flex flex-col justify-between gap-6">
            <div>
              <PageHeader
                title={`第 ${Number(issue)} 期 · ${issueTitle(issue)}`}
                description={entry.state === 'live' ? '本期已上线，滚动增补；以下目录按刊出顺序排列。' : '本期尚在排期，以下为已确定篇目。'}
              />
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">{items.length} 篇</Badge>
                <Badge variant="outline">{papers.length} 论文</Badge>
                <Badge variant="outline">{essays.length} 副刊</Badge>
                <Badge variant="outline">{disciplines.length} 个学科</Badge>
                {special > 0 && <Badge variant="outline" className="border-rose-300 text-rose-700">{special} 篇特别篇</Badge>}
              </div>
            </div>

            {/* 本期编后记 */}
            <div className="rounded-sm border border-current/15 bg-white/35 dark:bg-white/[0.04] p-5">
              <p className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] opacity-55">
                <Quote className="h-3.5 w-3.5" /> 本期编后记
              </p>
              <p className="mt-3 font-serif text-[15px] leading-8">{EDITOR_NOTES[issue] ?? '本期目录整理中。'}</p>
              <p className="mt-3 text-right text-xs opacity-55">— Rubbish 编辑部</p>
            </div>

            {/* 本期要目 */}
            {highlights.length > 0 && (
              <div>
                <p className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] opacity-55">
                  <BookOpen className="h-3.5 w-3.5" /> 本期要目
                </p>
                <div className="divide-y divide-current/10 border-y border-current/10">
                  {highlights.map((r, i) => (
                    <Link
                      key={r.id}
                      to="/catalog/$resourceId"
                      params={{ resourceId: String(r.id) }}
                      className="flex items-baseline gap-3 py-2.5 transition-opacity hover:opacity-70"
                    >
                      <span className="w-5 font-serif text-sm tabular-nums opacity-50">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1 font-medium">{r.title}</span>
                        <span className="mt-0.5 block text-xs opacity-60">{r.authors.join('、')}</span>
                      </span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 opacity-40" />
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 完整目录 */}
        <section className="mt-12">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b-2 border-current/20 pb-2">
            <h2 className="text-lg font-semibold tracking-tight">本期目录</h2>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => window.print()}>
                <Printer className="mr-1 h-3.5 w-3.5" /> 打印本期版面
              </Button>
              <a href={`/api/catalog/issues/1-${issue}/export?format=pdf&v=20`} className="inline-flex">
                <Button variant="outline" size="sm">
                  <Download className="mr-1 h-3.5 w-3.5" /> 整期下载
                </Button>
              </a>
            </div>
          </div>

          {isLoading ? (
            <Loading />
          ) : isError ? (
            <ErrorState message="加载本期目录失败" onRetry={() => refetch()} />
          ) : items.length === 0 ? (
            <EmptyState title="本期暂无文章" description="切换其他已上线期次，或浏览全部目录。" />
          ) : (
            <div className="space-y-8">
              {Object.entries(paperParts)
                .sort(([a], [b]) => {
                  const ia = PART_ORDER.indexOf(a)
                  const ib = PART_ORDER.indexOf(b)
                  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
                })
                .map(([part, rows]) => (
                  <div key={part}>
                    <p className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.24em] opacity-55">
                      <span className="h-1.5 w-1.5 rounded-full bg-current" /> {part} · {rows.length} 篇
                    </p>
                    <ol className="divide-y divide-current/10 border-y border-current/10">
                      {rows.map((r, idx) => (
                        <li key={r.id}>
                          <Link
                            to="/catalog/$resourceId"
                            params={{ resourceId: String(r.id) }}
                            className="group grid gap-2 py-4 transition-opacity hover:opacity-70 sm:grid-cols-[2.5rem_minmax(0,1fr)_11.5rem]"
                          >
                            <span className="font-serif text-sm tabular-nums opacity-50">{r.pages || String(idx + 1).padStart(2, '0')}</span>
                            <span className="min-w-0">
                              <span className="flex flex-wrap items-center gap-1.5">
                                <span className="font-medium leading-snug">{r.title}</span>
                                {r.is_special_issue && (
                                  <Badge variant="outline" className="border-rose-300 text-[10px] text-rose-700">特别篇</Badge>
                                )}
                              </span>
                              <span className="mt-1 block text-xs opacity-60">
                                {r.authors.join('、')} · {displayTypeLabel(r.type, r.content_category, r.content_track, r.track)}
                                {r.clc_code ? ` · CLC ${r.clc_code}` : ''}
                              </span>
                            </span>
                            <span className="whitespace-nowrap text-left text-[11px] opacity-55 sm:text-right">
                              {r.discipline}
                              {r.publish_at ? ` · ${fmtDate(r.publish_at)}` : ''}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              {essays.length > 0 && (
                <div>
                  <p className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.24em] opacity-55">
                    <span className="h-1.5 w-1.5 rounded-full bg-current" /> 副刊与随笔 · {essays.length} 篇
                  </p>
                  <ol className="divide-y divide-current/10 border-y border-current/10">
                    {essays.map((r, idx) => (
                      <li key={r.id}>
                        <Link to="/catalog/$resourceId" params={{ resourceId: String(r.id) }} className="group grid gap-2 py-4 transition-opacity hover:opacity-70 sm:grid-cols-[2.5rem_minmax(0,1fr)_11.5rem]">
                          <span className="font-serif text-sm tabular-nums opacity-50">{String(idx + 1).padStart(2, '0')}</span>
                          <span className="min-w-0 font-medium leading-snug">{r.title}</span>
                          <span className="text-[11px] opacity-55 sm:text-right">{r.discipline}</span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}
        </section>

        {/* 版权页 / 版本记录 */}
        <footer className="mt-14 border-t-2 border-current/20 pt-5">
          <div className="grid gap-6 text-xs leading-relaxed opacity-65 sm:grid-cols-3">
            <div>
              <p className="mb-2 font-semibold uppercase tracking-[0.2em]">出版</p>
              <p>Rubbish 编辑部</p>
              <p>纯数字出版 · 滚动刊出</p>
              <p>rubbish.argjiemi.cn</p>
            </div>
            <div>
              <p className="mb-2 font-semibold uppercase tracking-[0.2em]">编辑</p>
              <p>主编 陆止于海</p>
              <p>副主编 沈知非 · 顾荒唐</p>
              <p>编委 白鹿原上 · 林一苇 · R. 编辑部</p>
            </div>
            <div>
              <p className="mb-2 font-semibold uppercase tracking-[0.2em]">本版</p>
              <p>第 {issueVolume ?? '—'} 卷 第 {issue} 期 · {issueRange(items)}</p>
              <p>共 {items.length} 篇 · {papers.length} 篇论文 · {essays.length} 篇副刊</p>
              <p>版式：Rubbish 数字刊版式</p>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="flex gap-4">
              {prev ? (
                <Link to="/archive/$issue" params={{ issue: prev.issue }} className="inline-flex items-center gap-1 opacity-70 hover:opacity-100">
                  <ArrowLeft className="h-3.5 w-3.5" /> 第 {Number(prev.issue)} 期
                </Link>
              ) : null}
              {next ? (
                <Link to="/archive/$issue" params={{ issue: next.issue }} className="inline-flex items-center gap-1 opacity-70 hover:opacity-100">
                  第 {Number(next.issue)} 期 <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              ) : null}
            </div>
            <Link to="/archive" className="inline-flex items-center gap-1 opacity-70 hover:opacity-100">
              <CalendarDays className="h-3.5 w-3.5" /> 全部卷期
            </Link>
          </div>
        </footer>
      </div>
    </div>
  )
}
