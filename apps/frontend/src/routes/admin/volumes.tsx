import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ChevronRight, Search } from 'lucide-react'
import { requireAdminGuard } from '@/lib/route-guards'
import { useVolumeList } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/admin/volumes')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminVolumesPage,
})

function AdminVolumesPage() {
  const [query, setQuery] = useState('')
  const { data, isLoading, isError, refetch } = useVolumeList()
  // 用 useMemo 固定引用：直接写 `data?.items ?? []` 每渲染都是新数组，
  // 会让下面 filtered 的 useMemo 依赖每次都变（eslint exhaustive-deps 警告）。
  const volumes = useMemo(() => data?.items ?? [], [data])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return volumes
    return volumes.filter((v) => v.volume.toLowerCase().includes(q))
  }, [volumes, query])

  return (
    <div>
      <PageHeader
        title="卷管理"
        description="管理期刊卷（Volume）的组织结构。点击卷查看期列表。"
        actions={
          data ? (
            <Badge variant="secondary">{volumes.length} 卷</Badge>
          ) : null
        }
      />

      
      <div className="mb-4 max-w-sm">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索卷号"
            className="pl-8"
          />
        </div>
      </div>

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载卷列表失败" onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="暂无卷"
          description="资源中尚未设置卷号（volume）字段。请先在资源录入时填写卷号。"
        />
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>卷号</TableHead>
                <TableHead>期数</TableHead>
                <TableHead>文章数</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((v) => (
                <TableRow key={v.volume}>
                  <TableCell className="font-medium">
                    Vol. {v.volume}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{v.issueCount} 期</Badge>
                  </TableCell>
                  <TableCell>{v.articleCount} 篇</TableCell>
                  <TableCell>
                    <Link
                      to="/admin/issues"
                      search={{ volume: v.volume }}
                      className="inline-flex items-center text-muted-foreground hover:text-foreground"
                    >
                      <ChevronRight className="h-4 w-4" />
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
