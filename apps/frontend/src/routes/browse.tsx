import { Link } from '@tanstack/react-router'
import { createFileRoute, redirect } from '@tanstack/react-router'
import { useCatalogStats, useResources } from '@/hooks/api/use-modules'
import type { ResourceResponse, ResourceStats } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { ArticleCover } from '@/components/common/article-cover'
import { DISCIPLINE_STYLE, DEFAULT_DISCIPLINE_STYLE } from '@/lib/discipline-style'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/browse')({
  // /browse 已并入 /papers 的筛选器；旧链接与书签统一跳转，避免出现两套目录。
  beforeLoad: () => {
    throw redirect({ to: '/papers' })
  },
  component: BrowsePage,
})

function BrowsePage() {
  const statsQ = useCatalogStats()
  const papersQ = useResources({ track: 'paper', page: 1, page_size: 3, sort: 'created_at', order: 'desc' })
  const essaysQ = useResources({ track: 'essay', page: 1, page_size: 3, sort: 'created_at', order: 'desc' })

  const stats: ResourceStats | undefined = statsQ.data
  const disciplines = Object.entries(stats?.by_discipline ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader
        title="浏览"
        description="按学科进入。也可以直接搜索，但先给入口比先给搜索框更友好。"
      />

      {/* 学科九宫格：内容入口的核心（赛道入口已随赛道下线移除） */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">
          按学科（{disciplines.length} 个）
        </h2>
        {statsQ.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {disciplines.map(([name, count]) => {
              const style = DISCIPLINE_STYLE[name] ?? DEFAULT_DISCIPLINE_STYLE
              const Icon = style.icon
              return (
                <Link
                  key={name}
                  to="/catalog"
                  search={{ discipline: name }}
                  className={cn(
                    'group flex items-center gap-4 rounded-xl border bg-gradient-to-br p-4 transition-all hover:shadow-md',
                    style.tint,
                  )}
                >
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-background/70 ring-1 ring-border">
                    <Icon className="h-5 w-5 text-foreground/75" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{name}</span>
                    <span className="block text-xs text-muted-foreground">{count} 篇</span>
                  </span>
                </Link>
              )
            })}
          </div>
        )}
      </section>

      {/* 最新内容分两栏：论文一栏、副刊一栏。不再把两条轨道混在同一列里。 */}
      <section className="grid gap-6 lg:grid-cols-2">
        <LatestColumn
          title="最新论文"
          subtitle="学术论文与荒诞论文"
          href="/papers"
          rows={papersQ.data?.data ?? []}
          loading={papersQ.isLoading}
          showPaperKind
        />
        <LatestColumn
          title="最新副刊"
          subtitle="小说、随笔、评论、指南、吐槽"
          href="/fun"
          rows={essaysQ.data?.data ?? []}
          loading={essaysQ.isLoading}
        />
      </section>
    </div>
  )
}

function LatestColumn({
  title,
  subtitle,
  href,
  rows,
  loading,
  showPaperKind = false,
}: {
  title: string
  subtitle: string
  href: '/papers' | '/fun'
  rows: ResourceResponse[]
  loading: boolean
  showPaperKind?: boolean
}) {
  return (
    <div>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h2 className="font-serif text-lg font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Link to={href} className="text-xs text-primary hover:underline">
          查看全部 →
        </Link>
      </div>
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => {
            const kindTag = showPaperKind ? (r.track === 'absurd' ? '荒诞论文' : '学术论文') : '副刊'
            return (
              <Link key={r.id} to="/catalog/$resourceId" params={{ resourceId: String(r.id) }}>
                <Card className="overflow-hidden transition-shadow hover:shadow-md">
                  <CardContent className="flex gap-3 p-3">
                    <ArticleCover resource={r} className="h-20 w-24 shrink-0 rounded-lg" />
                    <div className="min-w-0 space-y-1.5">
                      <Badge variant="outline" className="text-[10px]">
                        {kindTag}
                      </Badge>
                      <p className="line-clamp-2 text-sm font-medium leading-snug">{r.title}</p>
                      <p className="line-clamp-1 text-xs text-muted-foreground">{r.authors.join('、')}</p>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
