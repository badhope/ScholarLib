import { useEffect, useRef, useState } from 'react'
import { Loading } from '@/components/common/state'

interface PdfImagePreviewProps {
  resourceId: number
  /** 产物版本号：模板或内容变了必须递增，避免浏览器拿旧图。 */
  version?: string
}

/**
 * PDF 版式预览（服务端渲染单页）。
 *
 * 不再在浏览器里用 pdf.js 解析整份 PDF：大文件（91 页 / 2.6 MB）
 * 在移动端要十几秒，慢网会撞上 45 秒超时，用户看到的就是“PDF 报错”。
 * 这里只请求当前页的 PNG，翻页再取下一页；版式仍来自同一份 PDF。
 */
export default function PdfImagePreview({
  resourceId,
  version = '21',
}: PdfImagePreviewProps) {
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const imgRef = useRef<HTMLImageElement>(null)

  const imageUrl = `/api/catalog/${resourceId}/export?format=png&v=${version}&page=${page}`

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    // 只取总页数（几十字节 JSON），图片仍交给 <img> 直接走浏览器缓存。
    fetch(`/api/catalog/${resourceId}/export?format=info&v=${version}`, {
      cache: 'force-cache',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) return
        const payload = (await response.json()) as { pages?: number }
        if (payload.pages && payload.pages > 0) setTotal(payload.pages)
      })
      .catch(() => {
        /* 页数失败不影响 <img> 显示，错误由 onError 兜底 */
      })
    return () => controller.abort()
  }, [imageUrl])

  // 图片命中浏览器缓存时，部分浏览器不会再触发 onLoad，加载遮罩会
  // 一直停在页面正中；渲染后检查 complete/naturalWidth 兜底关掉。
  useEffect(() => {
    const img = imgRef.current
    if (img?.complete && img.naturalWidth > 0) setLoading(false)
    // 部分浏览器/缓存组合下 onLoad 不触发，给一个兜底时限；
    // 真失败仍由 onError 接管，不会把错误页伪装成加载中。
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
            alt={`PDF 第 ${page} 页`}
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
              预览加载失败：{error}
            </p>
            <a
              href={`/api/catalog/${resourceId}/export?format=pdf&v=${version}`}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-primary underline"
            >
              直接打开 / 下载 PDF
            </a>
          </div>
        )}
      </div>
      {total > 0 && !error && (
        <div className="flex items-center justify-center gap-2 pt-2 text-sm">
          <button
            type="button"
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            disabled={page <= 1}
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            上一页
          </button>
          <span className="tabular-nums">
            {page} / {total} 页
          </span>
          <button
            type="button"
            onClick={() => setPage((value) => Math.min(total, value + 1))}
            disabled={page >= total}
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
