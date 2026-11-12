import { useEffect, useMemo, useState } from 'react'
import { createFileRoute, Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ChevronDown, Download, FileDown, Plus, RefreshCw, SlidersHorizontal, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { exportResources, useCatalogStats, useResources } from '@/hooks/api/use-modules'
import type { ResourceType } from '@/lib/types'
import { extractError, formatAuthors, cn } from '@/lib/utils'
import { contentCategoryLabel, displayTypeLabel, isScholarlyContent } from '@/lib/resource-labels'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/state'
import { Pagination } from '@/components/common/pagination'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { ResourceCard } from '@/components/mobile/ResourceCard'
import { CatalogGridCard } from './catalog-grid-card'
import { FunCatalog } from '@/components/catalog/fun-feed'
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
  category?: 'academic' | 'fun' | 'rant' | 'essay'
  /** 轨道切换（v1.15）：paper=论文（学术），essay=娱乐（fun/rant 同属娱乐）。
   *  不写 = 全部。URL 持久化，刷新不丢。 */
  track?: 'paper' | 'essay'
  /** 论文子类型（/papers 内部分区）：serious=学术论文 / absurd=荒诞论文。 */
  kind?: 'serious' | 'absurd'
  /** 娱乐轨文体（v1.16）：只在 track=essay 时生效 */
  genre?: 'joke' | 'fiction' | 'review' | 'guide' | 'essay' | 'poetry' | 'rant'
  discipline?: string
  year?: number
  page?: number
  view?: 'list' | 'grid'
}

// 论文与副刊是两本刊，入口固定在侧栏与移动端底部 Tab；
// 页面内不再维护第二套轨道分段控件。
const TYPE_OPTIONS: { value: ResourceType | 'all'; label: string }[] = [
  { value: 'all', label: '全部类型' },
  { value: 'paper', label: '论文' },
  { value: 'book', label: '图书' },
  { value: 'dataset', label: '数据集' },
  { value: 'tutorial', label: '教程' },
]

const EXPORT_FORMATS = ['bibtex', 'ris', 'csv', 'json'] as const

/** 固定种子的 Fisher–Yates：刷新页面换 seed，同一次浏览内「换一批」也稳定。 */
function seededShuffle<T>(items: T[], seed: number): T[] {
  const list = items.slice()
  let state = (seed % 2147483647) || 1
  for (let i = list.length - 1; i > 0; i -= 1) {
    state = (state * 48271) % 2147483647
    const j = state % (i + 1)
    ;[list[i], list[j]] = [list[j], list[i]]
  }
  return list
}

export function CatalogListPage({ fixedTrack }: { fixedTrack?: 'paper' | 'essay' } = {}) {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as CatalogSearch
  const { isAdmin, isAuthenticated } = useAuth()
  const isMobile = useIsMobile()

  // 轨道切换 → 后端 ?track=paper|essay（按 content_track 过滤，与旧 content_category 解耦）。
  // fixedTrack 由 /papers、/fun 两条独立路由传入，避免用户从娱乐区又切回混合列表。
  const effectiveTrack: 'paper' | 'essay' | undefined =
    fixedTrack ?? search.track
  // /papers 默认进入「学术论文」；荒诞论文是同页的并列分区，不是另一条轨道。
  const paperKind: 'serious' | 'absurd' = search.kind ?? 'serious'
  const statsTrack = effectiveTrack === 'essay' ? 'essay' : effectiveTrack === 'paper' ? 'paper' : undefined
  const routePath: '/papers' | '/fun' | '/catalog' = fixedTrack === 'paper'
    ? '/papers'
    : fixedTrack === 'essay'
      ? '/fun'
      : '/catalog'

  const params = {
    q: search.q || undefined,
    type: search.type,
    category: search.category || undefined,
    track: effectiveTrack,
    paper_kind: effectiveTrack === 'paper' ? paperKind : undefined,
    genre: effectiveTrack === 'essay' ? search.genre : undefined,
    discipline: search.discipline || undefined,
    year: search.year,
    page: search.page || 1,
    page_size: 10,
  }

  const { data, isLoading, isError, refetch } = useResources(params)
  const { data: stats } = useCatalogStats(statsTrack)

  // `/papers` 顶部随机推荐：单独拉论文池，用于抽取推荐卡片；
  // 两个 tab 的计数不要从这里数——池子只有 50 条，会把 240 篇截成 50。
  const { data: paperPool } = useResources(
    { track: 'paper', page: 1, page_size: 50 },
    fixedTrack === 'paper',
  )
  const [pickSeed, setPickSeed] = useState(() => Math.floor(Math.random() * 2147483646) + 1)
  const seriousCount = stats?.by_paper_kind?.serious ?? 0
  const absurdCount = stats?.by_paper_kind?.absurd ?? 0
  const paperPicks = useMemo(
    () =>
      seededShuffle(
        (paperPool?.data ?? []).filter((r) => (r.track ?? 'serious') === paperKind),
        pickSeed,
      ).slice(0, 4),
    [paperPool?.data, pickSeed, paperKind],
  )

  const [selectedIds, setSelectedIds] = useState<number[]>([])
  // 默认视图 = 九宫格（v1.15）：封面浏览是目录页第一动作；?view=list 时才切列表。
  const viewMode: 'list' | 'grid' = search.view === 'list' ? 'list' : 'grid'

  // 筛选条件写到 URL，replace 避免每次筛选都污染历史。
  // 顺带清空勾选：翻页/改筛选后旧 id 已经不在页面上，留着会让「导出」
  // 把用户看不见的记录也一起导出去。
  const updateSearch = (patch: Partial<CatalogSearch>) => {
    setSelectedIds([])
    void navigate({
      to: routePath,
      search: { ...search, ...patch },
      replace: true,
    } as never)
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

  if (effectiveTrack === 'essay') {
    return (
      <FunCatalog
        data={data}
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        stats={stats}
        search={search}
        updateSearch={updateSearch}
        routePath={routePath}
      />
    )
  }

  // 总目录不再把所有内容混成一列：先让读者选「论文 / 副刊」，
  // 论文里再选「学术 / 荒诞」。带检索词时仍走下面的跨区结果列表。
  const hasCatalogFilter = Boolean(
    search.q || search.type || search.category || search.discipline || search.year,
  )
  if (!fixedTrack && !hasCatalogFilter) {
    return <CatalogHub />
  }

  return (
    <div>
      <PageHeader
        title={
          search.q
            ? '搜索结果'
            : fixedTrack === 'paper'
              ? paperKind === 'absurd'
                ? '荒诞论文'
                : '学术论文'
              : fixedTrack === 'essay'
                ? '副刊'
                : '论文与副刊'
        }
        description={
          search.q
            ? '跨论文与副刊检索；点卡片进入对应版式。'
            : fixedTrack === 'essay'
              ? '小说、随笔、评论、诗歌与吐槽；独立成刊，不用论文体、不参与学术计分。'
              : fixedTrack === 'paper'
                ? paperKind === 'absurd'
                  ? '严格论文格式，用可核查材料一本正经地论证荒诞命题；与学术论文同用百分制评审。'
                  : '真实问题、可核查材料、正经论证；副刊与荒诞论文都在各自独立分区。'
                : '论文与副刊分属两本刊；论文内部再分学术论文与荒诞论文。'
        }
        actions={
          isAdmin ? (
            <Button asChild>
              <Link to="/catalog/new">
                <Plus className="h-4 w-4" />
                新建资源
              </Link>
            </Button>
          ) : undefined
        }
      />

      {/* 论文内部两区：学术论文 / 荒诞论文。默认学术，并列切换；
          副刊是另一条轨道，不在这组标签里。 */}
      {fixedTrack === 'paper' && !search.q ? (
        <div
          className="mb-5 grid grid-cols-2 gap-2 rounded-2xl border bg-card p-1.5"
          role="tablist"
          aria-label="论文分区"
        >
          {([
            { id: 'serious', label: '学术论文', note: '正经研究', count: seriousCount },
            { id: 'absurd', label: '荒诞论文', note: '一本正经胡说八道', count: absurdCount },
          ] as const).map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={paperKind === tab.id}
              onClick={() => updateSearch({ kind: tab.id, page: 1 })}
              className={cn(
                'rounded-xl px-3 py-2.5 text-left transition-colors',
                paperKind === tab.id
                  ? 'bg-primary text-primary-foreground shadow-sm'
                  : 'hover:bg-muted/50',
              )}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-serif text-sm font-semibold sm:text-base">{tab.label}</span>
                <span className={cn('text-xs tabular-nums', paperKind === tab.id ? 'opacity-80' : 'text-muted-foreground')}>
                  {tab.count} 篇
                </span>
              </span>
              <span className={cn('mt-0.5 block text-[11px]', paperKind === tab.id ? 'opacity-80' : 'text-muted-foreground')}>
                {tab.note}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {/* 1626：论文栏目顶部随机推荐。每次刷新换一批，不改变下面正式目录的排序。 */}
      {fixedTrack === 'paper' && !search.q && paperPicks.length > 0 ? (
        <section className="mb-5 rounded-2xl border border-amber-200/70 bg-gradient-to-br from-amber-50/80 via-card to-card p-3 sm:p-4 dark:border-amber-500/20 dark:from-amber-950/20">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <Sparkles className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-300" />
              <h2 className="font-serif text-base font-semibold tracking-tight sm:text-lg">
                随机推荐
              </h2>
              <span className="hidden text-[11px] text-muted-foreground sm:inline">
                每次刷新换一批，让每篇都有机会
              </span>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 text-xs text-muted-foreground"
              onClick={() => setPickSeed(Math.floor(Math.random() * 2147483646) + 1)}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              换一批
            </Button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
            {paperPicks.map((r) => (
              <Link
                key={r.id}
                to="/catalog/$resourceId"
                params={{ resourceId: String(r.id) }}
                className="group flex min-h-24 flex-col rounded-xl border border-border/70 bg-background/80 p-3 transition-colors hover:border-amber-300 hover:bg-card dark:hover:border-amber-500/30"
              >
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="rounded-full bg-amber-100 px-1.5 py-0.5 font-medium text-amber-900 dark:bg-amber-900/40 dark:text-amber-100">
                    {r.track === 'absurd' ? '荒诞论文' : '学术论文'}
                  </span>
                  <span>{r.year}</span>
                </div>
                <h3 className="mt-1.5 line-clamp-2 font-serif text-sm font-semibold leading-snug tracking-tight group-hover:text-amber-900 dark:group-hover:text-amber-200">
                  {r.title}
                </h3>
                <p className="mt-auto truncate pt-2 text-[11px] text-muted-foreground">
                  {formatAuthors(r.authors) || '佚名'}
                  {r.reads != null ? ` · 阅读 ${r.reads}` : ''}
                </p>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {/* 顶部只留视图切换。论文 / 副刊的主入口在侧栏与移动端「更多」菜单，
          页面内不再放第二套轨道分段，避免同一屏出现两个切换器。 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {fixedTrack === 'paper'
            ? paperKind === 'absurd'
              ? '荒诞论文：论文格式与评审标准不变，命题一本正经地荒诞'
              : '学术论文：正式评审 · 百分制计分 · 进 R 因子'
            : fixedTrack === 'essay'
              ? '副刊轨：非论文格式 · 格式与合规检查 · 不计分 · 独立成刊'
              : '论文与副刊分属两条轨道，从左侧导航或底部 Tab 进入对应目录。'}
        </p>
        <ViewSwitcher
          value={viewMode}
          onChange={(view) => updateSearch({ view })}
        />
      </div>

      {/* 栏目（学科）快捷筛选：点击即切换，免去展开下拉的两步操作 */}
      {!isMobile && (
        <DisciplineChips search={search} updateSearch={updateSearch} track={statsTrack} />
      )}

      {/* 桌面端：筛选常驻卡片（md 及以上） */}
      {!isMobile && (
        <DesktopFilters search={search} updateSearch={updateSearch} />
      )}

      {/* 移动端：筛选收进可折叠面板，默认收起，避免挤占浏览空间 */}
      {isMobile && <MobileFilters search={search} updateSearch={updateSearch} track={statsTrack} />}

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
        <EmptyState
          title="这一区还空着"
          description={fixedTrack === 'paper' ? '换个筛选条件，或切到另一个论文分区看看。' : '还没有匹配的副刊，换个筛选条件。'}
        />
      ) : viewMode === 'grid' ? (
        // 手机端单列：390px 下两列会把中文标题压成半行，读者必须先猜标题；
        // 平板 2 列、桌面 4 列。九宫格留给桌面，手机优先可读性。
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {data.data.map((r) => (
            <CatalogGridCard key={r.id} resource={r} />
          ))}
        </div>
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
            {/* 平板宽度下必须 table-fixed：auto 布局会用 min-content 撑宽，
                truncate/max-w 全部失效，整表又被裁掉。桌面恢复 auto。 */}
            <Table className="table-fixed lg:table-auto">
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
                  <TableHead className="w-[45%] lg:w-auto">标题</TableHead>
                  <TableHead className="w-[30%] lg:w-auto">作者</TableHead>
                  {/* 平板（768–1023）放不下 6 列：年份/学科先让位，
                      否则整表被裁成「标题 + 作者」两列，读者以为坏了。 */}
                  <TableHead className="hidden w-16 lg:table-cell">年份</TableHead>
                  <TableHead className="hidden lg:table-cell">学科</TableHead>
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
                      <TableCell className="hidden lg:table-cell">{r.year}</TableCell>
                      <TableCell className="hidden max-w-[200px] truncate lg:table-cell">
                        {r.discipline}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <Badge variant="secondary">{displayTypeLabel(r.type, r.content_category, r.content_track, r.track)}</Badge>
                          {r.is_special_issue ? (
                            <Badge variant="outline" className="border-rose-300 text-rose-700 text-[10px]">
                              特别篇
                            </Badge>
                          ) : null}
                         {isScholarlyContent(r.content_category, r.content_track) && r.content_category ? (
                            <Badge variant="outline" className="text-[10px] bg-primary/10 text-primary border-primary/25">
                              {contentCategoryLabel(r.content_category)}
                            </Badge>
                          ) : null}
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

// 总目录落地页：三区入口。读者先选「论文 / 副刊」，论文内部再选
// 「学术论文 / 荒诞论文」；不把 274 篇混在一列里。
function CatalogHub() {
  const papers = useResources({ track: 'paper', page: 1, page_size: 30, sort: 'created_at', order: 'desc' })
  const essays = useResources({ track: 'essay', page: 1, page_size: 5, sort: 'created_at', order: 'desc' })
  const paperRows = papers.data?.data ?? []
  const seriousRows = paperRows.filter((r) => (r.track ?? 'serious') === 'serious')
  const absurdRows = paperRows.filter((r) => r.track === 'absurd')
  const essayRows = essays.data?.data ?? []

  const zoneLink = 'group flex items-start gap-3 rounded-xl border bg-card p-3 transition-colors hover:border-primary/40 hover:bg-muted/20'
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="目录"
        description="论文与副刊是两本刊。论文内部再分学术论文与荒诞论文：前者正经研究，后者严格论文格式但一本正经地论证荒诞命题。"
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border bg-gradient-to-br from-card to-muted/20 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">Paper</p>
              <h2 className="mt-1 font-serif text-xl font-semibold">论文</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {seriousRows.length} 篇学术论文 · {absurdRows.length} 篇荒诞论文
              </p>
            </div>
            <Link to="/papers" className="shrink-0 rounded-full border px-3 py-1 text-xs hover:bg-background">
              进入论文区
            </Link>
          </div>
          <div className="mt-4 grid gap-2">
            <Link to="/papers" search={{ kind: 'serious' }} className={zoneLink}>
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
              <span className="min-w-0">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">学术论文</span>
                  <span className="text-xs tabular-nums text-muted-foreground">{seriousRows.length} 篇</span>
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">真实问题、可核查材料、正经论证</span>
              </span>
            </Link>
            <Link to="/papers" search={{ kind: 'absurd' }} className={zoneLink}>
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-500" />
              <span className="min-w-0">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">荒诞论文</span>
                  <span className="text-xs tabular-nums text-muted-foreground">{absurdRows.length} 篇</span>
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">论文格式、一本正经胡说八道、有论证有依据</span>
              </span>
            </Link>
          </div>
          <div className="mt-4 border-t pt-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">最新论文</p>
            <div className="space-y-2">
              {paperRows.slice(0, 3).map((r) => (
                <Link key={r.id} to="/catalog/$resourceId" params={{ resourceId: String(r.id) }} className="block text-sm hover:text-primary">
                  <span className="mr-1.5 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                    {r.track === 'absurd' ? '荒诞' : '学术'}
                  </span>
                  <span className="line-clamp-1">{r.title}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-2xl border bg-gradient-to-br from-card to-muted/20 p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">Supplement</p>
              <h2 className="mt-1 font-serif text-xl font-semibold">副刊</h2>
              <p className="mt-1 text-xs text-muted-foreground">小说、随笔、评论、指南、吐槽；不用论文体、不计分</p>
            </div>
            <Link to="/fun" className="shrink-0 rounded-full border px-3 py-1 text-xs hover:bg-background">
              进入副刊
            </Link>
          </div>
          <div className="mt-4 border-t pt-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">最新副刊</p>
            <div className="space-y-2">
              {essayRows.map((r) => (
                <Link key={r.id} to="/catalog/$resourceId" params={{ resourceId: String(r.id) }} className="block text-sm hover:text-primary">
                  <span className="line-clamp-1">{r.title}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

// 视图切换：九宫格（封面浏览，默认）/ 列表（紧凑行）。状态写进 URL ?view=，
// 刷新与分享链接都不丢；九宫格在前、列表在后，与默认视图顺序一致。
function ViewSwitcher({
  value,
  onChange,
}: {
  value: 'list' | 'grid'
  onChange: (view: 'list' | 'grid') => void
}) {
  return (
    <div
      className="inline-flex rounded-md border p-0.5 text-xs"
      role="group"
      aria-label="切换视图"
    >
      {(['grid', 'list'] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={cn(
            'rounded px-3 py-1 transition-colors',
            value === v
              ? 'bg-primary font-medium text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {v === 'list' ? '列表' : '九宫格'}
        </button>
      ))}
    </div>
  )
}

// 目录搜索：350ms 防抖的「输入即搜」，回车立即提交。
// 为什么防抖而不是每次击键都发请求：目录查询是聚合接口，逐键请求
// 会放大后端压力；比回车触发多的价值是无需学习成本的即时反馈。
function DebouncedSearchInput({
  initial,
  onCommit,
}: {
  initial: string
  onCommit: (q: string) => void
}) {
  const [value, setValue] = useState(initial)
  useEffect(() => {
    setValue(initial)
  }, [initial])
  useEffect(() => {
    if (value === initial) return
    const timer = setTimeout(() => onCommit(value), 350)
    return () => clearTimeout(timer)
  }, [value, initial, onCommit])
  return (
    <Input
      placeholder="标题/作者/摘要"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onCommit(value)
      }}
    />
  )
}

// 桌面常驻卡片与移动折叠面板共用同一组筛选字段（此前是整段复制）。
// 两边只有容器布局不同，所以布局由调用方用 className 指定。
function CatalogFilterFields({
  search,
  updateSearch,
  className,
  hideSearch = false,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
  className: string
  hideSearch?: boolean
}) {
  const { data: stats } = useCatalogStats()
  const facetDisciplines = Object.keys(stats?.by_discipline ?? {})
  return (
    <div className={className}>
      {hideSearch ? null : (
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground">
            搜索（输入即搜，回车立即）
          </label>
          <DebouncedSearchInput
            initial={search.q ?? ''}
            onCommit={(q) => updateSearch({ q: q || undefined, page: 1 })}
          />
        </div>
      )}
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
  track,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
  track?: 'paper' | 'essay'
}) {
  const [open, setOpen] = useState(false)
  const activeCount = [
    search.q,
    search.type,
    search.discipline,
    search.year,
  ].filter(Boolean).length

  return (
    <div className="mb-4 space-y-2">
      {/* 搜索是目录页的第一动作，不再藏进「筛选」里：手机用户不用先展开面板 */}
      <DebouncedSearchInput
        initial={search.q ?? ''}
        onCommit={(q) => updateSearch({ q: q || undefined, page: 1 })}
      />
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
          <DisciplineChips search={search} updateSearch={updateSearch} track={track} />
          <CatalogFilterFields
            search={search}
            updateSearch={updateSearch}
            className="mt-3 space-y-3"
            hideSearch
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
  track,
}: {
  search: CatalogSearch
  updateSearch: (patch: Partial<CatalogSearch>) => void
  track?: 'paper' | 'essay'
}) {
  const { data: stats } = useCatalogStats(track)
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
        <span className="tabular-nums opacity-60">{stats?.total ?? 0}</span>
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
