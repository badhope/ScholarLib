import { useMemo } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowRight, CalendarDays, Clock3, Layers, Lock } from 'lucide-react'
import { useAuth } from '@/hooks/use-auth'
import { useIssuePlan, usePublishIssue, useResources } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { ArticleCover } from '@/components/common/article-cover'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { contentCategoryLabel } from '@/lib/resource-labels'
import { cn } from '@/lib/utils'
import type { IssuePlanEntry } from '@/lib/types'

export const Route = createFileRoute('/archive')({
  component: ArchivePage,
})

// 卷期归档 = 公开的出版日历：已发期次可点开读全文，排期中的期次只显示
// 预计上线日期与篇数（服务端 publish_at 未到点前，这些记录对公众不存在）。
// 注意：本刊不设固定刊期，这里的排期只是归档组织与参考，随时可能调整。
import { issueTitle } from '@/lib/issue-meta'

function fmtDate(iso: string | null, fallback: string = '待定'): string {
  if (!iso) return fallback
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return fallback
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return null
  return Math.max(0, Math.ceil((d - Date.now()) / 86_400_000))
}

function ArchivePage() {
  const plan = useIssuePlan()
  const { isAdmin } = useAuth()
  const entries = useMemo(() => plan.data?.entries ?? [], [plan.data])
  const liveEntries = useMemo(() => entries.filter((e) => e.state === 'live'), [entries])
  const activeIssue = liveEntries[liveEntries.length - 1]?.issue || ''
  const activeEntry = entries.find((e) => e.issue === activeIssue)
  const activeVolume = activeEntry?.volume ?? plan.data?.volume ?? ''

  const { data, isLoading, isError, refetch } = useResources({
    volume: activeVolume || undefined,
    issue: activeIssue || undefined,
    page: 1,
    page_size: 50,
    sort: 'issue',
  })
  const publishIssue = usePublishIssue()

  const items = data?.data ?? []

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="卷期归档"
        description="按卷期归档 · 滚动刊出：稿件完成评审即上线，不设固定刊期；卷期仅作归档组织，排期信息仅供参考、随时可能调整。"
      />

      {/* 出版日历：横向滚动，不撑破视口 */}
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <div className="flex min-w-max gap-2 pb-1">
          {entries.map((entry) => {
            const isLive = entry.state === 'live'
            const isActive = entry.issue === activeIssue && isLive
            const cls = cn(
              'flex min-h-16 min-w-[92px] flex-col items-start justify-center rounded-lg border px-3.5 py-2 text-left transition-colors',
              isActive
                ? 'border-primary bg-primary/[0.06]'
                : isLive
                  ? 'border-border bg-card hover:border-primary/40'
                  : 'cursor-not-allowed border-dashed border-border/60 bg-muted/30 opacity-80',
            )
            const body = (
              <>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  第 {entry.issue} 期
                </span>
                <span className="flex items-center gap-1 text-sm font-medium">
                  {isLive ? (
                    <>已上线</>
                  ) : (
                    <>
                      <Lock className="h-3 w-3" />
                      {entry.publish_at ? `${new Date(entry.publish_at).getMonth() + 1} 月` : '排期中'}
                    </>
                  )}
                </span>
                <span className="text-[10px] tabular-nums text-muted-foreground">
                  {entry.published || entry.scheduled} 篇
                </span>
              </>
            )
            return isLive ? (
              <Link
                key={entry.issue}
                to="/archive/$issue"
                params={{ issue: entry.issue }}
                className={cls}
                title={`第 ${entry.issue} 期 · ${issueTitle(entry.issue)}`}
              >
                {body}
              </Link>
            ) : (
              <button
                key={entry.issue}
                type="button"
                disabled
                className={cls}
                title={`预计 ${fmtDate(entry.publish_at)} 上线`}
              >
                {body}
              </button>
            )
          })}
        </div>
      </div>

      {/* 当前期头 */}
      {activeEntry && (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-muted/30 px-5 py-3">
            <div>
              <p className="flex items-center gap-2 text-sm font-medium">
                <CalendarDays className="h-4 w-4 text-primary" />
                第 {activeEntry.volume} 卷 第 {activeEntry.issue} 期
                <span className="text-muted-foreground">
                  {/* 滚动刊出：一期里最早/最晚上线能差半年（实测 04-04 与 11-06
                      同属第 5 期）。对已上线期号显示单一日期只会误导读者，
                      改成说明刊出方式；未上线期号仍显示预计日期。 */}
                  · {activeEntry.state === 'live'
                    ? '滚动刊出 · 随时增补'
                    : `预计 ${fmtDate(activeEntry.publish_at)} 上线`}
                </span>
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {issueTitle(activeEntry.issue)}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="tabular-nums">
                {items.length} 篇
              </Badge>
              {activeEntry.state === 'live' ? (
                <Link
                  to="/archive/$issue"
                  params={{ issue: activeEntry.issue }}
                  className="inline-flex items-center gap-1 rounded-md border bg-background px-2.5 py-1 text-xs text-primary hover:bg-primary/5"
                >
                  <Layers className="h-3.5 w-3.5" /> 本期版面
                </Link>
              ) : null}
            </div>
          </div>

          {isLoading ? (
            <div className="p-6">
              <Loading />
            </div>
          ) : isError ? (
            <div className="p-6">
              <ErrorState message="加载本期目录失败" onRetry={() => refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div className="p-8">
              <EmptyState title="本期暂无文章" description="切换其他已上线期次，或浏览全部目录。" />
            </div>
          ) : (
            <ol className="divide-y">
              {items.map((r, idx) => {
                const categoryTag = contentCategoryLabel(r.content_category)
                return (
                  <li key={r.id}>
                    <Link
                      to="/catalog/$resourceId"
                      params={{ resourceId: String(r.id) }}
                      className="group flex gap-4 p-4 transition-colors hover:bg-muted/40 sm:p-5"
                    >
                      <span className="w-6 shrink-0 pt-1 text-right font-serif text-sm tabular-nums text-muted-foreground">
                        {idx + 1}
                      </span>
                      <div className="hidden w-32 shrink-0 sm:block">
                        <ArticleCover resource={r} showDiscipline={false} aspect="aspect-[16/9]" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          {categoryTag ? (
                            <Badge variant="outline" className="text-[10px] bg-primary/10 text-primary border-primary/25">
                              {categoryTag}
                            </Badge>
                          ) : null}
                          <Badge variant="outline" className="text-[10px]">
                            {r.discipline}
                          </Badge>
                          {r.subdiscipline ? (
                            <span className="text-[10px] text-muted-foreground">{r.subdiscipline}</span>
                          ) : null}
                        </div>
                        <p className="mt-1.5 line-clamp-2 font-medium leading-snug group-hover:text-primary">
                          {r.title}
                        </p>
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                          {r.authors.join('、')}
                        </p>
                        <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground/90">
                          {r.abstract}
                        </p>
                      </div>
                      <ArrowRight className="mt-1 hidden h-4 w-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:text-primary sm:block" />
                    </Link>
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      )}

      {/* 排期表 */}
      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <Clock3 className="h-4 w-4 text-primary" /> 刊出排期（仅供参考）
        </h2>
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">期次</th>
                <th className="px-4 py-2 text-left font-medium">主题</th>
                <th className="px-4 py-2 text-left font-medium">上线日期</th>
                <th className="px-4 py-2 text-right font-medium">篇数</th>
                <th className="px-4 py-2 text-right font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <IssueRow
                  key={entry.issue}
                  entry={entry}
                  isAdmin={isAdmin}
                  publishing={publishIssue.isPending}
                  onPublish={() =>
                    publishIssue.mutate({
                      volume: entry.volume,
                      issue: entry.issue,
                      publishAt: null,
                    })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="flex flex-wrap gap-3 text-sm">
        <Link to="/catalog" className="inline-flex items-center gap-1 text-primary hover:underline">
          <Layers className="h-3.5 w-3.5" /> 浏览全部条目
        </Link>
        <Link
          to="/levels"
          className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          评分与等级规范 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  )
}

function IssueRow({
  entry,
  isAdmin,
  publishing,
  onPublish,
}: {
  entry: IssuePlanEntry
  isAdmin: boolean
  publishing: boolean
  onPublish: () => void
}) {
  const wait = daysUntil(entry.publish_at)
  return (
    <tr className="border-t">
      <td className="px-4 py-2.5 font-medium tabular-nums">第 {entry.issue} 期</td>
      <td className="px-4 py-2.5 text-muted-foreground">
        {issueTitle(entry.issue)}
      </td>
      <td className="px-4 py-2.5 tabular-nums text-muted-foreground">
        {entry.state === 'scheduled' && !entry.publish_at
          ? '排期待定'
          : fmtDate(entry.publish_at)}
        {entry.state === 'scheduled' && wait !== null && wait > 0 ? (
          <span className="ml-2 text-[11px] text-muted-foreground/80">还有 {wait} 天</span>
        ) : null}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums">
        {entry.published || entry.scheduled}
      </td>
      <td className="px-4 py-2.5 text-right">
        {entry.state === 'live' ? (
          <Badge className="text-[10px]">已上线</Badge>
        ) : isAdmin ? (
          <Button size="sm" variant="outline" onClick={onPublish} disabled={publishing}>
            立即发布
          </Button>
        ) : (
          <Badge variant="outline" className="text-[10px]">
            排期中
          </Badge>
        )}
      </td>
    </tr>
  )
}
