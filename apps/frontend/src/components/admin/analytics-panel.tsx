import { BarChart3, BookOpen, Download, Eye, Route } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAdminAnalytics, useJournalMetrics } from '@/hooks/api/use-modules'
import {
  PageViewTrend,
  ReferrerBar,
  TopPathsBar,
  TrackDonut,
} from '@/components/charts/admin-overview'

function fmt(n: number | null | undefined) {
  return (n ?? 0).toLocaleString('zh-CN')
}

export function AdminAnalyticsPanel() {
  const { data: metrics, isLoading: metricsLoading } = useJournalMetrics()
  const { data: analytics, isLoading: analyticsLoading } = useAdminAnalytics(7)

  const published = metrics?.published_total ?? 0
  const reads = metrics?.reads_total ?? 0
  const downloads = metrics?.downloads_total ?? 0
  const views = analytics?.total ?? 0
  const paths = analytics?.unique_paths ?? 0
  const essays = Math.max(published - (metrics?.serious_total ?? 0) - (metrics?.absurd_total ?? 0), 0)

  const cards = [
    {
      label: '已发表内容',
      value: fmt(published),
      sub: `论文 ${fmt(metrics?.serious_total)} + 荒诞 ${fmt(metrics?.absurd_total)} + 副刊 ${fmt(essays)}`,
      icon: BookOpen,
    },
    {
      label: '总阅读次数',
      value: fmt(reads),
      sub: published > 0 ? `篇均 ${(reads / published).toFixed(1)} 次` : '暂无刊出',
      icon: Eye,
    },
    {
      label: '总下载次数',
      value: fmt(downloads),
      sub: published > 0 ? `篇均 ${(downloads / published).toFixed(1)} 次` : '暂无下载',
      icon: Download,
    },
    {
      label: '近 7 天页面访问',
      value: fmt(views),
      sub: `${fmt(paths)} 个页面有访问 · 按会话去重`,
      icon: Route,
    },
  ]

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-medium">
            <BarChart3 className="h-5 w-5 text-primary" />
            站点数据总览
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            内容、阅读、下载与页面访问都来自运行数据；页面访问只记路径与来源，不采 IP / UA / 用户 ID，因此不称 UV。
          </p>
        </div>
        <p className="text-[11px] text-muted-foreground">
          {metricsLoading || analyticsLoading ? '数据加载中…' : '每 60 秒自动刷新'}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(({ label, value, sub, icon: Icon }) => (
          <Card key={label}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">{label}</p>
                <Icon className="h-4 w-4 text-primary" />
              </div>
              <p className="mt-2 font-serif text-3xl font-semibold tabular-nums">{value}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-1">
            <CardTitle className="text-sm">近 7 天页面访问趋势</CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <PageViewTrend data={analytics?.daily ?? []} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm">内容构成</CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <TrackDonut data={metrics} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm">热门页面 Top 8</CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <TopPathsBar data={analytics?.paths ?? []} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm">访问来源 Top 6</CardTitle>
          </CardHeader>
          <CardContent className="pt-2">
            <ReferrerBar data={analytics?.referrers ?? []} />
          </CardContent>
        </Card>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        口径：阅读/下载为站内累计；页面访问为同一会话内同一路径只记一次，近 7 天按中国时区自然日切分。
        录用率与审稿周期在「关于本刊 · 指标」页，看板不重复造数。
      </p>
    </section>
  )
}
