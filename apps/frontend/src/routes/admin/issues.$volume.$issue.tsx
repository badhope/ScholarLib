import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Send } from 'lucide-react'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import { usePublishIssue, useResources, useUpdateResource } from '@/hooks/api/use-modules'
import { ARTICLE_SECTION_OPTIONS } from '@/lib/article-sections'
import type { ResourceResponse } from '@/lib/types'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/admin/issues/$volume/$issue')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminIssueDetailPage,
})

const UNSET_PART = '__unset__'
const SECTION_LABEL: Record<string, string> = Object.fromEntries(
  ARTICLE_SECTION_OPTIONS.map((item) => [item.value, item.label]),
)
SECTION_LABEL[UNSET_PART] = '未分部'

function AdminIssueDetailPage() {
  const { volume, issue } = Route.useParams()
  const { data, isLoading, isError, refetch } = useResources({
    volume,
    issue,
    page_size: 100,
    sort: 'issue',
    order: 'asc',
  })
  const updateMut = useUpdateResource()
  const publishMut = usePublishIssue()
  const [draftParts, setDraftParts] = useState<Record<number, string>>({})

  const rows = useMemo(() => data?.data ?? [], [data])
  const groups = useMemo(() => {
    const map = new Map<string, ResourceResponse[]>()
    for (const row of rows) {
      const key = row.issue_part || UNSET_PART
      const list = map.get(key) ?? []
      list.push(row)
      map.set(key, list)
    }
    return [...map.entries()].sort(([a], [b]) => {
      if (a === UNSET_PART) return 1
      if (b === UNSET_PART) return -1
      return (SECTION_LABEL[a] ?? a).localeCompare(SECTION_LABEL[b] ?? b)
    })
  }, [rows])

  const onSavePart = async (row: ResourceResponse) => {
    const next = draftParts[row.id]
    if (!next) return
    try {
      await updateMut.mutateAsync({
        id: row.id,
        body: { issue_part: next === UNSET_PART ? null : next },
      })
      toast.success(`《${row.title}》已归入${SECTION_LABEL[next]}`)
      setDraftParts((prev) => {
        const copy = { ...prev }
        delete copy[row.id]
        return copy
      })
      void refetch()
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  const onPublish = async () => {
    if (!window.confirm(`确认将 Vol. ${volume} Issue ${issue} 的已发布文章整期上线？`)) return
    try {
      await publishMut.mutateAsync({ volume, issue, publishAt: null })
      toast.success('本期已发布')
      void refetch()
    } catch (err) {
      toast.error(extractError(err, '发布失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title={`Vol. ${volume} — Issue ${issue}`}
        description="按 Nature 式分部逐篇核对内容归属；归位后整期发布，发布只影响已通过门禁的文章。"
        actions={
          <div className="flex items-center gap-2">
            {data ? <Badge variant="secondary">{rows.length} 篇</Badge> : null}
            <Button
              size="sm"
              onClick={() => void onPublish()}
              disabled={publishMut.isPending || rows.length === 0}
            >
              <Send className="mr-1 h-4 w-4" />
              {publishMut.isPending ? '发布中…' : '发布本期'}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/issues" search={{ volume }}>
                <ArrowLeft className="mr-1 h-4 w-4" />
                返回期列表
              </Link>
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载本期文章失败" onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="本期还没有文章"
          description="先在目录里创建资源并填好卷、期，再回到这里分部。"
        />
      ) : (
        <div className="space-y-6">
          {groups.map(([part, items]) => (
            <section key={part} className="space-y-2">
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-semibold">
                  {SECTION_LABEL[part] ?? part}
                </h2>
                <span className="text-xs text-muted-foreground">
                  {items.length} 篇
                </span>
              </div>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>文章</TableHead>
                      <TableHead className="w-64">分部</TableHead>
                      <TableHead className="w-28" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((row) => {
                      const value = draftParts[row.id] ?? (row.issue_part || UNSET_PART)
                      const dirty = value !== (row.issue_part || UNSET_PART)
                      return (
                        <TableRow key={row.id}>
                          <TableCell>
                            <Link
                              to="/catalog/$resourceId"
                              params={{ resourceId: String(row.id) }}
                              className="text-sm underline-offset-4 hover:underline"
                            >
                              《{row.title}》
                            </Link>
                            {row.publication_status === 'published' ? (
                              <Badge variant="outline" className="ml-2">
                                已上线
                              </Badge>
                            ) : (
                              <Badge variant="secondary" className="ml-2">
                                未上线
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <select
                              value={value}
                              onChange={(e) =>
                                setDraftParts((prev) => ({ ...prev, [row.id]: e.target.value }))
                              }
                              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                            >
                              {ARTICLE_SECTION_OPTIONS.map((item) => (
                                <option key={item.value} value={item.value}>
                                  {item.label}
                                </option>
                              ))}
                              <option value={UNSET_PART}>未分部</option>
                            </select>
                          </TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant={dirty ? 'default' : 'outline'}
                              disabled={!dirty || updateMut.isPending}
                              onClick={() => void onSavePart(row)}
                            >
                              保存
                            </Button>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
