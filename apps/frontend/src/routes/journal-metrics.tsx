import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { ArrowLeft, BookOpen, Download, Lock, Quote, TrendingUp } from 'lucide-react'
import { useJournalMetrics } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Card, CardContent } from '@/components/ui/card'
import { typeLabel } from '@/lib/resource-labels'
import { DisciplineBar, EngagementRadar } from '@/components/charts/metrics-charts'

export const Route = createFileRoute('/journal-metrics')({
  beforeLoad: () => {
    throw redirect({ to: '/about', search: { tab: 'metrics' } })
  },
  component: () => null,
})

// 百分比 / 中位数类指标的最小样本量：样本不足时一律显示
// 「暂无数据（样本不足）」，而不是让 0 天 / 0.0% 这种误导性的数字出场。
// （真实的 0 保留：如自引率恒为 0，是"没有引文系统"的诚实标注。）
const MIN_STAT_SAMPLE = 3

function statLabel(
  value: number | null | undefined,
  n: number,
  format: (v: number) => string,
): string {
  if (value == null || n < MIN_STAT_SAMPLE) return '暂无数据（样本不足）'
  return format(value)
}

// 公开指标页（0.5.0 改版）：像正式期刊的指标页一样只呈现数值与含义；
// 权重与计算口径属于编辑部内部口径，不进页面、不进 API。
// 没有引文数据，所以诚实标注"不与 JCR 影响因子互比"。
export function JournalMetricsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { data, isLoading, isError, refetch } = useJournalMetrics()

  return (
    <div className={embedded ? '' : 'mx-auto max-w-4xl py-8'}>
      {embedded ? null : (
        <>
          <Link
            to="/"
            className="mb-4 inline-flex items-center text-sm text-muted-foreground transition-colors hover:text-primary"
          >
            <ArrowLeft className="mr-1 h-4 w-4" />
            返回首页
          </Link>

          <PageHeader
            title="本刊数据"
            description="本页只展示站内运行数据。学术底刊不参加传统期刊评价，不发布影响因子，也不把任何数字包装成外部认证。"
          />
        </>
      )}

      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : isError || !data ? (
        <ErrorState message="加载指标失败" onRetry={() => refetch()} />
      ) : (
        <div className="space-y-8">
          <Card className="border-dashed">
            <CardContent className="py-6 text-sm leading-relaxed text-muted-foreground">
              学术底刊不发布影响因子，也不把站内互动包装成「期刊指标」。
              下面只展示站内运行数据：有多少稿、多少阅读、多少下载、样本够不够。
              样本不足时宁可不显示，也不给一个会被单次点击放大的假数字。
            </CardContent>
          </Card>


          <RevealSection>
            <h2 className="text-lg font-medium">一眼看学术轨</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              同样的数字，换一种看法。雷达看读者行为分布，条形看学科构成。
            </p>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs font-medium text-muted-foreground">读者行为分布</p>
                  <EngagementRadar data={data} />
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs font-medium text-muted-foreground">学科构成</p>
                  <DisciplineBar data={data.by_discipline} />
                </CardContent>
              </Card>
            </div>
          </RevealSection>

          <RevealSection>
            <h2 className="text-lg font-medium">指标一览</h2>
            <dl className="mt-3 grid gap-4 sm:grid-cols-2">
              {[
                ['学术论文（论文轨）', `${data.serious_total ?? 0} 篇`],
                ['荒诞论文（论文轨）', `${data.absurd_total ?? 0} 篇`],
                ['覆盖学科', `${data.discipline_count} 个`],
                [
                  '开放获取率',
                  statLabel(
                    data.open_access_rate,
                    data.published_total,
                    (v) => `${v}%`,
                  ),
                ],
                ['总阅读次数', String(data.reads_total)],
                ['总下载次数', String(data.downloads_total)],
                [
                  '总收藏次数',
                  data.saves_total < 10
                    ? `${data.saves_total} 次（样本不足，不作趋势解读）`
                    : `${data.saves_total} 次`,
                ],
                [
                  '录用率',
                  data.acceptance_rate == null ||
                  data.decided_submissions < MIN_STAT_SAMPLE ||
                  data.acceptance_rate >= 99
                    ? '暂不公开（评审样本不足）'
                    : `${data.acceptance_rate}%（${data.accepted_submissions}/${data.decided_submissions}）`,
                ],
                [
                  '初审周期（中位数）',
                  statLabel(data.median_review_days, data.decided_submissions, (v) => `${v} 天`),
                ],
                [
                  '初审周期（均值）',
                  statLabel(data.avg_review_days, data.decided_submissions, (v) => `${v} 天`),
                ],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between border-b py-2 text-sm">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-medium tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </RevealSection>

          <RevealSection>
            <h2 className="text-lg font-medium">本刊怎么看数据</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {[
                {
                  icon: TrendingUp,
                  title: '不发布影响因子',
                  body: '学术底刊不参加影响因子、JCR 分区那套评价。站内热度只用于编辑部观察，不做对外排名，也不冒充期刊指标。',
                },
                {
                  icon: Quote,
                  title: '不伪造引用',
                  body: '本刊没有引文系统，也不鼓励自引表演。该栏位明确标注为不适用，而不是编一个好看的小数字。',
                },
                {
                  icon: BookOpen,
                  title: '编号不是门槛',
                  body: '每篇录用稿自动分配底刊编号；DOI 与 ISSN 由作者按需选择，不强制、不伪造。没有 DOI 的稿件照样可引用、可归档。',
                },
              ].map(({ icon: Icon, title, body }) => (
                <Card key={title}>
                  <CardContent className="p-4">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      <Icon className="h-4 w-4 text-primary" />
                      {title}
                    </p>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{body}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </RevealSection>

          <RevealSection>
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
              <Lock className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-xs leading-relaxed text-muted-foreground">
                关于口径：各项数据的口径与构成已在
                <Link to="/policies" className="mx-1 text-primary hover:underline">
                  本刊政策 · 数据口径
                </Link>
                一节公示。本刊没有接入 Web of Science、Scopus 或 Crossref 引文数据，因此
                <strong>不发布影响因子，也不使用 JCR 分区</strong>；任何把本刊数据与外部影响因子并列比较的说法都不成立。
              </p>
            </div>
          </RevealSection>

          <RevealSection>
            <h2 className="text-lg font-medium">按学科</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {Object.entries(data.by_discipline).length === 0 ? (
                <li className="text-muted-foreground">暂无已发表记录</li>
              ) : (
                Object.entries(data.by_discipline).map(([discipline, count]) => (
                  <li
                    key={discipline}
                    className="flex items-center justify-between border-b py-2"
                  >
                    <span>{discipline}</span>
                    <span className="text-muted-foreground">
                      {count} 篇 · {count >= 4 ? '样本足够（≥4 篇）' : '样本不足（<4 篇）'}
                    </span>
                  </li>
                ))
              )}
            </ul>
          </RevealSection>

          <RevealSection>
            <h2 className="text-lg font-medium">按类型</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {Object.entries(data.by_type).length === 0 ? (
                <li className="text-muted-foreground">暂无已发表记录</li>
              ) : (
                Object.entries(data.by_type).map(([type, count]) => (
                  <li key={type} className="flex items-center justify-between border-b py-2">
                    <span className="flex items-center gap-1.5">
                      <Download className="h-3.5 w-3.5 text-muted-foreground" />
                      {typeLabel(type)}
                    </span>
                    <span className="text-muted-foreground">{count} 篇</span>
                  </li>
                ))
              )}
            </ul>
          </RevealSection>

          <RevealSection className="border-t pt-6 text-xs leading-relaxed text-muted-foreground">
            <p>
              数据来源：本站数据库的 resources / reading_history /
              reading_list_items / submissions 表；页面每次访问实时计算。
            </p>
            <p className="mt-2">
              口径说明：站内热度、篇均下载/阅读等数据仅统计学术稿
              （content_category=academic）；副刊稿（fun/rant）的阅读、收藏、评论、点赞
              等内容侧数据不计入学术指标，但仍在各文章页展示。
            </p>
            <p className="mt-2">
              机器可读版本：
              <a className="ml-1 text-primary hover:underline" href="/api/catalog/journal-metrics">
                /api/catalog/journal-metrics
              </a>
            </p>
          </RevealSection>
        </div>
      )}
    </div>
  )
}
