import { useEffect, useState } from 'react'
import PagedPdfPreview from '@/components/common/paged-pdf-preview'

interface PdfImagePreviewProps {
  resourceId: number
  /** 产物版本号：模板或内容变了必须递增，避免浏览器拿旧图。 */
  version?: string
}

/**
 * PDF 版式预览（服务端渲染单页）。
 *
 * 不在浏览器里解析整份 PDF：大文件在移动端要十几秒，慢网会撞超时。
 * 这里只请求当前页 PNG，翻页再取下一页。
 */
export default function PdfImagePreview({
  resourceId,
  version = '21',
}: PdfImagePreviewProps) {
  const viewKey = `${resourceId}:${version}`
  const [totalState, setTotalState] = useState({ key: viewKey, total: 0 })
  const total = totalState.key === viewKey ? totalState.total : 0

  useEffect(() => {
    const controller = new AbortController()
    // 只取总页数（几十字节 JSON），图片仍交给 <img> 走浏览器缓存。
    fetch(`/api/catalog/${resourceId}/export?format=info&v=${version}`, {
      cache: 'force-cache',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) return
        const payload = (await response.json()) as { pages?: number }
        if (payload.pages && payload.pages > 0) {
          setTotalState({ key: viewKey, total: payload.pages })
        }
      })
      .catch(() => {
        /* 页数失败不影响 <img> 显示，错误由 PagedPdfPreview 兜底 */
      })
    return () => controller.abort()
  }, [resourceId, version, viewKey])

  return (
    <PagedPdfPreview
      viewKey={viewKey}
      pages={total}
      altPrefix="PDF 第"
      ariaLabel="PDF 预览"
      emptyLabel="正在读取页数…"
      loadPage={(page, retry) =>
        `/api/catalog/${resourceId}/export?format=png&v=${version}&page=${page}${
          retry ? `&retry=${retry}` : ''
        }`
      }
      downloadUrl={`/api/catalog/${resourceId}/export?format=pdf&v=${version}`}
    />
  )
}
