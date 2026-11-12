import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Search } from 'lucide-react'
import { requireAdminGuard } from '@/lib/route-guards'
import { useIssueList } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface IssuesSearch {
  volume?: string
}

export const Route = createFileRoute('/admin/issues')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  validateSearch: (search: Record<string, unknown>): IssuesSearch => ({
    volume: typeof search.volume === 'string' ? search.volume : undefined,
  }),
  component: AdminIssuesPage,
})

function AdminIssuesPage() {
  const { volume } = Route.useSearch()
  const [query, setQuery] = useState('')
  const { data, isLoading, isError, refetch } = useIssueList(volume ?? '')
  // 用 useMemo 固定引用：直接写 `data?.items ?? []` 每渲染都是新数组，
  // 会让下面 filtered 的 useMemo 依赖每次都变（eslint exhaustive-deps 警告）。
  const issues = useMemo(() => data?.items ?? [], [data])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return issues
    return issues.filter((item) => item.issue.toLowerCase().includes(q))
  }, [issues, query])

  if (!volume) {
    return (
      <div>
        <PageHeader
          title="期管理"
          description="请从卷管理页面选择一个卷来查看其期列表。"
          actions={
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/volumes">
                <ArrowLeft className="mr-1 h-4 w-4" />
                返回卷列表
              </Link>
            </Button>
          }
        />
        <EmptyState
          title="未选择卷"
          description="请先访问卷管理页面，选择要查看的卷。"
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/volumes">浏览卷列表</Link>
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title={`Vol. ${volume} — 期列表`}
        description="管理该卷下的各期组织结构。点击期号查看该期的文章。"
        actions={
          <div className="flex items-center gap-2">
            {data ? (
              <Badge variant="secondary">{issues.length} 期</Badge>
            ) : null}
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/volumes">
                <ArrowLeft className="mr-1 h-4 w-4" />
                返回卷列表
              </Link>
            </Button>
          </div>
        }
      />


      <div className="mb-4 max-w-sm">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索期号"
            className="pl-8"
          />
        </div>
      </div>

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载期列表失败" onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={`Vol. ${volume} 暂无期`}
          description="该卷下尚未设置期号（issue）字段。"
        />
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>期号</TableHead>
                <TableHead>文章数</TableHead>
                <TableHead>年份范围</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((item) => (
                <TableRow key={item.issue}>
                  <TableCell className="font-medium">
                    Issue {item.issue}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{item.articleCount} 篇</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {item.firstYear === item.lastYear
                      ? item.firstYear
                      : `${item.firstYear} — ${item.lastYear}`}
                  </TableCell>
                  <TableCell>
                    <Link
                      to="/admin/issues/$volume/$issue"
                      params={{ volume, issue: item.issue }}
                      className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                    >
                      分部与发布
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
