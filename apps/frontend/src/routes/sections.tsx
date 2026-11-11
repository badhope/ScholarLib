import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowRight, Layers } from 'lucide-react'
import { useArticleSections } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Loading, ErrorState } from '@/components/common/state'

export const Route = createFileRoute('/sections')({
  component: SectionsIndex,
})

function SectionsIndex() {
  const { data, isLoading, isError, refetch } = useArticleSections()
  return (
    <div>
      <PageHeader
        title="栏目"
        description="按 Nature 式栏目组织阅读：社论、新闻、书评、观点、职业与研究。栏目是展示分组，论文与副刊可共用同一栏目，但不会改变各自的轨道归属。"
      />
      {isLoading && <Loading />}
      {isError && <ErrorState onRetry={() => refetch()} />}
      {data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.data.map((section) => (
            <Link key={section.slug} to="/sections/$slug" params={{ slug: section.slug }} className="group block h-full">
              <Card className="card-lift flex h-full flex-col gap-0">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="font-serif text-lg tracking-tight">{section.label}</CardTitle>
                    <Badge variant="secondary">{section.count} 篇</Badge>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-2.5 pt-0">
                  <p className="text-sm text-muted-foreground">{section.description}</p>
                  {section.track_counts && (section.track_counts.paper > 0 || section.track_counts.essay > 0) ? (
                    <p className="text-xs text-muted-foreground">
                      论文 {section.track_counts.paper} 篇 · 副刊 {section.track_counts.essay} 篇
                    </p>
                  ) : null}
                  <div className="flex flex-wrap gap-1.5">
                    {section.parts.map((p) => (
                      <Badge key={p.slug} variant="outline" className="font-normal">
                        {p.label}
                        {p.count > 0 ? ` · ${p.count}` : ''}
                      </Badge>
                    ))}
                  </div>
                  <span className="mt-auto inline-flex items-center gap-1 pt-1 text-sm font-medium text-primary">
                    进入栏目
                    <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
      {data?.uncategorized ? (
        <p className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
          <Layers className="h-4 w-4" /> 另有 {data.uncategorized} 篇尚未归入栏目，仍可在论文/副刊目录阅读。
        </p>
      ) : null}
    </div>
  )
}
