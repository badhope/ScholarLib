import { useMemo, useState } from 'react'
import { createFileRoute, Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ChevronDown, Download, FileDown, Plus, SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { exportResources, useCatalogStats, useResources } from '@/hooks/api/use-modules'
import type { ResourceType } from '@/lib/types'
import { extractError, formatAuthors, cn } from '@/lib/utils'
import { absurdityLevel, qualityGrade, typeLabel } from '@/lib/resource-labels'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/state'
import { Pagination } from '@/components/common/pagination'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { ResourceCard } from '@/components/mobile/ResourceCard'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export const Route = createFileRoute('/catalog/')({
  component: CatalogListPage,
})

interface CatalogSearch {
  q?: string
  type?: ResourceType
  discipline?: string
  year?: number
  page?: number
}

const TYPE_OPTIONS: { value: ResourceType | 'all'; label: string }[] = [
  { value: 'all', label: '全部类型' },
  { value: 'paper', label: '论文' },
  { value: 'book', label: '图书' },
  { value: 'dataset', label: '数据集' },
  { value: 'tutorial', label: '教程' },
]

const EXPORT_FORMATS = ['bibtex', 'ris', 'csv', 'json'] as const

function CatalogListPage() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as CatalogSearch
  const { isAdmin, isAuthenticated } = useAuth()
  const isMobile = useIsMobile()

  const params = {
    q: search.q || undefined,
    type: search.type,
    discipline: search.discipline || undefined,
    year: search.year,
    page: search.page || 1,
    page_size: 10,
  }

  const { data, isLoading, isError, refetch } = useResources(params)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  // 筛选条件写到 URL，replace 避免每次筛选都污染历史。
  // 顺带清空勾选：翻页/改筛选后旧 id 已经不在页面上，留着会让「导出」
  // 把用户看不见的记录也一起导出去。
  const updateSearch = (patch: Partial<CatalogSearch>) => {
    setSelectedIds([])
    void navigate({
      to: '/catalog',
      search: { ...search, ...patch },
      replace: true,
    })
  }

  const allIds = data?.data.map((r) => r.id) ?? []
  // 用「本页 id 是否都选中」判断，不能比长度：两页各有 10 条时
  // length 相等会让全选框误显示为已勾选。
  const allSelected = allIds.length > 0 && allIds.every((rid) => selectedIds.includes(rid))

  const toggleAll = () => {
    setSelectedIds(allSelected ? [] : allIds)
  }

  const toggleOne = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const onExport = async (format: (typeof EXPORT_FORMATS)[number]) => {
    if (selectedIds.length === 0) {
      toast.error('请先选择资源')
      return
    }
    try {
      await exportResources(selectedIds, format)
      toast.success(`已导出 ${selectedIds.length} 条为 ${format.toUpperCase()}`)
    } catch (err) {
      toast.error(extractError(err, '导出失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="资源目录"
        description="浏览 Rubbish 中所有学术资源。"
        actions={
          isAdmin ? (
            <Button asChild>
              <Link to="/catalog/new">
                <Plus className="h-4 w-4" />
                新建资源
              </Link>
            </Button>
          ) : null
        }
      />

      {/* 栏目（学科）快捷筛选：点击即切换，免去展开下拉的两步操作 */}
      {!isMobile && (
        <DisciplineChips search={search} updateSearch={updateSearch} />
      )}

      {/* 桌面端：筛选常驻卡片（md 及以上） */}
      {!isMobile && (
        <DesktopFilters search={search} updateSearch={updateSearch} />
      )}

      {/* 移动端：筛选收进可折叠面板，默认收起，避免挤占浏览空间 */}
      {isMobile && <MobileFilters search={search} updateSearch={updateSearch} />}

      {/* 批量选择/导出是桌面管理操作，移动端隐藏以保持浏览专注 */}
      {!isMobile && selectedIds.length > 0 && (
        <div className="mb-3 flex items-center justify-between rounded-md border bg-muted/40 px-4 py-2">
          <span className="text-sm">已选 {selectedIds.length} 项</span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4" />
                导出为…
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {EXPORT_FORMATS.map((f) => (
                <DropdownMenuItem key={f} onClick={() => onExport(f)}>
                  {f.toUpperCase()}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3" aria-hidden>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 rounded-lg border bg-card px-4 py-3">
              <Skeleton className="h-4 w-4" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="hidden h-4 w-32 sm:block" />
              <Skeleton className="h-4 w-12" />
              <Skeleton className="hidden h-4 w-24 md:block" />
              <Skeleton className="h-5 w-14 rounded-full" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <ErrorState message="加载资源失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState title="暂无资源" description="尝试调整筛选条件。" />
      ) : isMobile ? (
        // 移动端：卡片列表（独立设计，无批量勾选）
        <div className="space-y-3">
          {data.data.map((r) => (
            <ResourceCard key={r.id} resource={r} />
          ))}
        </div>
      ) : (
        // 桌面端：表格
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  {isAuthenticated && (
                    <TableHead className="w-10">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="全选"
                      />
                    </TableHead>
                  )}
                  <TableHead>标题</TableHead>
                  <TableHead>作者</TableHead>
                  <TableHead className="w-16">年份</TableHead>
                  <TableHead>学科</TableHead>
                  <TableHead className="w-20">类型</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((r) => {
                  const authors = formatAuthors(r.authors)
                  return (
                    <TableRow
                      key={r.id}
                      data-state={selectedIds.includes(r.id) ? 'selected' : undefined}
                    >
                      {isAuthenticated && (
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selectedIds.includes(r.id)}
                            onChange={() => toggleOne(r.id)}
                            aria-label={`选择 ${r.title}`}
                          />
                        </TableCell>
                      )}
                      {/* 长文本列约束列宽 + 截断，防止 160 字符标题把整表撑出视口
                          （对齐 shadcn DataTable 长文本列 max-w+truncate 惯例） */}
                      <TableCell className="max-w-[320px] truncate">
                        <Link
                          to="/catalog/$resourceId"
                          params={{ resourceId: String(r.id) }}
                          className="font-medium hover:text-primary"
                        >
                          {r.title}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-muted-foreground">
                        {authors}
                      </TableCell>
                      <TableCell>{r.year}</TableCell>
                      <TableCell className="max-w-[200px] truncate">
                        {r.discipline}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <Badge variant="secondary">{typeLabel(r.type)}</Badge>
                          {(() => {
                            const grade = qualityGrade(r.quality_grade)
                            return grade ? (
                              <Badge
                                variant="outline"
                                className={`text-[10px] ${grade.className}`}
                                title={`RQS ${r.quality_score ?? ''} / 100 · ${grade.description}`}
                              >
                                {grade.label}
                              </Badge>
                            ) : null
                          })()}
                          {(() => {
                            const level = absurdityLevel(r.absurdity_index)
                            return level ? (
                              <Badge
                                variant={level.variant}
                                className="text-[10px]"
                                title={`荒诞指数 ${r.absurdity_index} / 10 · ${level.description}`}
                              >
                                {level.label}
                              </Badge>
                            ) : null
                          })()}
                          {r.has_file ? (
                            <span
                              className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground"
                              title="提供 PDF 全文"
                            >
                              <FileDown className="h-3 w-3" />
                              PDF
                            </span>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          onPageChange={(p) => updateSearch({ page: p })}
        />
      )}
    </div>
  )
}

// 桌面常驻卡片与移动折叠面板共用同一组筛选字段（此前是整段复制）。
// 两边只有容器布局不同，所以布局由调用方用 className 指定。
function CatalogFilterFields({
  search,
  updateSearch,
  className,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
  className: string
}) {
  const { data: stats } = useCatalogStats()
  const facetDisciplines = Object.keys(stats?.by_discipline ?? {})
  return (
    <div className={className}>
      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">
          搜索（输入后按回车）
        </label>
        <Input
          placeholder="标题/作者/摘要"
          defaultValue={search.q ?? ''}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              updateSearch({ q: (e.target as HTMLInputElement).value, page: 1 })
            }
          }}
        />
      </div>
      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">类型</label>
        <Select
          value={search.type ?? 'all'}
          onValueChange={(v) =>
            updateSearch({
              type: v === 'all' ? undefined : (v as ResourceType),
              page: 1,
            })
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TYPE_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">学科</label>
        <Select
          value={search.discipline ?? 'all'}
          onValueChange={(v) =>
            updateSearch({ discipline: v === 'all' ? undefined : v, page: 1 })
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部学科</SelectItem>
            {(facetDisciplines.length > 0
              ? facetDisciplines
              : search.discipline
                ? [search.discipline]
                : []
            ).map((d) => (
              <SelectItem key={d} value={d}>
                {d}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <label className="text-xs text-muted-foreground">年份</label>
        <Input
          type="number"
          placeholder="如 2024"
          defaultValue={search.year ?? ''}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const v = (e.target as HTMLInputElement).value
              updateSearch({ year: v ? Number(v) : undefined, page: 1 })
            }
          }}
        />
      </div>
    </div>
  )
}

// 移动端筛选：默认收起，点击"筛选"展开。字段与桌面共用，只是容器形态不同。
function MobileFilters({
  search,
  updateSearch,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
}) {
  const [open, setOpen] = useState(false)
  const activeCount = [
    search.q,
    search.type,
    search.discipline,
    search.year,
  ].filter(Boolean).length

  return (
    <div className="mb-4">
      <Button
        type="button"
        variant="outline"
        className="w-full justify-between"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4" />
          筛选
          {activeCount > 0 && (
            <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
              {activeCount}
            </span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">{open ? '收起' : '展开'}</span>
      </Button>

      {open && (
        <div className="mt-3 rounded-lg border bg-muted/30 p-3">
          <DisciplineChips search={search} updateSearch={updateSearch} />
          <CatalogFilterFields
            search={search}
            updateSearch={updateSearch}
            className="mt-3 space-y-3"
          />
        </div>
      )}
    </div>
  )
}

// 桌面端筛选：与移动端同策略——默认收起为一行工具栏（带活跃计数），
// 带着筛选条件进来时自动展开，避免"打开页面先看到一面筛选墙"。
function DesktopFilters({
  search,
  updateSearch,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
}) {
  const activeCount = [
    search.q,
    search.type,
    search.discipline,
    search.year,
  ].filter(Boolean).length
  const [open, setOpen] = useState(() => activeCount > 0)

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="justify-between"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" />
            筛选
            {activeCount > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
                {activeCount}
              </span>
            )}
          </span>
        </Button>
        {activeCount > 0 && !open && (
          <span className="text-xs text-muted-foreground">正在按条件过滤，点击「筛选」可调整</span>
        )}
      </div>

      {open && (
        <div className="mt-3 rounded-lg border bg-muted/30 p-3">
          <CatalogFilterFields
            search={search}
            updateSearch={updateSearch}
            className="grid grid-cols-1 gap-3 md:grid-cols-4"
          />
        </div>
      )}
    </div>
  )
}

// 栏目（学科）快捷筛选：期刊网站的 browse-by-subject 惯例，
// 带篇数计数，点击即筛。超过 8 个时默认收起一排展开按钮 ——
// 已选中的栏目即使排在收起区也会补显出来，不让筛选条件"隐身"。
const CHIP_COLLAPSE_AT = 8

function DisciplineChips({
  search,
  updateSearch,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
}) {
  const { data: stats } = useCatalogStats()
  const [expanded, setExpanded] = useState(false)
  const disciplines = useMemo(
    () => Object.entries(stats?.by_discipline ?? {}).sort((a, b) => b[1] - a[1]),
    [stats],
  )
  if (disciplines.length === 0) return null

  const collapsed = !expanded && disciplines.length > CHIP_COLLAPSE_AT
  const visible = collapsed ? disciplines.slice(0, CHIP_COLLAPSE_AT) : [...disciplines]
  if (collapsed && search.discipline) {
    const idx = disciplines.findIndex(([name]) => name === search.discipline)
    if (idx >= CHIP_COLLAPSE_AT) visible.push(disciplines[idx])
  }
  const hiddenCount = Math.max(0, disciplines.length - visible.length)

  const chipCls = (active: boolean) =>
    cn(
      'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors',
      active
        ? 'border-primary bg-primary text-primary-foreground'
        : 'bg-card text-foreground/80 hover:border-primary/40 hover:text-foreground',
    )

  return (
    <>
    <div className="mb-4 flex flex-wrap items-center gap-1.5" role="group" aria-label="按学科（栏目）快速筛选">
      <button
        type="button"
        className={chipCls(!search.discipline)}
        onClick={() => updateSearch({ discipline: undefined, page: 1 })}
      >
        全部
        <span className="tabular-nums opacity-60">{stats?.total ?? ''}</span>
      </button>
      {visible.map(([name, count]) => (
        <button
          key={name}
          type="button"
          className={chipCls(search.discipline === name)}
          onClick={() => updateSearch({ discipline: name, page: 1 })}
        >
          {name}
          <span className="tabular-nums opacity-60">{count}</span>
        </button>
      ))}
      {collapsed && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          aria-expanded={false}
        >
          更多 {hiddenCount} 个学科
          <ChevronDown className="h-3 w-3" />
        </button>
      )}
      {expanded && disciplines.length > CHIP_COLLAPSE_AT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          aria-expanded
        >
          收起
          <ChevronDown className="h-3 w-3 rotate-180" />
        </button>
      )}
    </div>
    </>
  )
}
