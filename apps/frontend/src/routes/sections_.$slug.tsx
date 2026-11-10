import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMemo } from 'react'
import { ArrowLeft } from 'lucide-react'
import { useArticleSections, useResources } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'

export const Route = createFileRoute('/sections_/$slug')({
  component: SectionPage,
})

function SectionPage() {
  const { slug } = Route.useParams()
  const nav = useNavigate()
  const sections = useArticleSections()
  const section = sections.data?.data.find((s) => s.slug === slug)
  const part = section?.parts.find((p) => p.slug === slug)
  const activePart = part ? slug : undefined
  const { data, isLoading, isError, refetch } = useResources({
    section: part ? part.slug : slug,
    page_size: 100,
    sort: 'created_at',
  })
  const items = useMemo(() => data?.data ?? [], [data])
  const title = section?.label ?? part?.label ?? slug
  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-3 -ml-2" onClick={() => nav({ to: '/sections' })}>
        <ArrowLeft className="h-4 w-4" /> 全部栏目
      </Button>
      <PageHeader
        title={title}
        description={section?.description ?? '本栏目下的稿件。'}
        actions={<Badge variant="secondary">{items.length} 篇</Badge>}
      />
      {section && (section.track_counts?.paper ?? 0) > 0 && (section.track_counts?.essay ?? 0) > 0 ? (
        <p className="mb-4 text-xs text-muted-foreground">
          本栏目同时收论文与副刊：下方卡片标注轨道；副刊稿不参与学术计分。
        </p>
      ) : null}
      {section && (
        <div className="mb-5 flex flex-wrap gap-2">
          {section.parts.map((p) => (
            <Link key={p.slug} to="/sections/$slug" params={{ slug: p.slug }}>
              <Badge variant={activePart === p.slug ? 'default' : 'outline'}>
                {p.label} · {p.count}
              </Badge>
            </Link>
          ))}
        </div>
      )}
      {isLoading && <Loading />}
      {isError && <ErrorState onRetry={() => refetch()} />}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          title="本栏目暂无稿件"
          description="欢迎作者从投稿入口选择对应栏目；编辑部会按栏目分派与排版。"
          action={
            <Link
              to="/submissions/new"
              search={{ section: activePart ?? section?.parts[0]?.slug ?? slug } as never}
            >
              <Button size="sm">投这个栏目</Button>
            </Link>
          }
        />
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((r) => (
          <Link key={r.id} to="/catalog/$resourceId" params={{ resourceId: String(r.id) }}>
            <Card className="h-full transition-colors hover:border-foreground/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-base leading-snug">{r.title}</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {r.authors?.join('、')} · {r.year}
                </p>
              </CardHeader>
              <CardContent>
                <p className="line-clamp-3 text-sm text-muted-foreground">{r.abstract}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {r.content_track === 'essay' ? (
                    <Badge variant="outline">副刊</Badge>
                  ) : (
                    <Badge variant="outline">{r.track === 'absurd' ? '荒诞论文' : '学术论文'}</Badge>
                  )}
                  {r.issue_part && <Badge variant="outline">{r.issue_part}</Badge>}
                  {r.discipline && <Badge variant="secondary">{r.discipline}</Badge>}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
