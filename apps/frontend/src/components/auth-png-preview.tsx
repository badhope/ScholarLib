import { useCallback, useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import PagedPdfPreview from '@/components/common/paged-pdf-preview'

interface AuthPngPreviewProps {
  /** 例如 /submissions/source-preview/<token> */
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

const AUTH_PREVIEW_CACHE_LIMIT = 20

/**
 * 带鉴权的分页 PNG 预览。
 *
 * 原件只对编辑部开放，直接用 <img src> 带不上 Authorization；这里用 axios
 * 取 blob，再转 data URL（站点 CSP 允许 data:，不允许 blob:）。
 */
export default function AuthPngPreview({
  baseUrl,
  pages,
}: AuthPngPreviewProps) {
  const cache = useRef(new Map<number, string>())

  useEffect(() => {
    cache.current.clear()
  }, [baseUrl])

  const loadPage = useCallback(
    async (page: number, retry: number) => {
      if (retry === 0) {
        const cached = cache.current.get(page)
        if (cached) return cached
      }
      const res = await api.get(`${baseUrl}/${page}.png`, {
        responseType: 'blob',
        timeout: 60_000,
      })
      const dataUrl = await blobToDataUrl(res.data)
      if (cache.current.size >= AUTH_PREVIEW_CACHE_LIMIT) {
        const oldest = cache.current.keys().next().value
        if (oldest !== undefined) cache.current.delete(oldest)
      }
      cache.current.set(page, dataUrl)
      return dataUrl
    },
    [baseUrl],
  )

  return (
    <PagedPdfPreview
      viewKey={baseUrl}
      pages={pages}
      altPrefix="原件第"
      ariaLabel="原件预览"
      errorPrefix="原件预览加载失败"
      retryLabel="重试"
      emptyLabel="原件页数读取中…"
      loadPage={loadPage}
    />
  )
}
