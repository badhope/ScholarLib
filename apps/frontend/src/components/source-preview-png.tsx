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
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const imgRef = useRef<HTMLImageElement>(null)

  const imageUrl = `/api/submissions/source-preview/${token}/${page}.png`

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
      {pages > 0 && !error && (
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
            {page} / {pages} 页
          </span>
          <button
            type="button"
            onClick={() => setPage((value) => Math.min(pages, value + 1))}
            disabled={page >= pages}
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
