import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, BookOpen, Download, Lock, Quote, Sparkles, TrendingUp } from 'lucide-react'
import { useJournalMetrics } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Card, CardContent } from '@/components/ui/card'
import { typeLabel } from '@/lib/resource-labels'
import { AbsurdityDonut, DisciplineBar, EngagementRadar } from '@/components/charts/metrics-charts'

export const Route = createFileRoute('/journal-metrics')({
  component: JournalMetricsPage,
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
function JournalMetricsPage() {
  const { data, isLoading, isError, refetch } = useJournalMetrics()

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
        title="期刊指标"
        description="本页所有数字均由本站运行数据实时计算。指标体系为编辑部自设计，与任何外部评价体系互不隶属。"
      />

      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : isError || !data ? (
        <ErrorState message="加载指标失败" onRetry={() => refetch()} />
      ) : (
        <div className="space-y-8">
          {data.published_total > 0 && data.r_factor == null ? (
            <Card className="border-dashed">
              <CardContent className="py-6 text-sm text-muted-foreground">
                R 因子需要足够的站内互动样本（阅读 + 下载 + 收藏）。
                当前样本量不足，暂不出数 —— 少于这个量算出来的均值会被单次点击放大
                （例如一篇被下载一次就顶到学科满分）。样本够了这里会自动出现。
              </CardContent>
            </Card>
          ) : null}
          {data.published_total > 0 && data.r_factor != null ? (
            <RevealSection>
              <Card className="overflow-hidden border-primary/20 bg-gradient-to-br from-primary/5 via-transparent to-accent/10">
                <CardContent className="flex flex-col items-center gap-2 py-10 text-center sm:flex-row sm:justify-between sm:text-left">
                  <div>
                    <p className="text-sm font-medium tracking-wide text-muted-foreground">
                      R 因子（全刊）
                    </p>
                    <p className="mt-1 font-serif text-5xl font-bold tabular-nums text-primary">
                      {data.r_factor.toFixed(2)}
                    </p>
                    <p className="mt-2 max-w-md text-xs leading-relaxed text-muted-foreground">
                      本刊旗舰指标，衡量全刊已发表内容的综合热度与编辑质量。口径与权重属编辑部内部标准。
                    </p>
                  </div>
                  <div className="grid grid-cols-3 gap-6 text-center sm:text-right">
                    <div>
                      <p className="font-serif text-2xl font-semibold tabular-nums">
                        {data.absurdity_index_median == null ? '—' : data.absurdity_index_median.toFixed(1)}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">荒诞指数中位数</p>
                    </div>
                    <div>
                      <p className="font-serif text-2xl font-semibold tabular-nums">
                        {data.self_citation_rate.toFixed(1)}%
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">自引率</p>
                    </div>
                    <div>
                      <p className="font-serif text-2xl font-semibold tabular-nums">
                        {data.published_total}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">已发表论文</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </RevealSection>
          ) : null}

          <RevealSection>
            <h2 className="text-lg font-medium">一眼看全刊</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              同样的数字，换一种看法。环形看荒诞气质，雷达看读者行为分布，条形看学科构成。
            </p>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs font-medium text-muted-foreground">荒诞气质</p>
                  <AbsurdityDonut median={data.absurdity_index_median} />
                </CardContent>
              </Card>
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
                ['已发表记录', `${data.published_total} 篇`],
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
                ['总收藏次数', String(data.saves_total)],
                [
                  '录用率',
                  data.acceptance_rate == null || data.decided_submissions < MIN_STAT_SAMPLE
                    ? '暂无数据（样本不足）'
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
            <h2 className="text-lg font-medium">指标体系说明</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {[
                {
                  icon: TrendingUp,
                  title: 'R 因子',
                  body: '本刊自设计的旗舰指标，综合读者注意力与编辑质量评定，取全刊均值。类似传统引文指标的门面数字，但口径由编辑部掌握，不对外公开。',
                },
                {
                  icon: Sparkles,
                  title: '荒诞指数',
                  body: '编辑部对每篇内容离谱程度的评定（0–10）。本刊兼收正经与荒诞研究，指数只描述内容气质，与质量无关——正经论文可以很好，离谱论文也可以很好。',
                },
                {
                  icon: Quote,
                  title: '自引率 0.0%',
                  body: '本刊没有引文系统，也不鼓励自引表演。该栏位诚实保留为 0，而不是编一个好看的小数字。',
                },
                {
                  icon: BookOpen,
                  title: '分区（R1–R4）',
                  body: '同一学科内按 R 值四分位划分，前 25% 为 R1。学科样本不足 4 篇时不出分区，宁缺毋滥。',
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
                关于口径：各指数的口径与构成已在
                <Link to="/policies" className="mx-1 text-primary hover:underline">
                  期刊政策 · 本刊指数体系
                </Link>
                一节公示。本刊未接入 Web of Science、Scopus 或 Crossref 引文数据，因此
                <strong>不发布影响因子，也不使用 JCR 分区</strong>；任何把本刊指标与外部影响因子并列比较的说法都不成立。
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
                      {count} 篇 · {count >= 4 ? '已生成分区' : '样本不足（<4 篇）'}
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
