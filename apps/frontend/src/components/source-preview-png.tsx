import { useEffect, useRef, useState } from 'react'
import { Loading } from '@/components/common/state'

interface SourcePreviewPngProps {
  token: string
  pages: number
}

/**
 * 投稿页「原件预览」：与发表版文章页同一条分页 PNG 链路。
 *
 * 不再在浏览器里用 pdf.js 解析整份原件；上传时后端已把 DOCX/PDF 转成
 * 一份 PDF 并返回 token，这里按页取 `/api/submissions/source-preview/{token}/{n}.png`。
 * 大文件、慢网只影响当前页，不会撞 pdf.js 的整份解析超时。
 */
export default function SourcePreviewPng({ token, pages }: SourcePreviewPngProps) {
  // token 变化必须在同一次渲染里把页码归 1：否则换一份更短的稿时，
  // 旧页码会先发一次 `/4.png` 请求，用户看到 404 空白后才被 effect 纠正。
  const [pager, setPager] = useState({ token, page: 1 })
  const page = pager.token === token ? pager.page : 1
  const safePages = Math.max(0, pages)
  const setPage = (next: number | ((value: number) => number)) => {
    setPager((prev) => {
      const current = prev.token === token ? prev.page : 1
      const value = typeof next === 'function' ? next(current) : next
      return { token, page: value }
    })
  }
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const imgRef = useRef<HTMLImageElement>(null)

  const imageUrl = `/api/submissions/source-preview/${token}/${page}.png${retry ? `?v=${retry}` : ''}`

  useEffect(() => {
    setPager((prev) => (prev.token === token ? prev : { token, page: 1 }))
  }, [token])

  useEffect(() => {
    if (safePages > 0) setPage((value) => Math.min(value, safePages))
    // setPage 是渲染内闭包，token 变化时已由上面的 pager 派生处理。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safePages])

  useEffect(() => {
    setLoading(true)
    setError(null)
  }, [imageUrl])

  useEffect(() => {
    const img = imgRef.current
    if (img?.complete && img.naturalWidth > 0) setLoading(false)
    const timer = setTimeout(() => setLoading(false), 2500)
    return () => clearTimeout(timer)
  }, [imageUrl])

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-[40vh] flex-1 items-start justify-center overflow-auto rounded-md border bg-muted/30 p-2">
        {!error && (
          <img
            ref={imgRef}
            src={imageUrl}
            alt={`原件第 ${page} 页`}
            className="max-w-full rounded-sm shadow"
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false)
              setError('图片加载失败')
            }}
          />
        )}
        {loading && !error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loading />
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4">
            <p className="text-center text-sm text-muted-foreground">
              原件预览加载失败：{error}
            </p>
            <button
              type="button"
              onClick={() => {
                setError(null)
                setLoading(true)
                setRetry((value) => value + 1)
              }}
              className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
            >
              重新加载本页
            </button>
            <a
              href={`/api/submissions/source-preview/${token}.pdf`}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-primary underline"
            >
              直接打开原件 PDF
            </a>
          </div>
        )}
      </div>
      {safePages > 0 && !error && (
        <div className="flex items-center justify-center gap-2 pt-2 text-sm">
          <button
            type="button"
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            disabled={page <= 1}
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            上一页
          </button>
          <span className="tabular-nums" aria-live="polite">
            {page} / {safePages} 页
          </span>
          <button
            type="button"
            onClick={() => setPage((value) => Math.min(safePages, value + 1))}
            disabled={page >= safePages}
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
