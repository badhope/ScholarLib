import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import {
  Bookmark,
  ChevronLeft,
  FileDown,
  FileText,
  Pencil,
  Share2,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import type { ResourceResponse } from '@/lib/types'
import { essayGenreMeta } from '@/lib/essay-genres'
import { formatAuthors } from '@/lib/utils'
import { ManuscriptView } from '@/components/common/manuscript-view'
import { Comments } from '@/components/common/comments'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import PdfImagePreview from '@/components/pdf-image-preview'

// 娱乐文章页（v1.16）：和论文详情页不是同一套排版。
// 论文页是“看一份学术记录”：摘要卡、CLC、引用、PDF、评审信息、R 评分；
// 娱乐页是“看一篇网文”：大标题、作者、封面、正文、标签、评论。
// 这里刻意不渲染任何学术块，也不使用论文页的 3/4 封面卡与侧栏。

interface FunArticleProps {
  data: ResourceResponse
  progress: number
  isAuthenticated: boolean
  isAdmin: boolean
  onEdit: () => void
  onDelete: () => void
  onSave: () => void
  canClaim?: boolean
  claimOpen?: boolean
}

export function FunArticle({
  data,
  progress,
  isAuthenticated,
  isAdmin,
  onEdit,
  onDelete,
  onSave,
  canClaim,
  claimOpen,
}: FunArticleProps) {
  const genre = essayGenreMeta(data.content_genre)
  const [fatal, setFatal] = useState<unknown>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const author = data.authors_detail?.[0]
  const authorName = author?.name || formatAuthors(data.authors) || '佚名'
  const initial = authorName.trim().slice(0, 1).toUpperCase()

  return (
    <div className="-mx-4 min-h-screen bg-[#fbf8f3] pb-16 dark:bg-background sm:-mx-6">
      <div className="fixed left-0 top-0 z-50 h-[2px] w-full bg-transparent">
        <div
          className="h-full bg-amber-600 transition-[width] duration-150"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="mx-auto max-w-3xl px-4 pt-4 sm:px-6 sm:pt-6">
        <div className="flex items-center justify-between gap-2">
          <Link
            to="/fun"
            className="inline-flex min-h-[36px] shrink-0 items-center whitespace-nowrap text-sm text-muted-foreground hover:text-amber-700"
          >
            <ChevronLeft className="mr-1 h-4 w-4" />
            副刊
          </Link>
          <div className="flex min-w-0 items-center gap-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 gap-1 px-2 text-muted-foreground"
              aria-label="收藏"
              onClick={() => {
                if (!isAuthenticated) {
                  toast.error('登录后才能收藏')
                  return
                }
                onSave()
              }}
            >
              <Bookmark className="h-4 w-4" />
              <span className="hidden sm:inline">收藏</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 gap-1 px-2 text-muted-foreground"
              aria-label="分享"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(window.location.href)
                  toast.success('链接已复制')
                } catch {
                  toast.error('复制失败，手动复制地址栏吧')
                }
              }}
            >
              <Share2 className="h-4 w-4" />
              <span className="hidden sm:inline">分享</span>
            </Button>
            {data.has_markdown ? (
              <>
                <Button asChild variant="ghost" size="sm" className="h-8 shrink-0 gap-1 px-2 text-muted-foreground">
                  <a href={`/api/catalog/${data.id}/export?format=pdf&v=21`} download aria-label="下载副刊 PDF">
                    <FileDown className="h-4 w-4" />
                    PDF
                  </a>
                </Button>
                <Button asChild variant="ghost" size="sm" className="h-8 shrink-0 gap-1 px-2 text-muted-foreground">
                  <a href={`/api/catalog/${data.id}/export?format=docx&v=21`} download aria-label="下载副刊 Word">
                    <FileDown className="h-4 w-4" />
                    Word
                  </a>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 shrink-0 gap-1 px-2 text-muted-foreground"
                  aria-label="PDF 版式预览"
                  onClick={() => setPreviewOpen(true)}
                >
                  <FileText className="h-4 w-4" />
                  <span className="hidden sm:inline">预览</span>
                </Button>
              </>
            ) : null}
            {isAdmin ? (
              <>
                <Button variant="ghost" size="sm" className="h-8 shrink-0 gap-1 px-2" aria-label="编辑" onClick={onEdit}>
                  <Pencil className="h-4 w-4" />
                  <span className="hidden sm:inline">编辑</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 shrink-0 gap-1 px-2 text-destructive"
                  aria-label="删除"
                  onClick={onDelete}
                >
                  <Trash2 className="h-4 w-4" />
                  <span className="hidden sm:inline">删除</span>
                </Button>
              </>
            ) : null}
          </div>
        </div>

        <header className="mt-8">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded-full bg-amber-600 px-2.5 py-1 font-medium text-white">
              {genre.emoji} {genre.label}
            </span>
            
            <span>{data.year}</span>
            {data.reads != null ? <span>· 阅读 {data.reads}</span> : null}
            {data.is_special_issue ? (
              <span className="rounded-full border border-rose-300 px-2 py-0.5 text-rose-700">
                长文
              </span>
            ) : null}
          </div>
          <h1 className="mt-4 text-balance font-serif text-[1.7rem] font-semibold leading-[1.35] tracking-tight sm:text-4xl">
            {data.title}
          </h1>
          <div className="mt-5 flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-amber-100 text-sm font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200">
              {initial}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{authorName}</p>
              <p className="text-xs text-muted-foreground">
                作者
                {author?.affiliation ? ` · ${author.affiliation}` : ''}
              </p>
            </div>
            {claimOpen ? (
              <Link
                to="/claim/$resourceId"
                params={{ resourceId: String(data.id) }}
                className="shrink-0 whitespace-nowrap rounded-full border border-amber-300/80 px-2.5 py-1 text-[11px] text-amber-900 hover:bg-amber-50 dark:border-amber-500/30 dark:text-amber-200"
              >
                {canClaim ? '我是作者，去认领' : '作者认领'}
              </Link>
            ) : null}
          </div>
        </header>

        <article className="mt-8" id="article">
          {fatal ? (
            <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/20">
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                这篇的正文暂时打不开。可以稍后刷新，或者去讨论区催更。
              </CardContent>
            </Card>
          ) : (
            <ManuscriptView
              resourceId={data.id}
              initialPercent={progress}
              onProgress={() => {}}
              hideTocNav
              useWindowScroll
              contentCategory={data.content_category}
              contentTrack={data.content_track}
              abstract={data.abstract}
              title={data.title}
              onFatalError={setFatal}
            />
          )}
        </article>

        {(data.tags?.length ?? 0) > 0 ? (
          <div className="mt-8 flex flex-wrap gap-2">
            {data.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-amber-100/80 px-3 py-1 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
              >
                #{tag}
              </span>
            ))}
          </div>
        ) : null}

        <p className="mt-8 border-t pt-4 text-[11px] leading-5 text-muted-foreground">
          副刊轨：不计分 · 不进 R 因子 · 不走同行评审 · 不代表编辑部立场。正文里的“研究”“样本”“显著性”请默认在整活。
        </p>

        <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
          <DialogContent className="flex h-[86vh] max-w-5xl flex-col overflow-hidden p-0">
            <DialogHeader className="border-b px-4 py-3">
              <DialogTitle className="text-sm">PDF 版式预览 · 与下载件同源</DialogTitle>
            </DialogHeader>
            <div className="min-h-0 flex-1 p-2">
              {previewOpen && <PdfImagePreview resourceId={data.id} version="21" />}
            </div>
          </DialogContent>
        </Dialog>

        <section className="mt-8 border-t pt-6">
          <h2 className="mb-4 text-sm font-medium">评论区</h2>
          <Comments resourceId={data.id} />
        </section>
      </div>
    </div>
  )
}
