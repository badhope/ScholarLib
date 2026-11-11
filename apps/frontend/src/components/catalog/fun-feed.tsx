import { Link } from '@tanstack/react-router'
import { ArrowRight, ChevronDown, Search, Sparkles } from 'lucide-react'
import type { ResourceResponse, ResourceStats } from '@/lib/types'
import { ESSAY_GENRES, essayGenreMeta } from '@/lib/essay-genres'
import { ArticleCover } from '@/components/common/article-cover'
import { formatAuthors, cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState } from '@/components/common/state'
import { Skeleton } from '@/components/ui/skeleton'

// 娱乐区（v1.16）：不是“论文目录换个底色”，而是一套自己的阅读入口。
// 论文区回答“这篇文章可不可信”；娱乐区回答“这篇东西好不好玩”。
// 因此这里不出现学科、CLC、评分、PDF 徽章，只用文体 + 作者 + 阅读量。

interface FunCatalogProps {
  data?: { data: ResourceResponse[]; meta: { page: number; total_pages: number; total: number } }
  isLoading: boolean
  isError: boolean
  onRetry: () => void
  stats?: ResourceStats
  search: { q?: string; genre?: string; page?: number }
  updateSearch: (patch: Record<string, unknown>) => void
  routePath: '/papers' | '/fun' | '/catalog'
}

function plainPreview(text?: string | null): string {
  return (text ?? '')
    .replace(/[#>*_`~]/g, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 150)
}

export function FunCatalog({
  data,
  isLoading,
  isError,
  onRetry,
  stats,
  search,
  updateSearch,
  routePath,
}: FunCatalogProps) {
  const genreCounts = stats?.by_genre ?? {}
  const visibleGenres = ESSAY_GENRES.filter((g) => (genreCounts[g.value] ?? 0) > 0)
  const totalAll = Object.values(genreCounts).reduce((a, b) => a + b, 0) || data?.meta.total || 0

  const go = (patch: Record<string, unknown>) => {
    updateSearch({ ...patch, page: 1 })
  }

  // 编辑部栏目说明不跟普通副刊稿抢头图：抽成顶部一条紧凑说明栏，
  // 首篇推荐也只从真正的副刊稿里选，避免“编辑推荐”永远落在公告上。
  const editorialNotes = data?.data.filter(isEditorialNote) ?? []
  const stories = data?.data.filter((r) => !isEditorialNote(r)) ?? []
  const featuredId = stories[0]?.id
  const rest = stories.slice(1)

  return (
    <div className="mx-auto max-w-5xl px-4 py-3 sm:px-6 sm:py-6">
      {/* 刊头只负责“这是副刊”。筛选、搜索、公告全部下移，首屏不再堆四层控件。 */}
      <header className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-card via-card to-accent/25 px-4 py-5 shadow-sm sm:px-8 sm:py-7">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-12 -top-14 h-44 w-44 rotate-12 rounded-full bg-amber-300/20 blur-2xl dark:bg-amber-500/10"
        />
        <div className="relative">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary/70 sm:text-[11px] sm:tracking-[0.24em]">
              Rubbish · Off the Record
            </p>
            <div className="inline-flex shrink-0 items-center rounded-full border border-border bg-card p-0.5 text-[11px]">
              <Link to="/papers" className="rounded-full px-2.5 py-0.5 text-muted-foreground hover:text-foreground">
                论文
              </Link>
              <span className="rounded-full bg-primary px-2.5 py-0.5 font-medium text-primary-foreground">副刊</span>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-1">
            <h1 className="section-title text-2xl font-semibold tracking-tight sm:text-4xl">
              副刊
            </h1>
            <span className="pb-0.5 text-xs text-muted-foreground sm:pb-1 sm:text-sm">
              不正经研究所，认真你就输了
            </span>
          </div>
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground sm:mt-2 sm:leading-7">
            小说、随笔、评论、指南，以及大量假装是论文的整活。这里不计分、不进 R 因子、
            不走同行评审——只负责让你在改稿的间隙笑一下。
          </p>
        </div>
      </header>

      {/* 文体 + 搜索合并成一条工具栏。移动端一行下拉、一行搜索，不再在刊头里叠控件。 */}
      <div className="mt-3 rounded-2xl border border-border bg-card p-3 sm:p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="sm:hidden">
            <select
              aria-label="选择副刊文体"
              value={search.genre ?? ''}
              onChange={(e) => go({ genre: e.target.value || undefined })}
              className="h-10 w-full rounded-full border border-border bg-card px-4 text-sm text-foreground outline-none transition-colors focus:border-primary/40"
            >
              <option value="">
                全部文体 · {totalAll}
              </option>
              {visibleGenres.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label} · {genreCounts[g.value]}
                </option>
              ))}
            </select>
          </div>

          <div className="hidden min-w-0 flex-1 flex-wrap gap-1.5 sm:flex">
            <GenrePill active={!search.genre} onClick={() => go({ genre: undefined })}>
              全部 · {totalAll}
            </GenrePill>
            {visibleGenres.map((g) => (
              <GenrePill
                key={g.value}
                active={search.genre === g.value}
                onClick={() => go({ genre: g.value })}
                title={g.hint}
              >
                {g.label} · {genreCounts[g.value]}
              </GenrePill>
            ))}
          </div>

          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              defaultValue={search.q ?? ''}
              placeholder="搜标题、作者，或者一个梗"
              className="h-10 rounded-full pl-9 text-sm"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  go({ q: (e.target as HTMLInputElement).value.trim() || undefined })
                }
              }}
            />
          </div>
        </div>

        <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
          <Link
            to="/policies"
            className="inline-flex shrink-0 items-center gap-1 font-medium text-primary hover:underline"
          >
            格式与版式
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
          <span>
            {search.genre ? `${essayGenreMeta(search.genre).label} · ` : ''}
            {data?.meta.total ?? 0} 篇
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-2xl" />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-6">
          <ErrorState message="副刊没打开" onRetry={onRetry} />
        </div>
      ) : !data || data.data.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            title="这一栏还空着"
            description={
              search.genre
                ? '换个文体看看，或者直接把这篇稿子投过来。'
                : '还没有匹配的内容，换个关键词试试。'
            }
          />
        </div>
      ) : (
        <>
          {/* 公告默认折叠：它们重要，但不该和正文抢同一屏。 */}
          {editorialNotes.length > 0 && (
            <details className="group mt-3 rounded-xl border border-dashed border-border bg-muted/30 px-3 py-2 open:bg-muted/45">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[11px] font-medium text-foreground/80">
                <span>
                  公告与说明
                  <span className="ml-1 font-normal text-muted-foreground">· {editorialNotes.length} 条</span>
                </span>
                <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-2 grid gap-1.5 border-t border-border pt-2 sm:grid-cols-2">
                {editorialNotes.map((r) => (
                  <Link
                    key={r.id}
                    to="/catalog/$resourceId"
                    params={{ resourceId: String(r.id) }}
                    className="truncate text-[11px] text-muted-foreground hover:text-foreground hover:underline"
                  >
                    {r.title}
                  </Link>
                ))}
                <Link
                  to="/sections"
                  className="inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline"
                >
                  全部栏目
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            </details>
          )}

          <div className="mt-5 space-y-7">
            {featuredId != null && (
              <section>
                <SectionHead title="编辑推荐" note="本周先看这篇" />
                <div className="mt-3">
                  <FunCard resource={stories[0]} featured />
                </div>
              </section>
            )}

            {rest.length > 0 && (
              <section>
                <SectionHead
                  title="最新副刊"
                  note={data.meta.total ? `共 ${data.meta.total} 篇` : undefined}
                />
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {rest.map((r) => (
                    <FunCard key={r.id} resource={r} featured={false} />
                  ))}
                </div>
              </section>
            )}

            {visibleGenres.length > 0 && (
              <section>
                <SectionHead title="按文体逛" note="选一个门类，换一种笑法" />
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {visibleGenres.map((g) => {
                    const active = search.genre === g.value
                    return (
                      <button
                        key={g.value}
                        type="button"
                        onClick={() => go({ genre: active ? undefined : g.value })}
                        className={cn(
                          'group flex items-center gap-2.5 rounded-xl border px-3 py-3 text-left transition-all',
                          active
                            ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                            : 'border-border bg-card hover:-translate-y-0.5 hover:border-primary/30 hover:bg-accent/25',
                        )}
                      >
                        <span className="text-xl leading-none">{g.emoji}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium">{g.label}</span>
                          <span
                            className={cn(
                              'mt-0.5 block truncate text-[11px]',
                              active ? 'text-white/75' : 'text-muted-foreground',
                            )}
                          >
                            {genreCounts[g.value]} 篇
                            <span className="hidden sm:inline"> · {g.hint}</span>
                          </span>
                        </span>
                        <ArrowRight
                          className={cn(
                            'h-3.5 w-3.5 shrink-0 transition-transform group-hover:translate-x-0.5',
                            active ? 'text-white/80' : 'text-muted-foreground',
                          )}
                        />
                      </button>
                    )
                  })}
                </div>
              </section>
            )}
          </div>

          <div className="mt-7 flex items-center justify-between gap-3 border-t border-border pt-4">
            <Link
              to={routePath === '/fun' ? '/papers' : routePath}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              想看论文？去论文区
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Pagination
              page={data.meta.page}
              totalPages={data.meta.total_pages}
              onPageChange={(p) => updateSearch({ page: p })}
            />
          </div>
        </>
      )}
    </div>
  )
}

function SectionHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border pb-2">
      <h2 className="font-serif text-lg font-semibold tracking-tight sm:text-xl">{title}</h2>
      {note ? <span className="text-[11px] text-muted-foreground">{note}</span> : null}
    </div>
  )
}

function GenrePill({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        'shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
        active
          ? 'border-primary bg-primary text-primary-foreground shadow-sm'
          : 'border-border bg-card text-foreground/80 hover:border-primary/30 hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function isEditorialNote(resource: ResourceResponse): boolean {
  const tags = (resource.tags ?? []).map(String)
  return formatAuthors(resource.authors) === 'Rubbish 编辑部' && (tags.includes('栏目说明') || tags.includes('编辑部'))
}

function FunCard({ resource, featured }: { resource: ResourceResponse; featured: boolean }) {
  const genre = essayGenreMeta(resource.content_genre)
  const preview = plainPreview(resource.preview || resource.abstract)

  if (featured) {
    return (
      <Link
        to="/catalog/$resourceId"
        params={{ resourceId: String(resource.id) }}
        className={cn(
          'card-lift group grid overflow-hidden rounded-2xl border border-border bg-card',
          resource.cover_image ? 'md:grid-cols-[1.15fr_0.85fr]' : 'md:grid-cols-1',
        )}
      >
        <div className="order-1 flex flex-col justify-center gap-3 p-5 sm:p-7 md:order-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full bg-primary px-2.5 py-1 font-medium text-primary-foreground">
              {genre.label}
            </span>
            {resource.is_special_issue ? (
              <span className="rounded-full border border-border px-2 py-0.5 text-muted-foreground">
                长文
              </span>
            ) : null}
            <span className="text-muted-foreground">{resource.year}</span>
          </div>
          <h2 className="font-serif text-xl font-semibold leading-snug tracking-tight sm:text-2xl">
            {resource.title}
          </h2>
          <p className="line-clamp-3 text-sm leading-7 text-muted-foreground">{preview}</p>
          <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{formatAuthors(resource.authors) || '佚名'}</span>
            {resource.reads != null ? <span>· 阅读 {resource.reads}</span> : null}
            <span className="inline-flex items-center gap-1 text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              编辑推荐
            </span>
          </div>
        </div>
        <div
          className="relative order-2 hidden overflow-hidden md:order-2 md:block md:min-h-[260px]"
        >
          <ArticleCover
            resource={resource}
            showDiscipline={false}
            aspect="aspect-[16/10] md:h-full md:aspect-auto"
            className="h-full"
          />
          {!resource.cover_image ? (
            <span className="pointer-events-none absolute inset-0 grid place-items-center text-4xl">
              {genre.emoji}
            </span>
          ) : null}
        </div>
      </Link>
    )
  }

  return (
    <Link
      to="/catalog/$resourceId"
      params={{ resourceId: String(resource.id) }}
      className="group grid grid-cols-[92px_1fr] gap-4 rounded-2xl border border-transparent bg-card/70 p-3 transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card sm:grid-cols-[120px_1fr] sm:p-4"
    >
      <div className="relative aspect-square overflow-hidden rounded-xl">
        <ArticleCover resource={resource} showDiscipline={false} className="h-full" />
        {!resource.cover_image ? (
          <span className="pointer-events-none absolute inset-0 grid place-items-center text-2xl">
            {genre.emoji}
          </span>
        ) : null}
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="font-medium text-primary">{genre.label}</span>
          <span>·</span>
          <span>{resource.year}</span>
          {resource.reads != null ? <span>· 阅读 {resource.reads}</span> : null}
        </div>
        <h3 className="mt-1 line-clamp-2 font-serif text-base font-semibold leading-snug tracking-tight sm:text-lg">
          {resource.title}
        </h3>
        <p className="mt-1.5 line-clamp-2 text-xs leading-6 text-muted-foreground sm:text-sm">
          {preview}
        </p>
        <p className="mt-2 truncate text-[11px] text-muted-foreground">
          {formatAuthors(resource.authors) || '佚名'}
        </p>
      </div>
    </Link>
  )
}
