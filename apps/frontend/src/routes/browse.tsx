import { Link } from '@tanstack/react-router'
import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Atom,
  BookOpen,
  Brain,
  Cpu,
  FlaskConical,
  Globe2,
  Landmark,
  Leaf,
  LineChart,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { api } from '@/lib/api'
import { useCatalogStats } from '@/hooks/api/use-modules'
import type { ResourceResponse, ResourceStats } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { ArticleCover } from '@/components/common/article-cover'
import { absurdityLevel, qualityGrade } from '@/lib/resource-labels'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/browse')({
  component: BrowsePage,
})

/**
 * 学科 → 图标/配色映射。
 *
 * 为什么要有这一页：此前目录页一进来就是一张大表格，读者面对 109 条
 * 记录无从下手。好的内容站不会让人"先看到全部"再自己筛——它先给
 * 入口（九宫格），让人按兴趣缩小范围，再进列表。这是导航逻辑，不是
 * 装饰。
 */
const DISCIPLINE_STYLE: Record<string, { icon: LucideIcon; tint: string }> = {
  计算机科学: { icon: Cpu, tint: 'from-sky-500/15 to-sky-500/5' },
  信息科学: { icon: LineChart, tint: 'from-indigo-500/15 to-indigo-500/5' },
  生命科学: { icon: FlaskConical, tint: 'from-emerald-500/15 to-emerald-500/5' },
  物理与宇宙学: { icon: Atom, tint: 'from-violet-500/15 to-violet-500/5' },
  地球科学: { icon: Globe2, tint: 'from-teal-500/15 to-teal-500/5' },
  生态与环境科学: { icon: Leaf, tint: 'from-green-500/15 to-green-500/5' },
  数学与统计: { icon: LineChart, tint: 'from-cyan-500/15 to-cyan-500/5' },
  心理学: { icon: Brain, tint: 'from-rose-500/15 to-rose-500/5' },
  社会科学: { icon: Users, tint: 'from-amber-500/15 to-amber-500/5' },
  人文与文化研究: { icon: Landmark, tint: 'from-orange-500/15 to-orange-500/5' },
  管理学: { icon: BookOpen, tint: 'from-blue-500/15 to-blue-500/5' },
}

const DEFAULT_STYLE = { icon: BookOpen, tint: 'from-primary/15 to-primary/5' }

function BrowsePage() {
  const statsQ = useCatalogStats()
  const featuredQ = useQuery<{ data: ResourceResponse[] }>({
    queryKey: ['catalog', 'featured'],
    queryFn: async () =>
      (
        await api.get('/catalog', {
          params: { page: 1, page_size: 6, sort: 'created_at', order: 'desc' },
        })
      ).data,
  })

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
              const style = DISCIPLINE_STYLE[name] ?? DEFAULT_STYLE
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

      {/* 最新发表：给"随便看看"的读者一个去处 */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground">最新发表</h2>
          <Link to="/catalog" className="text-xs text-primary hover:underline">
            全部文章 →
          </Link>
        </div>
        {featuredQ.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-56 rounded-xl" />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(featuredQ.data?.data ?? []).map((r) => {
              const grade = qualityGrade(r.quality_grade)
              const level = absurdityLevel(r.absurdity_index)
              return (
                <Link key={r.id} to="/catalog/$resourceId" params={{ resourceId: String(r.id) }}>
                  <Card className="h-full overflow-hidden transition-shadow hover:shadow-md">
                    <ArticleCover resource={r} className="h-32 w-full" />
                    <CardContent className="space-y-2 p-4">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {level && (
                          <Badge variant={level.variant} className="text-[10px]">
                            {level.label}
                          </Badge>
                        )}
                        {grade && (
                          <Badge variant="outline" className={grade.className}>
                            {grade.label}
                          </Badge>
                        )}
                      </div>
                      <p className="line-clamp-2 text-sm font-medium leading-snug">{r.title}</p>
                      <p className="line-clamp-1 text-xs text-muted-foreground">
                        {r.authors.join('、')}
                      </p>
                    </CardContent>
                  </Card>
                </Link>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
