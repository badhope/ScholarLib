import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { Loading } from '@/components/common/state'

interface AuthPngPreviewProps {
  /** 例如 /catalog/303/source-preview/<token> */
  baseUrl: string
  pages: number
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/**
 * 带鉴权的分页 PNG 预览。
 *
 * 原件只对编辑部开放，直接用 <img src> 带不上 Authorization；这里用 axios
 * 取 blob，再转 data URL（站点的 CSP 允许 data:，不允许 blob:）。每页单独
 * 请求，慢网/大文件不会卡整份解析。
 */
const AUTH_PREVIEW_CACHE_LIMIT = 20

export default function AuthPngPreview({ baseUrl, pages }: AuthPngPreviewProps) {
  // 与 SourcePreviewPng/PdfImagePreview 相同的规则：换一份原件时页码必须
  // 在同一次渲染里归 1，不能等 effect 跑完再纠正。
  const [pager, setPager] = useState({ key: baseUrl, page: 1 })
  const page = pager.key === baseUrl ? pager.page : 1
  const safePages = Math.max(0, pages)
  const setPage = (next: number | ((value: number) => number)) => {
    setPager((prev) => {
      const current = prev.key === baseUrl ? prev.page : 1
      const value = typeof next === 'function' ? next(current) : next
      return { key: baseUrl, page: value }
    })
  }
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const cache = useRef(new Map<number, string>())

  useEffect(() => {
    cache.current.clear()
    setUrl(null)
    setError(null)
    setLoading(true)
    setPager((prev) => (prev.key === baseUrl ? prev : { key: baseUrl, page: 1 }))
  }, [baseUrl])

  useEffect(() => {
    if (safePages > 0) setPage((value) => Math.min(value, safePages))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safePages])

  useEffect(() => {
    let cancelled = false
    const cached = cache.current.get(page)
    if (cached) {
      setUrl(cached)
      setLoading(false)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    api
      .get(`${baseUrl}/${page}.png`, { responseType: 'blob', timeout: 60_000 })
      .then(async (res) => {
        const dataUrl = await blobToDataUrl(res.data)
        if (cache.current.size >= AUTH_PREVIEW_CACHE_LIMIT) {
          const oldest = cache.current.keys().next().value
          if (oldest !== undefined) cache.current.delete(oldest)
        }
        cache.current.set(page, dataUrl)
        if (!cancelled) {
          setUrl(dataUrl)
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
  }, [baseUrl, page, reloadKey])

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-[40vh] flex-1 items-start justify-center overflow-auto rounded-md border bg-muted/30 p-2">
        {url && !error ? (
          <img src={url} alt={`原件第 ${page} 页`} className="max-w-full rounded-sm shadow" />
        ) : null}
        {loading && !error ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loading />
          </div>
        ) : null}
        {error ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4">
            <p className="text-center text-sm text-muted-foreground">原件预览加载失败：{error}</p>
            <button
              type="button"
              className="text-sm text-primary underline"
              onClick={() => {
                cache.current.delete(page)
                setUrl(null)
                setReloadKey((value) => value + 1)
              }}
            >
              重试
            </button>
          </div>
        ) : null}
      </div>
      {safePages > 0 && !error ? (
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
      ) : null}
    </div>
  )
}
