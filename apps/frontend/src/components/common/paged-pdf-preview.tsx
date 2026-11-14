import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Maximize, Minus, Plus } from 'lucide-react'
import { Loading } from '@/components/common/state'

export interface PagedPdfPreviewProps {
  /** 资源/版本的稳定标识；变化时页码、缩放、错误状态一起归零。 */
  viewKey: string
  /** 总页数；0 表示还在读取页数。 */
  pages: number
  /**
   * 取某一页的图片地址。可以是同步 URL，也可以是带鉴权的异步 blob URL。
   * retry 从 0 开始，用户点重试时递增；异步实现应跳过缓存。
   */
  loadPage: (page: number, retry: number) => string | Promise<string>
  altPrefix: string
  /** 预览容器可访问名称；默认由 altPrefix 派生。 */
  ariaLabel?: string
  /** 有值时显示“打开/下载 PDF”。 */
  downloadUrl?: string
  downloadLabel?: string
  retryLabel?: string
  errorPrefix?: string
  emptyLabel?: string
  className?: string
}

/**
 * 分页 PDF/图片预览的通用壳。
 *
 * 两个业务预览器（公开 PDF、投稿原件鉴权 PNG）只在“怎么取一页”上不同，
 * 分页状态机、换稿归位、越界夹取、重试、页码跳转、缩放和键盘翻页都在
 * 这里维护一份，避免两边各改一半后行为漂移。
 */
export default function PagedPdfPreview({
  viewKey,
  pages,
  loadPage,
  altPrefix,
  ariaLabel,
  downloadUrl,
  downloadLabel = '直接打开 / 下载 PDF',
  retryLabel = '重新加载本页',
  errorPrefix = '预览加载失败',
  emptyLabel = '正在读取页数…',
  className = '',
}: PagedPdfPreviewProps) {
  const safePages = Math.max(0, Math.floor(pages))

  // 换资源时页码必须在同一次渲染里归 1：否则会先请求新资源的第 91 页。
  const [pager, setPager] = useState({ key: viewKey, page: 1 })
  const page = pager.key === viewKey ? pager.page : 1
  const setPage = (next: number | ((value: number) => number)) => {
    setPager((prev) => {
      const current = prev.key === viewKey ? prev.page : 1
      const value = typeof next === 'function' ? next(current) : next
      return { key: viewKey, page: value }
    })
  }

  const [source, setSource] = useState<{
    key: string
    page: number
    url: string
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [jump, setJump] = useState('')
  const imgRef = useRef<HTMLImageElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const loadPageRef = useRef(loadPage)

  // 更新 ref 只能在 effect 里做；直接在 render 期间赋值会触发 React Compiler 的 refs 规则。
  useEffect(() => {
    loadPageRef.current = loadPage
  }, [loadPage])

  // 保留上一页图片直到新页返回：翻页时不要先闪一块空白，alt 仍指向新页。
  const currentUrl = source?.key === viewKey ? source.url : null

  // 换稿：页码、缩放、重试和旧图一起失效，避免旧稿的页面短暂串台。
  useEffect(() => {
    setPager((prev) =>
      prev.key === viewKey ? prev : { key: viewKey, page: 1 },
    )
    setSource(null)
    setError(null)
    setLoading(true)
    setRetry(0)
    setZoom(1)
    setJump('')
  }, [viewKey])

  useEffect(() => {
    if (safePages > 0) setPage((value) => Math.min(value, safePages))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safePages])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.resolve(loadPageRef.current(page, retry))
      .then((url) => {
        if (!cancelled) {
          setSource({ key: viewKey, page, url })
          setLoading(false)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoading(false)
          setError('图片加载失败')
        }
      })
    return () => {
      cancelled = true
    }
  }, [page, retry, viewKey])

  // 命中浏览器缓存时部分浏览器不触发 onLoad，给一个兜底时限；
  // 真失败仍由 onError 接管，不会把错误页伪装成加载中。
  useEffect(() => {
    const img = imgRef.current
    if (img?.complete && img.naturalWidth > 0) setLoading(false)
    const timer = setTimeout(() => setLoading(false), 2500)
    return () => clearTimeout(timer)
  }, [currentUrl])

  const goToPage = (next: number) => {
    if (safePages <= 0) return
    setPage(Math.max(1, Math.min(safePages, next)))
  }

  const retryPage = () => {
    setError(null)
    setLoading(true)
    setSource(null)
    setRetry((value) => value + 1)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      goToPage(page - 1)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      goToPage(page + 1)
    }
  }

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      aria-label={ariaLabel ?? `${altPrefix}预览`}
      className={`flex h-full flex-col outline-none focus-visible:ring-2 focus-visible:ring-ring ${className}`}
    >
      <div className="relative flex min-h-[40vh] flex-1 items-start justify-center overflow-auto rounded-md border bg-muted/30 p-2">
        {currentUrl && !error ? (
          <img
            ref={imgRef}
            src={currentUrl}
            alt={`${altPrefix} ${page} 页`}
            className="rounded-sm shadow"
            style={{
              width: `${Math.round(zoom * 100)}%`,
              maxWidth: zoom <= 1 ? '100%' : 'none',
            }}
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false)
              setError('图片加载失败')
            }}
          />
        ) : null}
        {loading && !error ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loading />
          </div>
        ) : null}
        {error ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4">
            <p className="text-center text-sm text-muted-foreground">
              {errorPrefix}：{error}
            </p>
            <button
              type="button"
              onClick={retryPage}
              className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
            >
              {retryLabel}
            </button>
            {downloadUrl ? (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-primary underline"
              >
                {downloadLabel}
              </a>
            ) : null}
          </div>
        ) : null}
        {safePages === 0 && !error && !loading ? (
          <p className="p-4 text-center text-sm text-muted-foreground">
            {emptyLabel}
          </p>
        ) : null}
      </div>

      {safePages > 0 && !error ? (
        <div className="flex flex-wrap items-center justify-center gap-2 pt-2 text-sm">
          <button
            type="button"
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1}
            className="rounded-md border px-3 py-1.5 transition-colors hover:bg-muted disabled:opacity-50"
          >
            上一页
          </button>
          <span className="tabular-nums" aria-live="polite">
            {page} / {safePages} 页
          </span>
          <button
            type="button"
            onClick={() => goToPage(page + 1)}
            disabled={page >= safePages}
            className="rounded-md border px-3 py-1.5 transition-colors hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>

          <form
            className="flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault()
              const next = Number.parseInt(jump, 10)
              if (Number.isFinite(next)) goToPage(next)
              setJump('')
            }}
          >
            <input
              aria-label="跳转页码"
              type="number"
              min={1}
              max={safePages}
              value={jump}
              onChange={(event) => setJump(event.target.value)}
              placeholder="页码"
              className="w-16 rounded-md border bg-background px-2 py-1 text-center text-sm tabular-nums"
            />
            <button
              type="submit"
              className="rounded-md border px-2 py-1 text-xs hover:bg-muted"
            >
              跳转
            </button>
          </form>

          <div className="flex items-center gap-1" aria-label="缩放控制">
            <button
              type="button"
              aria-label="缩小"
              onClick={() =>
                setZoom((value) =>
                  Math.max(0.5, Math.round((value - 0.1) * 10) / 10),
                )
              }
              className="rounded-md border p-1 hover:bg-muted"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <span className="w-12 text-center text-xs tabular-nums">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              aria-label="放大"
              onClick={() =>
                setZoom((value) =>
                  Math.min(2, Math.round((value + 0.1) * 10) / 10),
                )
              }
              className="rounded-md border p-1 hover:bg-muted"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label="适合宽度"
              onClick={() => setZoom(1)}
              className="rounded-md border p-1 hover:bg-muted"
            >
              <Maximize className="h-3.5 w-3.5" />
            </button>
          </div>
          {downloadUrl ? (
            <a
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-primary underline underline-offset-2"
            >
              {downloadLabel}
            </a>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
