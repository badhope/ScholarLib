import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { ListTree } from 'lucide-react'
import 'katex/dist/katex.min.css'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { EmptyState, Loading } from '@/components/common/state'

// 在线阅读的 Markdown 渲染视图（0.7.0）。
// - 数据：GET /api/catalog/{id}/manuscript（text/markdown，公开边界与
//   PDF 下载端点一致；上传时服务端从 PDF/Word 自动转换）。
// - 渲染：react-markdown（默认转义原始 HTML，XSS 面为零）+ GFM 表格
//   + KaTeX 公式；图片为 data URI 自包含（urlTransform 白名单放行）。
// - 阅读体验：桌面端目录侧栏（点击跳转）、参考文献折叠、滚动进度。
interface TocEntry {
  id: string
  level: 2 | 3
  text: string
}

interface ManuscriptViewProps {
  resourceId: number
  initialPercent: number
  onProgress: (percent: number, completed: boolean) => void
  /** true = 用 window 原生滚动采集进度（移动端富文本），false = 容器内滚 */
  useWindowScroll?: boolean
  /** 目录条目数变化时回调，供阅读页决定底部「目录」按钮是否出现 */
  onTocChange?: (count: number) => void
}

function headingHash(text: string): string {
  let h = 5381
  for (let i = 0; i < text.length; i++) {
    h = (Math.imul(h, 33) ^ text.charCodeAt(i)) >>> 0
  }
  return h.toString(36)
}

function splitManuscript(md: string): { main: string; refs: string } {
  const idx = md.lastIndexOf('\n## 参考文献')
  if (idx < 0) return { main: md, refs: '' }
  return { main: md.slice(0, idx), refs: md.slice(idx + 1) }
}

export const TOC_OPEN_EVENT = 'rubbish:open-toc'

export function ManuscriptView({
  resourceId,
  initialPercent,
  onProgress,
  useWindowScroll = false,
  onTocChange,
}: ManuscriptViewProps) {
   const scrollRef = useRef<HTMLDivElement>(null)
  const restoredRef = useRef(false)
  const [scrollHost, setScrollHost] = useState<HTMLDivElement | null>(null)
  const [refsOpen, setRefsOpen] = useState(false)
  const [tocOpen, setTocOpen] = useState(false)

  // 底部操作栏的「目录」按钮通过 window 事件唤出抽屉：目录条目是在
  // 本组件里从 Markdown 解析出来的，把状态提上去反而要重解析一遍。
  useEffect(() => {
    const onOpen = () => setTocOpen(true)
    window.addEventListener(TOC_OPEN_EVENT, onOpen)
    return () => window.removeEventListener(TOC_OPEN_EVENT, onOpen)
  }, [])

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['catalog', 'manuscript', resourceId],
    staleTime: 5 * 60_000,
    retry: 0,
    queryFn: async () => {
      const resp = await api.get<string>(`/catalog/${resourceId}/manuscript`, {
        transformResponse: (body) => body,
        headers: { Accept: 'text/markdown' },
      })
      return resp.data
    },
  })

  // 目录与正文/参考文献拆分：纯字符串操作，无需 memo
  const split = data ? splitManuscript(data) : { main: '', refs: '' }
  const main = split.main
  const refs = split.refs
  const refCount = refs ? (refs.match(/^\[\d+\]/gm)?.length ?? 0) : 0
 const [toc, setToc] = useState<TocEntry[]>([])
 const articleRef = useRef<HTMLElement>(null)
 useEffect(() => {
 if (!data || !articleRef.current) return
 const seen = new Set<string>()
 const entries: TocEntry[] = []
 articleRef.current.querySelectorAll<HTMLHeadingElement>('h2, h3').forEach((heading) => {
 if (heading.closest('#refs')) return
 const text = heading.textContent?.trim() ?? ''
 let id = `h-${headingHash(text)}`
 while (seen.has(id)) id += '-x'
 seen.add(id)
 heading.id = id
 entries.push({ id, level: heading.tagName === 'H2' ?2 :3, text })
 })
 if (refs) entries.push({ id: 'refs', level:2, text: '参考文献' })
 setToc(entries)
 }, [data, refs])

  // 目录条目数上报给阅读页：不足 3 条时底部不出现「目录」按钮，
  // 避免按下去弹出一个几乎空白的抽屉。
  useEffect(() => {
    onTocChange?.(toc.length)
  }, [toc.length, onTocChange])

  // 进入时按已保存的百分比恢复阅读位置（本地或服务端进度）。
  // 恢复是一次性副作用：走 timeout 异步执行（react-hooks 编译规则要求
  // render 后的变更一律异步），restoredRef 保证只恢复一次。
  useEffect(() => {
    if (!data || !scrollHost) return
    const timer = window.setTimeout(() => {
      if (restoredRef.current) return
      restoredRef.current = true
      if (initialPercent > 0) {
        if (useWindowScroll) {
          const max = document.documentElement.scrollHeight - window.innerHeight
          window.scrollTo(0, (initialPercent / 100) * max)
        } else {
          const max = scrollHost.scrollHeight - scrollHost.clientHeight
          scrollHost.scrollTop = (initialPercent / 100) * max
        }
      }
    }, 60)
    return () => window.clearTimeout(timer)
  }, [data, scrollHost, initialPercent, useWindowScroll])

  // 进度采集：移动端富文本走 window 原生滚动，桌面/内滚走容器滚动
  useEffect(() => {
    if (!useWindowScroll) return
    const onWinScroll = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight
      const percent = max <= 0 ? 100 : Math.min(100, Math.round((window.scrollY / max) * 100))
      onProgress(percent, percent >= 98)
    }
    window.addEventListener('scroll', onWinScroll, { passive: true })
    return () => window.removeEventListener('scroll', onWinScroll)
  })

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const max = el.scrollHeight - el.clientHeight
    const percent = max <= 0 ? 100 : Math.min(100, Math.round((el.scrollTop / max) * 100))
    onProgress(percent, percent >= 98)
  }

  const jumpTo = (id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    if (useWindowScroll) {
      const top = el.getBoundingClientRect().top + window.scrollY - 88
      window.scrollTo({ top })
    } else if (scrollRef.current) {
      scrollRef.current.scrollTop = el.offsetTop - 24
    }
    if (id === 'refs') setRefsOpen(true)
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center overflow-y-auto">
        <Loading />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex flex-1 items-center justify-center overflow-y-auto p-6">
        <EmptyState
          title="在线稿件加载失败"
          description="这篇论文没有可用的在线稿件，请切换到 PDF 视图或直接下载。"
          action={
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div
      ref={(node) => {
        scrollRef.current = node
        setScrollHost(node)
      }}
      onScroll={useWindowScroll ? undefined : handleScroll}
      className={
        'flex-1 bg-background ' +
        (useWindowScroll ? '' : 'overflow-y-auto')
      }
    >
      <div className="mx-auto flex max-w-6xl items-start px-5 py-8">
        {/* 目录：桌面端左侧吸附；移动端底部抽屉，由阅读页操作栏的
            「目录」按钮通过 TOC_OPEN_EVENT 唤出（见下方 useEffect）。 */}
        {toc.length > 2 && (
          <>
            {tocOpen && (
              <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-label="文章目录">
                <button
                  aria-label="关闭目录"
                  onClick={() => setTocOpen(false)}
                  className="absolute inset-0 bg-black/40"
                />
                <div className="absolute inset-x-0 bottom-0 max-h-[70vh] overflow-y-auto rounded-t-2xl bg-background p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      <ListTree className="h-4 w-4" />
                      文章目录
                    </p>
                    <button
                      onClick={() => setTocOpen(false)}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      关闭
                    </button>
                  </div>
                  <ul className="space-y-0.5">
                    {toc.map((t) => (
                      <li key={t.id}>
                        <button
                          onClick={() => {
                            setTocOpen(false)
                            window.setTimeout(() => jumpTo(t.id), 120)
                          }}
                          className={
                            'block w-full truncate rounded px-2 py-2 text-left text-sm hover:bg-muted hover:text-primary ' +
                            (t.level === 3 ? 'pl-6 text-muted-foreground' : 'font-medium')
                          }
                        >
                          {t.text}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </>
        )}

        {toc.length > 2 && (
          <nav
            aria-label="文章目录"
            className="sticky top-0 hidden w-52 shrink-0 lg:mr-6 lg:block"
          >
            <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground">
              <ListTree className="h-3.5 w-3.5" />
              目录
            </p>
            <ul className="mt-2 max-h-[70vh] space-y-0.5 overflow-y-auto border-l border-border pr-2 text-sm">
              {toc.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => jumpTo(t.id)}
                    className={
                      'block w-full truncate rounded px-2 py-1 text-left text-xs transition-colors hover:bg-muted hover:text-primary ' +
                      (t.level === 3 ? 'pl-5 text-muted-foreground' : 'font-medium')
                    }
                    title={t.text}
                  >
                    {t.text}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}

        <article ref={articleRef} className="markdown-body min-w-0 flex-1">
          <ReactMarkdown
            urlTransform={(url) =>
              // 转换管线把图表内嵌为 data:image URI；默认清洗会剥掉 data: 协议
              // 导致破图。这里只放行图片 data URI，其余仍走默认清洗。
              url.startsWith('data:image/') ? url : defaultUrlTransform(url)
            }
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[[rehypeKatex, { strict: false }]]}
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                  {children}
                </a>
              ),
              img: ({ src, alt }) =>
                // 空/非字符串 src（例如转换失败的本地绝对路径被清洗成空串）
                // 直接不渲染：浏览器对 src="" 会重新请求整页，且控制台报错。
                typeof src === 'string' && src ? (
                  <img src={src} alt={alt ?? ''} loading="lazy" />
                ) : null,
              }}
          >
            {main}
          </ReactMarkdown>

          {refs && (
            <details
              id="refs"
              className="refs-collapse mt-10 rounded-lg border bg-muted/30"
              open={refsOpen || undefined}
            >
              <summary
                className="cursor-pointer select-none px-4 py-3 text-sm font-medium"
                onClick={(e) => {
                  e.preventDefault()
                  setRefsOpen((v) => !v)
                }}
              >
                参考文献（{refCount} 条）· 点击展开
              </summary>
              <div className="border-t px-4 py-3">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{refs}</ReactMarkdown>
              </div>
            </details>
          )}
        </article>
      </div>
    </div>
  )
}
