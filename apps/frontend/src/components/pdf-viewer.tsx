import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Loading } from '@/components/common/state'
import { cn } from '@/lib/utils'

// pdf.js 阅读器：替代 iframe 直接嵌 PDF 的方案。
// iframe 的缺点：无法知道总页数/当前页、进度只能按输入猜测、移动端缩放体验差。
// pdf.js 是 Mozilla 开源的 PDF 渲染库，本地解析渲染、支持按页精确同步进度。
//
// 关键实现约束：canvas 必须常驻挂载（loading/error 用覆盖层表示）。
// 曾经把 canvas 放在 loading 条件分支里 —— setLoading(false) 之后立即
// renderPage，此时 React 尚未提交 DOM，canvasRef.current === null，
// render 静默 return，页面永远停在一张 300x150 的空白默认画布上。
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

interface PdfViewerProps {
  url: string
  /** 初始页码（从服务端进度恢复时传入，1 基） */
  initialPage?: number
  /** 页码变化回调（翻页/恢复后触发，供父组件同步进度） */
  onPageChange?: (page: number) => void
  /** 文档加载完成回调（报告总页数，父组件可做"已读完"判断） */
  onLoaded?: (totalPages: number) => void
  /**
   * 是否渲染组件自带的翻页条。移动端由页面底部固定操作栏独占翻页，
   * 这里必须关掉，否则同一屏出现两组「上一页/下一页」，且下面那组
   * 会被固定操作栏盖住，用户点了没反应。
   */
  showPager?: boolean
}

export default function PdfViewer({
  url,
  initialPage = 1,
  onPageChange,
  onLoaded,
  showPager = true,
}: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // docRef 持有加载好的文档对象，卸载时销毁释放内存
  const docRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null)
  const pageNumRef = useRef(0)
 const pagePropRef = useRef(initialPage)
 const onPageChangeRef = useRef(onPageChange)
 const onLoadedRef = useRef(onLoaded)
 const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null)
 useEffect(() => {
 pagePropRef.current = initialPage
 onPageChangeRef.current = onPageChange
 onLoadedRef.current = onLoaded
 })
  const [totalPages, setTotalPages] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
 const [attempt, setAttempt] = useState(0)
  // 渲染竞态守卫：页码快速连点时丢弃过期渲染结果
  const renderTokenRef = useRef(0)

  // 渲染指定页（页码变化时调用；初始加载在 onLoad 后调一次）
  const renderPage = async (num: number, doc: pdfjsLib.PDFDocumentProxy) => {
    const canvas = canvasRef.current
    // canvas 常驻挂载后这里正常拿得到；拿不到说明组件正在卸载，直接放弃
    if (!canvas) return
    const token = ++renderTokenRef.current
 renderTaskRef.current?.cancel()
 renderTaskRef.current = null
    const target = Math.min(Math.max(1, num), doc.numPages)
    pageNumRef.current = target
    setPage(target)
    try {
      const pdfPage = await doc.getPage(target)
 if (token !== renderTokenRef.current) return
      // 按容器宽度自适应（1.5x 保证高清屏清晰），单页纵向布局。
      // pdf.js 各版本 viewBox API 有波动，用 scale=1 视口宽度求基准最稳。
      // clientWidth 在初次渲染 / 隐藏容器 / 移动端折叠时可能为 0。
      // 为 0 时退回到窗口宽度（再夹到 320–900），否则 scale 会算出 0，
      // canvas 尺寸变成 0×0，用户看到的就是"白屏 + 加载失败"。
      const containerW = canvas.parentElement?.clientWidth ?? 0
      const base = Math.min(containerW > 0 ? containerW : window.innerWidth - 48, 900)
      const viewport1 = pdfPage.getViewport({ scale: 1 })
      const scale = (base / viewport1.width) * 1.5
      const viewport = pdfPage.getViewport({ scale })
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      // 渲染失败绝不静默：surface 到 UI 与 window.__pdfErr，便于线上定位。
      // v5 渲染全在主线程 canvasContext，稳定不卡（v6 worker 侧渲染实测会静默挂起）
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const task = pdfPage.render({ canvasContext: ctx, viewport } as any)
 renderTaskRef.current = task
 await task.promise
 if (renderTaskRef.current === task) renderTaskRef.current = null
      } catch (err) {
        if (token !== renderTokenRef.current) return
 const msg = `PDF 页面渲染失败：${err instanceof Error ? err.message : String(err)}`
        ;(window as unknown as { __pdfErr?: string }).__pdfErr = msg
        console.error('[pdf-viewer]', err)
        if (token === renderTokenRef.current) setError(msg)
        return
      }
      if (token === renderTokenRef.current) {
        onPageChangeRef.current?.(target)
      }
    } catch (err) {
      // getPage / viewport 等前置步骤失败：同样 surface，不再静默。
      const msg = `PDF 页面加载失败：${err instanceof Error ? err.message : String(err)}`
      ;(window as unknown as { __pdfErr?: string }).__pdfErr = msg
      console.error('[pdf-viewer]', err)
      if (token === renderTokenRef.current) setError(msg)
    }
  }

  // 文档加载：只跑一次（url 固定）
  useEffect(() => {
 let disposed = false
 pageNumRef.current =0
 ;(async () => {
 await Promise.resolve()
 if (disposed) return
 setError(null)
 setLoading(true)
 setTotalPages(0)
 setPage(1)
 try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const task = pdfjsLib.getDocument({ url } as any)
        // 加载超时：pdf.js 在服务端挂起/网络半开时会永久 pending，
        // 用户看到无限转圈而不是错误。45 秒后主动失败并提示重试。
        const doc = await Promise.race([
          task.promise,
          new Promise<never>((_, reject) =>
            window.setTimeout(() => reject(new Error('加载超时（45 秒）')), 45000),
          ),
        ])
        if (disposed) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          void (doc as any).destroy()
          return
        }
        docRef.current = doc
        setTotalPages(doc.numPages)
        setLoading(false)
onLoadedRef.current?.(doc.numPages)
 await renderPage(pagePropRef.current, doc)
      } catch (err) {
        if (!disposed) {
          const msg = `PDF 加载失败（文件可能已损坏或格式不支持）：${err instanceof Error ? err.message : String(err)}`
          ;(window as unknown as { __pdfErr?: string }).__pdfErr = msg
          console.error('[pdf-viewer]', err)
          setError(msg)
          setLoading(false)
        }
      }
    })()
    return () => {
      disposed = true
 renderTokenRef.current++
 renderTaskRef.current?.cancel()
 renderTaskRef.current = null
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      void (docRef.current as any)?.destroy()
      docRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, attempt])

  useEffect(() => {
 const doc = docRef.current
 if (doc && initialPage !== pageNumRef.current) void renderPage(initialPage, doc)
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [initialPage])

 const goTo = (delta: number) => {
    const doc = docRef.current
    if (!doc) return
    void renderPage(pageNumRef.current + delta, doc)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative flex min-h-[40vh] flex-1 items-start justify-center overflow-auto rounded-md border bg-muted/30 p-2">
        {/* canvas 常驻挂载：loading/error 只是覆盖层，保证 renderPage 拿得到元素 */}
        <canvas
          ref={canvasRef}
          aria-label="PDF 页面预览"
          className={cn('max-w-full rounded-sm shadow', (loading || error) && 'invisible')}
        />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loading />
          </div>
        )}
        {error && (
 <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4">
 <p className="text-center text-sm text-muted-foreground">{error}</p>
 <button type="button" className="rounded-md border px-3 py-1.5 text-sm" onClick={() => setAttempt((value) => value +1)}>重试</button>
 </div>
        )}
      </div>
      {showPager && totalPages > 0 && !error && (
        <div className="flex items-center justify-center gap-2 pt-2 text-sm">
          <button
            type="button"
            onClick={() => goTo(-1)}
            disabled={page <= 1}
            aria-label="上一页"
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            上一页
          </button>
          <span className="tabular-nums">
            {page} / {totalPages} 页
          </span>
          <button
            type="button"
            onClick={() => goTo(1)}
            disabled={page >= totalPages}
            aria-label="下一页"
            className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
