import {
  Children,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown, { defaultUrlTransform, type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { ListTree, ALargeSmall, Baseline } from 'lucide-react'
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
/** 阅读偏好：字号/行距/衬线，localStorage 持久化（跨篇生效）。 */
interface ReadingPrefs {
  fontScale: number
  lineHeight: number
  serif: boolean
}

const READING_PREFS_KEY = 'rubbish.reading-prefs'

function loadReadingPrefs(): ReadingPrefs {
  try {
    const raw = localStorage.getItem(READING_PREFS_KEY)
    if (raw) {
      const p = JSON.parse(raw) as Partial<ReadingPrefs>
      return {
        fontScale: Math.min(1.5, Math.max(0.85, p.fontScale ?? 1)),
        lineHeight: Math.min(2.4, Math.max(1.5, p.lineHeight ?? 1.95)),
        serif: p.serif ?? true,
      }
    }
  } catch {
    /* 忽略损坏数据 */
  }
  return { fontScale: 1, lineHeight: 1.95, serif: true }
}

function useReadingPrefs() {
  const [prefs, setPrefs] = useState<ReadingPrefs>(loadReadingPrefs)
  const update = (patch: Partial<ReadingPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      try {
        localStorage.setItem(READING_PREFS_KEY, JSON.stringify(next))
      } catch {
        /* 私密模式忽略 */
      }
      return next
    })
  }
  return { prefs, update }
}

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
  if (idx < 0) {
    if (md.startsWith('## 参考文献')) return { main: '', refs: md }
    return { main: md, refs: '' }
  }
  return { main: md.slice(0, idx), refs: md.slice(idx + 1) }
}

// Word → HTML → Markdown 的转换管线会在插图位置留下
// `<!-- Start of picture text --> … <!-- End of picture text -->` 这类
// 注释，Markdown 渲染时被当成正文显示（生产 /reader/133 实锤）。
// 只在渲染层剥离，不改存储原文。
const HTML_COMMENT = /<!--[\s\S]*?-->/g

export function stripHtmlComments(md: string): string {
  return md.replace(HTML_COMMENT, '')
}

interface AbstractSplit {
  before: string
  abstract: string
  label: string
  after: string
}

const ABSTRACT_HEADING =
  /^#{2,3}[ \t]*(摘[ \t\u3000]*要|Abstract|ABSTRACT)(?:[ \t]*[（(][^）)]*[）)])?[ \t]*$/i
const ABSTRACT_QUOTE =
  /^>[ \t]*(?:\*\*)?[ \t]*(摘[ \t\u3000]*要|Abstract|ABSTRACT)[ \t]*(?:\*\*)?[ \t\u3000:：]*(.*)$/i
const NEXT_HEADING = /^#{1,3}[ \t]+\S/
const KEYWORDS_LINE = /^(?:\*\*)?[ \t]*(关键词|关键字|Keywords?)(?:\*\*)?[ \t]*[:：]/i

function abstractLabel(heading: string): string {
  return /^abstract$/i.test(heading.trim()) ? 'Abstract' : '摘要'
}

// 摘要从正文流中摘出，交给独立卡片渲染；关键词/下一节/分隔线都视为摘要结束。
// 兼容两种真实稿件结构：清洗后的 `## 摘要` 与存量稿的 `> **摘 要** …`。
export function splitAbstract(md: string): AbstractSplit {
  const lines = md.split('\n')
  const headingAt = lines.findIndex((line) => ABSTRACT_HEADING.test(line.trim()))
  if (headingAt >= 0) {
    const heading = ABSTRACT_HEADING.exec(lines[headingAt].trim())?.[1] ?? '摘要'
    let end = lines.length
    for (let i = headingAt + 1; i < lines.length; i++) {
      const line = lines[i].trim()
      if (NEXT_HEADING.test(line) || KEYWORDS_LINE.test(line) || line === '---') {
        end = i
        break
      }
    }
    const abstract = lines.slice(headingAt + 1, end).join('\n').trim()
    if (abstract) {
      return {
        before: lines.slice(0, headingAt).join('\n').trim(),
        abstract,
        label: abstractLabel(heading),
        after: lines.slice(end).join('\n').trim(),
      }
    }
  }

  const quoteAt = lines.findIndex((line) => ABSTRACT_QUOTE.test(line.trim()))
  if (quoteAt >= 0) {
    const heading = ABSTRACT_QUOTE.exec(lines[quoteAt].trim())?.[1] ?? '摘要'
    const body = [ABSTRACT_QUOTE.exec(lines[quoteAt].trim())?.[2] ?? '']
    let end = quoteAt + 1
    while (end < lines.length && /^>/.test(lines[end].trim())) {
      const quoted = lines[end].trim().replace(/^>[ \t]?/, '')
      if (KEYWORDS_LINE.test(quoted) || NEXT_HEADING.test(quoted)) break
      body.push(quoted)
      end++
    }
    const abstract = body.join('\n').trim()
    if (abstract) {
      return {
        before: lines.slice(0, quoteAt).join('\n').trim(),
        abstract,
        label: abstractLabel(heading),
        after: lines.slice(end).join('\n').trim(),
      }
    }
  }

  return { before: '', abstract: '', label: '摘要', after: md }
}

function nodeText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join('')
  if (isValidElement<{ children?: ReactNode }>(node)) return nodeText(node.props.children)
  return ''
}

const CAPTION_TEXT = /^(?:图|表|Figure|Fig\.?|Table)[ \t\u3000]*\d+/i
const KEYWORDS_TEXT = /^(?:关键词|关键字|Keywords?)[ \t]*[:：]/i

// 图注/表注：整段为一行、且源稿用斜体或粗体标记（`*图 1 …*` / `**表 1 …**`）。
function paragraphClass(children: ReactNode): string | undefined {
  const text = nodeText(children).trim()
  if (KEYWORDS_TEXT.test(text)) return 'md-keywords'
  if (!CAPTION_TEXT.test(text)) return undefined
  const items = Children.toArray(children)
  const only = items.length === 1 ? items[0] : null
  const emphasized = isValidElement(only) && (only.type === 'em' || only.type === 'strong')
  // 无强调标记时只认「图 1 / 表 1：」这种带全角分隔的独立短行，
  // 避免把「图 1 显示…」这类正文句子误判成图注。
  const labelled = /^(?:图|表)[ \t\u3000]*\d+[\u3000.、:：]/.test(text) && text.length <= 90
  if (!emphasized && !labelled) return undefined
  return /^(?:表|Table)/i.test(text)
    ? 'md-caption md-caption-table'
    : 'md-caption md-caption-figure'
}

function referenceEntries(refs: string): string[] {
  const body = refs.replace(/^#{1,6}[ \t]*参考文献[^\n]*\n?/i, '').trim()
  if (!body) return []
  return body
    .split(/\n(?=[ \t]*\[\d+\])/)
    .map((entry) => entry.trim())
    .filter(Boolean)
}

// 公式/插图原图 404 时，浏览器会把 img 的 alt（整段 LaTeX 回退文本）
// 当正文渲染出来，看起来像"一堆乱码"（生产 /reader/133 实锤）。
// onError 后换成小占位元素：保留 a11y 信息，但不显示 alt 原文。
function ManuscriptImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <span
        role="img"
        aria-label={alt || '缺失的插图'}
        className="md-img-missing inline-block rounded border border-dashed border-border bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground align-middle"
      >
        插图缺失（原图未上传）
      </span>
    )
  }
  return <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />
}

const markdownComponents: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  ),
  img: ({ src, alt }) =>
    // 空/非字符串 src（例如转换失败的本地绝对路径被清洗成空串）
    // 直接不渲染：浏览器对 src="" 会重新请求整页，且控制台报错。
    typeof src === 'string' && src ? (
      <ManuscriptImage src={src} alt={alt ?? ''} />
    ) : null,
  p: ({ children }) => <p className={paragraphClass(children)}>{children}</p>,
  table: ({ children }) => (
    <div className="md-table-wrap">
      <table>{children}</table>
    </div>
  ),
}

function ManuscriptMarkdown({ children, math = true }: { children: string; math?: boolean }) {
  return (
    <ReactMarkdown
      urlTransform={(url) =>
        // 转换管线把图表内嵌为 data:image URI；默认清洗会剥掉 data: 协议
        // 导致破图。这里只放行图片 data URI，其余仍走默认清洗。
        url.startsWith('data:image/') ? url : defaultUrlTransform(url)
      }
      remarkPlugins={math ? [remarkGfm, remarkMath] : [remarkGfm]}
      rehypePlugins={math ? [[rehypeKatex, { strict: false }]] : []}
      components={markdownComponents}
    >
      {children}
    </ReactMarkdown>
  )
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
  // 阅读偏好：字号/行距/衬线。toolbar 折叠收纳，不与目录按钮抢位。
  const { prefs, update: updatePrefs } = useReadingPrefs()
  // 手机端阅读设置默认收起，避免常驻工具条压住正文开头
  const [prefsOpen, setPrefsOpen] = useState(false)

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

  // 渲染前剥离 Word 转换残留的 HTML 注释（只在渲染层，不改存储原文）。
  const cleaned = data ? stripHtmlComments(data) : data

  // 目录与正文/参考文献拆分：纯字符串操作，无需 memo
  const split = cleaned ? splitManuscript(cleaned) : { main: '', refs: '' }
  const sections = split.main
    ? splitAbstract(split.main)
    : { before: '', abstract: '', label: '摘要', after: '' }
  const main = split.main
  const refs = split.refs
  const refEntries = refs ? referenceEntries(refs) : []
  const refCount = refEntries.length
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

        <div className="flex min-w-0 flex-1 flex-col">
        {/* 阅读控制条：字号 / 行距 / 衬线切换。
            桌面端常驻右上；手机端折叠成一颗小圆钮——390px 宽的屏上，
            一条常驻工具条会压住摘要开头，读者第一眼先看到一排图标而不是正文。 */}
        <div className="sticky top-2 z-10 -mb-2 flex justify-end">
          <button
            type="button"
            aria-label="阅读设置"
            aria-expanded={prefsOpen}
            onClick={() => setPrefsOpen((v) => !v)}
            className="mr-1 grid h-8 w-8 place-items-center rounded-full border bg-background/90 text-xs shadow-sm backdrop-blur lg:hidden"
          >
            Aa
          </button>
          <div
            className={`${prefsOpen ? 'flex' : 'hidden'} items-center gap-1 rounded-full border bg-background/95 px-2 py-1 shadow-sm backdrop-blur lg:flex`}
          >
            <button
              aria-label="减小字号"
              className="grid h-7 w-7 place-items-center rounded-full text-xs hover:bg-muted"
              onClick={() => updatePrefs({ fontScale: Math.max(0.85, prefs.fontScale - 0.08) })}
            >
              <ALargeSmall className="h-4 w-4" />
            </button>
            <button
              aria-label="增大字号"
              className="grid h-7 w-7 place-items-center rounded-full text-base hover:bg-muted"
              onClick={() => updatePrefs({ fontScale: Math.min(1.5, prefs.fontScale + 0.08) })}
            >
              <ALargeSmall className="h-5 w-5" />
            </button>
            <span className="mx-0.5 h-4 w-px bg-border" aria-hidden="true" />
            <button
              aria-label="切换行距"
              className="grid h-7 w-7 place-items-center rounded-full hover:bg-muted"
              title={`行距 ${prefs.lineHeight.toFixed(2)}（点击在 1.6/1.95/2.3 间切换）`}
              onClick={() => {
                const steps = [1.6, 1.95, 2.3]
                const idx = steps.findIndex((v) => Math.abs(v - prefs.lineHeight) < 0.01)
                updatePrefs({ lineHeight: steps[(idx + 1) % steps.length] })
              }}
            >
              <Baseline className="h-4 w-4" />
            </button>
            <span className="mx-0.5 h-4 w-px bg-border" aria-hidden="true" />
            <button
              className="rounded-full px-2 py-0.5 text-xs hover:bg-muted"
              title="切换正文字体（衬线/无衬线）"
              onClick={() => updatePrefs({ serif: !prefs.serif })}
            >
              {prefs.serif ? '宋体' : '黑体'}
            </button>
          </div>
        </div>
        <article
          ref={articleRef}
          className="markdown-body min-w-0 flex-1"
          style={{
            fontSize: `${prefs.fontScale}em`,
            lineHeight: prefs.lineHeight,
            fontFamily: prefs.serif
              ? undefined
              : "ui-sans-serif, system-ui, 'Noto Sans SC', sans-serif",
          }}
        >
          {sections.abstract ? (
            <>
              {sections.before && <ManuscriptMarkdown>{sections.before}</ManuscriptMarkdown>}
              <section role="region" aria-label={sections.label} className="md-abstract">
                <ManuscriptMarkdown>
                  {`## ${sections.label}\n\n${sections.abstract}`}
                </ManuscriptMarkdown>
              </section>
              {sections.after && <ManuscriptMarkdown>{sections.after}</ManuscriptMarkdown>}
            </>
          ) : (
            <ManuscriptMarkdown>{main}</ManuscriptMarkdown>
          )}

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
                <div className="markdown-body refs-body">
                  <ManuscriptMarkdown math={false}>
                    {refEntries.join('\n\n')}
                  </ManuscriptMarkdown>
                </div>
              </div>
            </details>
          )}
        </article>
        </div>
      </div>
    </div>
  )
}
