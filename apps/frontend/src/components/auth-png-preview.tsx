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
export default function AuthPngPreview({ baseUrl, pages }: AuthPngPreviewProps) {
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const cache = useRef(new Map<number, string>())

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
      {pages > 0 && !error ? (
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
      ) : null}
    </div>
  )
}
