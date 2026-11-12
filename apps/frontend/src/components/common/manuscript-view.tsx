import {
  Children,
  Fragment,
  cloneElement,
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

export interface TocEntry {
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
  /** 目录条目就绪时回调，供父级把 TOC 渲染到自己的侧栏 */
  onTocReady?: (toc: TocEntry[]) => void
  /** 隐藏组件内置的左侧 TOC 导航（父级自己渲染侧栏时用） */
  hideTocNav?: boolean
  /** 稿件加载失败（含 409 needs_docx）时回调，父级可据此渲染兜底 UI */
  onFatalError?: (err: unknown) => void
  /** 内容分类（来自资源元数据），组件内部据此计算 effectiveKind */
  contentCategory?: string | null
  /** 内容赛道（essay/paper），作为 contentCategory 的兜底 */
  contentTrack?: string | null
  /** 页面已展示的标题；用于剥掉正文首行重复标题 */
  title?: string
  /** 页面已展示的摘要/导读；用于剥掉副刊正文开头重复的同一段 */
  abstract?: string | null
}

// --- 轨道裁剪：在 Markdown 渲染前按 v3 规范剥掉学术小节 -------------------

function headingMatches(title: string, patterns: RegExp[]): boolean {
  const t = title.trim().replace(/[：:：\s]+$/, '')
  return patterns.some((re) => re.test(t))
}

const ABSTRACT_RE = /^(摘[ \t\u3000]*要|Abstract|ABSTRACT)$/i
const KEYWORDS_RE = /^(关键词|关键字|Keywords?)$/i
const CLC_RE = /^(中图分类号|CLC)$/i
const REFS_RE = /^(参考文献|References?|Bibliography)$/i
const DECLS_RE =
  /^(作者贡献|作者声明|作者信息|作者简介|贡献声明|声明|利益冲突|基金项目?|资助|数据可用性|伦理声明|AI[ \t\u3000]*使用声明?|致谢|Acknowledg(e)?ments?)$/i
const DOI_RE = /^(DOI|doi)$/i
const SCORE_RE = /^(评分|质量等级|RQS)$/i

// 所有需要剥掉的学术小节标题（用于行内标题规范化）
const ALL_BLOCK_TITLES =
  '摘[ \\t\\u3000]*要|Abstract|ABSTRACT|关键词|关键字|Keywords?|中图分类号|CLC|参考文献|References?|Bibliography|作者贡献|作者声明|贡献声明|利益冲突|基金项目?|资助|数据可用性|伦理声明|AI[ \\t\\u3000]*使用声明?|致谢|Acknowledg(e)?ments?|DOI|doi|评分|质量等级|RQS'

/**
 * 规范化：逐行处理。只对"本行内出现 #+ 块标题但不在行首"的行，
 * 把该片段拆成独立行；其余行一个字都不改。
 * 关键：用负向后顾 (?<!#) 避免把 `## 关键词` 的第一个 # 当成"行内文本"吃掉。
 */
function normalizeInlineHeadings(md: string): string {
  const lines = md.split('\n')
  const out: string[] = []
  // 行内块标题：# 后跟块标题词，且前面不是 #（避免拆 ## ）
  const inlineRe = new RegExp(`(?<![#\\n])#{1,6}[ \\t]+(?:${ALL_BLOCK_TITLES})[ \\t]*[:：]?`, 'g')
  for (const line of lines) {
    // 已经是行首标题的行不动
    if (/^#{1,6}\s+/.test(line)) {
      out.push(line)
      continue
    }
    // 行内出现块标题 → 用 matchAll 定位并拆行
    const matches = [...line.matchAll(inlineRe)]
    if (matches.length === 0) {
      out.push(line)
      continue
    }
    let cursor = 0
    for (const m of matches) {
      const start = m.index ?? 0
      const before = line.slice(cursor, start)
      if (before.trim()) out.push(before)
      out.push('')
      out.push(m[0])
      out.push('')
      cursor = start + m[0].length
    }
    const after = line.slice(cursor)
    if (after.trim()) out.push(after)
  }
  return out.join('\n')
}

/**
 * 剥掉文首学术刊头块：从开头到第一个正文小节之前，整块丢弃。
 * 待剥范围：H1 标题（与页头标题重复）、期刊 Logo 图、Open Access/Received/Accepted 行、
 * 作者单位/邮箱/通讯作者标记。只对 fun/rant 生效。
 * 判据：剥完后 article 内不再出现第二个 H1 标题、Logo、刊头英文。
 */
function dropAcademicHeader(md: string): string {
  const lines = md.split('\n')
  // 找第一个正文 H2/H3（1 引言 / 2.1 方法 / Introduction 等）
  let firstBodyIdx = -1
  for (let i = 0; i < lines.length; i++) {
    const m = /^(#{2,3})\s+(.*)$/.exec(lines[i])
    if (m) {
      const title = m[2].trim()
      if (/^(\d+(\.\d+)*\s*|引言|Introduction|方法|Method|结果|Result|讨论|Discussion|结论|Conclusion)/.test(title) &&
          !headingMatches(title, [ABSTRACT_RE, KEYWORDS_RE, CLC_RE, REFS_RE, DECLS_RE, DOI_RE])) {
        firstBodyIdx = i
        break
      }
    }
  }
  if (firstBodyIdx <= 0) return md
  const headerBlock = lines.slice(0, firstBodyIdx).join('\n')
  // 刊头特征：Open Access / Received / Accepted / Logo 图 / 学院/大学/邮箱 / H1
  if (/(Open Access|Received|Accepted|Copyright|©|!\[.*\]\(|@|School|University|Department|学院|大学|单位|通讯作者|Corresponding|Rubbish\s+Journal|ISSN|作者[:：])/i.test(headerBlock)) {
    return lines.slice(firstBodyIdx).join('\n')
  }
  return md
}

/**
 * 按轨道裁剪 Markdown：删除指定的 ## / ### 小节。
 * fun/rant：删 摘要/关键词/CLC/参考文献/声明/DOI；保留正文与「参考资料」
 * sci_pop：删 摘要/关键词/CLC/评分/DOI；保留正文与「延伸阅读」
 * 安全护栏：删完后若剩余 < 原文 60% 或找不到正文标题，回退为不裁剪。
 */
// 论文轨：页面已经展示标题/作者/摘要，正文若从原稿复制了同一段题录与摘要，
// 会形成“标题重复 + 作者裸行 + 摘要重复”的三连。这里只删重复部分：
// 文首标题块、作者信息起至正文前的摘要块；文首的声明/伦理说明保留。
export function stripPaperFrontMatter(md: string): string {
  const lines = md.replace(/\r/g, '').split('\n')
  const isBodyStart = (line: string) => {
    const t = line.trim()
    if (!/^#{1,3}\s+/.test(t)) return false
    if (/^#{2,3}\s+\d+\.\d+/.test(t)) return false
    return (
      /^#{1,3}\s+(?:1(?:[.、]\s*|\s+)|[一二三四五六七八九十]+[、.]\s*)?(引言|绪论|Introduction)\b/i.test(t) ||
      /^#{1,2}\s+1(?:\s|[.、])/.test(t)
    )
  }
  const bodyAt = lines.findIndex(isBodyStart)
  if (bodyAt <= 0 || bodyAt > 120) return md.trim()

  let front = lines.slice(0, bodyAt)
  // 摘要/作者块从出现处一直删到正文；保留它之前的声明与说明。
  const cutAt = front.findIndex((line) =>
    /^\s*(?:\*\*)?(作者|Author)\s*[:：]/i.test(line) ||
    /^\s*(?:\*\*)?(中文摘要|摘\s*要|Abstract)\b/i.test(line),
  )
  if (cutAt >= 0) front = front.slice(0, cutAt)
  // 有些存量稿不写「作者：」而直接写「某某（独立研究者） 通讯作者：」，
  // 页头已经展示作者，这一行在正文里只会留下一个空标签。
  front = front.filter((line) => !/(独立研究者|通讯作者|Corresponding\s+author|E-?mail|邮箱\s*[:：]|@)/i.test(line))
  while (front.length && !front[0].trim()) front.shift()

  // 文首标题块：只处理加粗标题块。`#` 标题可能是正文的 0.1 小节，
  // 若一律当重复标题删除，网页会丢掉 Word/PDF 里存在的第一个小节
  // （299/295 实锤：正文从 0.1 开始，网页却直接从「本 PADA 体系…」开始）。
  // 与页头同名的 `#` 标题已由 stripLeadingDuplicateTitle 精确删除。
  const first = front[0]?.trim() ?? ''
  if (first && first.startsWith('**')) {
    let end = 0
    while (end < front.length && front[end].trim() !== '') end++
    front = front.slice(end)
  }

  return [...front, '', ...lines.slice(bodyAt)].join('\n').trim()
}

function stripLeadingDuplicateTitle(md: string, title?: string | null): string {
  if (!title) return md
  const norm = (x: string) =>
    x.replace(/^#{1,6}\s+/, '').replace(/[*_`]/g, '').replace(/[：:，,。.、\s]/g, '').toLowerCase()
  const target = norm(title)
  if (target.length < 8) return md
  const lines = md.replace(/\r/g, '').split('\n')
  let i = 0
  while (i < lines.length && !lines[i].trim()) i++
  const m = /^(#{1,3})\s+(.+)$/.exec(lines[i]?.trim() ?? '')
  if (!m) return md
  const h = norm(m[2])
  if (!(h === target || (h.length >= 8 && (target.startsWith(h) || h.startsWith(target)))) ) return md
  lines.splice(i, 1)
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

function stripLeadingDuplicateAbstract(md: string, abstract?: string | null): string {
  if (!abstract) return md
  const norm = (s: string) =>
    s
      .replace(/[“”"']/g, '')
      .replace(/[ \t\u3000]+/g, '')
      .replace(/\n+/g, '')
      .trim()
  const target = norm(abstract)
  if (target.length < 40) return md
  const lines = md.split('\n')
  const heading = lines.findIndex((line) => /^##\s+/.test(line))
  if (heading < 0) return md
  let start = heading + 1
  while (start < lines.length && !lines[start].trim()) start++
  let end = start
  while (end < lines.length && lines[end].trim() && !/^#{1,6}\s/.test(lines[end])) end++
  const paragraph = norm(lines.slice(start, end).join('\n'))
  if (paragraph.length < 40) return md
  // api.abstract 有时会把「1 引言」和正文一起塞进来，
  // 因此用「正文首段是否出现在摘要全文里」判断，而不是只比开头。
  if (!target.includes(paragraph.slice(0, Math.min(80, paragraph.length)))) return md
  lines.splice(start, end - start)
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

// 副刊原稿常见「摘要/导读」和「引言」各写一遍同一段：保留第一次出现，
// 删掉后面的完整重复段。只处理长度 >= 40 的独立段落，避免删掉短句、
// 图注或作者刻意做的复沓。
function dedupeRepeatedParagraphs(md: string): string {
  const norm = (s: string) =>
    s
      .replace(/[“”"']/g, '')
      .replace(/[ \t\u3000]+/g, '')
      .replace(/\n+/g, '')
      .toLowerCase()
  const seen = new Set<string>()
  const earlier: string[] = []
  const blocks = md.split(/\n{2,}/)
  const kept = blocks.filter((block) => {
    const n = norm(block)
    if (n.length < 40) return true
    if (seen.has(n)) return false
    // 摘要版通常是完整长段，引言版是它的缩短复述：后者开头相同、
    // 长度更短，按前缀认作重复段删掉，避免只做全等匹配漏掉。
    const probe = n.slice(0, Math.min(80, n.length))
    if (
      earlier.some(
        (prev) => prev.length > n.length && prev.startsWith(probe),
      )
    ) {
      return false
    }
    seen.add(n)
    earlier.push(n)
    return true
  })
  return kept.join('\n\n')
}

// 同一段里逐句复述也很常见（摘要写一遍、引言再写一遍），按句子去重；
// 只处理 >= 20 字的完整句，短句、标题和列表标记原样保留。
function dedupeRepeatedSentences(md: string): string {
  const norm = (s: string) =>
    s
      .replace(/[“”"']/g, '')
      .replace(/[ \t\u3000]+/g, '')
      .replace(/\n+/g, '')
      .toLowerCase()
  const seen = new Set<string>()
  return md
    .split('\n')
    .map((line) => {
      if (/^#{1,6}\s/.test(line.trim())) return line
      const parts = line.split(/(?<=[。！？!?])/)
      return parts
        .filter((sentence) => {
          const n = norm(sentence)
          if (n.length < 20) return true
          if (seen.has(n)) return false
          seen.add(n)
          return true
        })
        .join('')
    })
    .join('\n')
}

function stripFunFrontMatter(md: string): string {
  const cutBlock = (lines: string[], re: RegExp) => {
    const start = lines.findIndex((line) => re.test(line.trim()))
    if (start < 0) return lines
    let end = start + 1
    while (end < lines.length && !/^#{2,6}\s/.test(lines[end])) end++
    return [...lines.slice(0, start), ...lines.slice(end)]
  }
  let lines = md.split('\n')
  lines = cutBlock(lines, /^##[ \t]*(?:摘[ \t\u3000]*要|Abstract)$/i)
  lines = cutBlock(lines, /^##[ \t]*(?:关键词|关键字|Keywords?)$/i)
  const out = lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
  // 极端稿子可能只有摘要没有正文；宁可保留原稿，也不要把页面清空。
  return out.length >= 500 ? out : md
}

export function stripAcademicSections(md: string, kind: string, title?: string | null): string {
  md = stripLeadingDuplicateTitle(md, title)
  if (kind === 'paper') return stripPaperFrontMatter(md)
  if (kind === 'plain') return md

  // 先统一换行：去掉 \r（Windows 换行残留会导致 $ 锚点不匹配）
  md = md.replace(/\r/g, '')
  // 娱乐页的页头已经展示标题和作者；正文第一行常是原稿自带的
  // H1 标题与 ``**作者：** 某某``，不剥掉就会在页头下重复一遍。
  md = md.replace(/^\s*#\s+.*(?:\n+|$)/u, '')
  md = md.replace(/^\s*\*\*作者[:：]\*\*.*\n+/u, '')
  md = md.replace(/^\s*作者[:：].*\n+/u, '')
  // 副刊页头已经展示作者与单位；正文开头若还带 `姓名¹ / ¹ 单位`
  // 这类上标作者块，整块去掉，避免同一个人在同一屏出现两次。
  if (kind === 'fun' || kind === 'rant') {
    md = md.replace(
      /^\s*[^\n]{1,40}[¹²³⁴⁵⁶⁷⁸⁹]\s*\n+\s*[¹²³⁴⁵⁶⁷⁸⁹][^\n]*\n+/u,
      '',
    )
  }

  // 1) 先把行内标题规范化成行首（逐行处理，不动行首标题）
  let work = normalizeInlineHeadings(md)

  // 2) fun/rant 额外剥掉文首学术刊头（找不到正文标题时放弃，保持原文）
  if (kind === 'fun' || kind === 'rant') {
    work = stripFunFrontMatter(work)
    work = dropAcademicHeader(work)
  }

  const dropPatterns: RegExp[] = [ABSTRACT_RE, KEYWORDS_RE, CLC_RE, DOI_RE]
  if (kind === 'fun' || kind === 'rant') dropPatterns.push(REFS_RE, DECLS_RE)
  else if (kind === 'sci_pop') dropPatterns.push(SCORE_RE)

  const lines = work.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const m = /^(#{1,6})\s+(.*)$/.exec(line)
    if (m) {
      const level = m[1].length
      if (level > 1 && headingMatches(m[2], dropPatterns)) {
        i++
        while (i < lines.length) {
          const next = /^(#{1,6})\s+(.*)$/.exec(lines[i])
          if (next) {
            const nextLevel = next[1].length
            const nextTitle = next[2].trim()
            // 同级或更高级标题一定结束本节；标题层级不规范的稿子里，
            // 「## 摘要」后面直接跟「### 引言」，也必须在这里收住，
            // 否则会把整篇正文当成摘要一起删掉。
            if (nextLevel <= level) break
            if (/^(\d+(\.\d+)*\s*|引言|Introduction|方法|Method|结果|Result|讨论|Discussion|结论|Conclusion)/.test(nextTitle)) break
          }
          i++
        }
        continue
      }
    }
    out.push(line)
    i++
  }
  let result = out.join('\n')

  // 安全护栏：宁可多显示也不能删正文。
  // 娱乐稿的小节层级经常是「## 摘要 / ### 引言」这种不规范结构，
  // 删完摘要和参考文献后正文可能只剩 40%~50%，不能再用论文轨的 60% 阈值，
  // 否则会把整篇带摘要、参考文献的原始稿重新显示出来。
  // 只用「剩余内容是否还有实际正文」兜底：少于 500 字认为裁剪异常。
  const isFun = kind === 'fun' || kind === 'rant'
  if (isFun) {
    // 娱乐稿不挂参考文献，正文里的 [1]/[2,3] 只会变成无主的悬空编号。
    // 这是渲染层的全局兜底；源文件仍保留编号，便于回溯原稿。
    result = result
      .replace(/[ \t]*\[\d+(?:\s*[-,，]\s*\d+)*\][ \t]*/g, ' ')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/ \n/g, '\n')
      .replace(/[ \t]+([，。、；：！？）])/g, '$1')
      // 有些娱乐稿拿高考/考试题当引子，正文里会整段复制“阅读下面的
      // 材料……写一篇文章”。题面属于引用，不是作者正文；保留会让读者
      // 以为点进了题库。只删明确带“以上材料…写一篇文章”的题面段。
      .replace(
        /（\d{4}\s*年[^）]{0,60}）\s*[\s\S]{0,1200}?以上材料[^\n]{0,240}\n+/g,
        '',
      )
    if (result.trim().length < 500) {
      console.warn('[stripAcademicSections] fun result too short, falling back', {
        original: md.length,
        result: result.length,
      })
      return md
    }
    return result
  }

  // 论文 / 科普轨保留原有双护栏
  if (result.length < md.length * 0.6) {
    console.warn('[stripAcademicSections] result too short, falling back to original', {
      original: md.length,
      result: result.length,
    })
    return md
  }
  if (!/^#{1,3}\s+(\d+|引言|方法|结果|讨论|结论|Introduction|Method|Result|Discussion)/m.test(result)) {
    console.warn('[stripAcademicSections] no body heading found, falling back')
    return md
  }
  return result
}


// 娱乐轨去学术范式：娱乐文不套论文小节。把「引言/方法/结果/讨论/结论」
// 这类学术标题改写为网文口吻的小标题，并去掉章节编号；只动标题，不动正文。
// 触发条件严格限定 fun/rant，论文轨一个字都不改。
const FUN_HEADING_MAP: Array<[RegExp, string]> = [
  [/^(引言|绪论|前言|导论)(?:[：:（(].*)?$/i, '开场'],
  [/^(文献综述|相关工作|Related Work)$/i, '前情提要'],
  [/^(研究设计与方法|研究方法|方法|材料与方法|Methods?|Methodology|Materials and Methods)$/i, '怎么玩的'],
  [/^(研究设计|实验设计)$/i, '怎么搭的'],
  [/^(实验设置|Experimental Setup)$/i, '怎么搭的'],
  [/^(核心概念界定与理论基础)$/i, '先把词说清'],
  [/^(核心概念界定)$/i, '语言通胀是个啥'],
  [/^(理论基础|分析框架)$/i, '拿什么看'],
  [/^(生成动因分析|动因分析)$/i, '为啥会这样'],
  [/^(语义贬值路径实证分析|实证分析)$/i, '拿数据说话'],
  [/^(典型场景的质性拆解|质性拆解)$/i, '一个个看'],
  [/^(数据可用性声明)$/i, '数据放哪了'],
  [/^(作者贡献声明)$/i, '谁干的'],
  [/^(利益冲突声明)$/i, '有没有猫腻'],
  [/^(数据分析|Data Analysis)$/i, '数据怎么说'],
  [/^(结果与讨论|结果|Results?)$/i, '所以呢'],
  [/^(讨论|Discussion)$/i, '聊两句'],
  [/^(结论|结语|总结)(?:[：:（(].*)?$/i, '最后'],
  [/^(Conclusion|Conclusions?)$/i, '最后'],
  [/^(研究局限|局限|Limitations?)$/i, '别信太多'],
  [/^(创新点|研究贡献|贡献)$/i, '花活在哪儿'],
  [/^(研究背景|研究意义|背景)$/i, '为啥聊这个'],
  [/^(研究问题|问题的提出)$/i, '事儿是这么来的'],
  [/^(研究对象)$/i, '先看谁'],
  [/^(研究假设|假设)$/i, '先猜一下'],
  [/^(数据来源|数据来源与空间范围)$/i, '数据哪来的'],
  [/^(实验材料)$/i, '拿什么做的'],
  [/^(模型构建)$/i, '怎么搭的'],
  [/^(统计学分析)$/i, '怎么算的'],
  [/^(问题提出|问题的提出)$/i, '事儿是这么来的'],
  [/^(理论框架|分析框架)$/i, '拿什么看'],
  [/^(案例|案例分析)$/i, '举个例子'],
  [/^(小结)$/i, '先说到这'],
  [/^(参考文献|References?)$/i, '提到的'],
  [/^(致谢|Acknowledg(e)?ments?)$/i, '谢幕'],
  [/^(附录|Appendix)$/i, '彩蛋'],
  [/^(摘要|Abstract)$/i, '开场'],
]

export function humanizeFunMarkdown(md: string): string {
  return md
    .split('\n')
    .map((line) => {
      const m = /^(#{2,4})[ \t]+(.+?)[ \t]*$/.exec(line)
      if (!m) return line
      // 去掉「1」「2.3」「一、」等论文式编号，保留标题本身
      const title = m[2]
        .replace(/^\d+(?:\.\d+)*[.、]?\s*/, '')
        .replace(/^[一二三四五六七八九十]+[、.]\s*/, '')
        .trim()
      const key = title.replace(/[：:]\s*$/u, '')
      const hit = FUN_HEADING_MAP.find(([re]) => re.test(key))
      // 234 篇副刊的标题是作者各自写的，穷举不可能覆盖完。这里做一层
      // 语义兜底：只要标题仍在讲“研究/方法/样本/结果/讨论/结论”，
      // 就换成副刊口吻，正文一个字不动。
      const fallback: Array<[RegExp, string]> = [
        [/研究|方法|模型|样本|变量|数据|实证|实验|检验|回归|统计|假设/u, '怎么做的'],
        [/结果|发现|效应|显著性/u, '所以呢'],
        [/讨论|局限|反思|不足/u, '聊两句'],
        [/结论|总结|启示|建议/u, '最后'],
        [/背景|问题|缘起|动机/u, '为啥聊这个'],
        [/概念|定义|理论|框架|机制/u, '先把词说清'],
        [/案例|场景|样本/u, '举个例子'],
      ]
      // 兜底只处理“纯学术骨架标题”（研究结果 / 研究结论 / 讨论…）。
      // 带具体限定词的标题（仿真结果、SHA-256-QA 总体结果、讨论：认知过载）
      // 保留原词，否则一页会出现多个“所以呢”，比论文标题更难读。
      const qualifier = key
        .replace(/研究|方法|模型|样本|变量|数据|实证|实验|检验|回归|统计|假设|结果|发现|效应|显著性|讨论|局限|反思|不足|结论|总结|启示|建议|背景|问题|缘起|动机|概念|定义|理论|框架|机制|案例|场景/gu, '')
        .replace(/[\s\d.、,，:：;；()（）\-—_]+/g, '')
        .trim()
      const fallbackHit = qualifier.length === 0 ? fallback.find(([re]) => re.test(key)) : undefined
      const mapped = hit ? hit[1] : fallbackHit ? fallbackHit[1] : title
      return `${m[1]} ${mapped}`
    })
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
}

// 邮箱脱敏：原稿里 `* zabwerk@yeah.net`、`邮箱：zabwerk@yeah.net` 这类
// 整行移除；行内残留邮箱也删掉。注意不能吃掉邮箱相邻的作者名/字符。
// 用负向后顾确保不从单词中间开始匹配（避免把 Zabwerk 削成 abwerk）。
const EMAIL_LINE_RE =
  /^[ \t>*-]*\s*(?:邮箱[：:]|Email[：:]|E-mail[：:])?\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\s*[ \t]*$/gim
// 行内邮箱：前后不能是字母数字（避免匹配到 XZabwerk@... 里的子串）
const EMAIL_INLINE_RE = /(?<![A-Za-z0-9])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])/g

export function scrubManuscriptEmails(md: string): string {
  // 1) 整行邮箱（含 * / 邮箱： 前缀）整块删除
  let out = md.replace(EMAIL_LINE_RE, '')
  // 2) 行内残留邮箱删除（不留「未认领」拼接）
  out = out.replace(EMAIL_INLINE_RE, '')
  // 3) 清理因删除留下的孤立列表标记 `* ` 与多余空行
  out = out.replace(/^[ \t]*\*[ \t]*$/gm, '')
  out = out.replace(/\n{3,}/g, '\n\n')
  return out
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
        aria-label={alt || '图示'}
        className="md-img-missing my-5 flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border/70 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_7px,color-mix(in_oklab,var(--color-muted)_35%,transparent)_7px,color-mix(in_oklab,var(--color-muted)_35%,transparent)_8px)] px-4 py-8 text-center"
      >
        <span className="font-mono text-[10px] tracking-[0.18em] text-muted-foreground/70">RUBBISH · FIGURE</span>
        <span className="text-xs text-muted-foreground">图示未随稿附上</span>
      </span>
    )
  }
  return (
    <img
      src={src}
      alt={alt || '稿件插图'}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  )
}

// 中文出版符号在阅读页也要「看得出是什么」：书名号走霞鹜文楷 + 品牌绿，
// 中文引号走霞鹜文楷；与 Word 下载件的 docx_template._add_inline 口径一致。
// 只处理文本节点，KaTeX / 图片等结构化节点原样放行，避免破坏公式。
const CN_INLINE_TOKENS = /(《[^》]{1,80}》|「[^」]{1,80}」|“[^”]{1,80}”)/g

function decorateInline(nodes: ReactNode): ReactNode {
  return Children.map(nodes, (node) => {
    if (typeof node === 'string') {
      const parts = node.split(CN_INLINE_TOKENS)
      if (parts.length === 1) return node
      return parts.map((part, idx) => {
        if (!part) return null
        if (part.startsWith('《')) {
          return <span key={idx} className="md-book-title">{part}</span>
        }
        if (part.startsWith('「') || part.startsWith('“')) {
          return <span key={idx} className="md-quote-cn">{part}</span>
        }
        return <Fragment key={idx}>{part}</Fragment>
      })
    }
    if (isValidElement<{ children?: ReactNode; className?: string }>(node)) {
      const { children, className } = node.props
      if (children === undefined || children === null) return node
      if (typeof className === 'string' && className.includes('katex')) return node
      return cloneElement(node, undefined, decorateInline(children))
    }
    return node
  })
}

// CommonMark 的左右侧翼规则对「**作者：**马必略」这类中文相邻的强调标记
// 常常判为不合法，结果整段显示成字面 **。这里在 mdast 文本节点上兜底：
// 把残留的 **…** 直接转成 strong 节点，只处理文本节点，不碰代码块/公式。
type MdNode = {
  type?: string
  value?: string
  children?: MdNode[]
}

function remarkCjkStrong() {
  return (tree: MdNode) => {
    const repair = (node: MdNode) => {
      if (!Array.isArray(node.children)) return
      const out: MdNode[] = []
      for (const child of node.children) {
        if (child.type === 'text' && typeof child.value === 'string' && child.value.includes('**')) {
          const parts = child.value.split(/(\*\*[^*\n]+\*\*)/g)
          for (const part of parts) {
            if (!part) continue
            const m = /^\*\*([^*\n]+)\*\*$/.exec(part)
            if (m) out.push({ type: 'strong', children: [{ type: 'text', value: m[1] }] })
            else if (part !== '**') out.push({ type: 'text', value: part.replace(/\*\*/g, '') })
          }
        } else {
          repair(child)
          out.push(child)
        }
      }
      node.children = out
    }
    repair(tree)
  }
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
  p: ({ children }) => <p className={paragraphClass(children)}>{decorateInline(children)}</p>,
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
      remarkPlugins={math ? [remarkGfm, remarkCjkStrong, remarkMath] : [remarkGfm, remarkCjkStrong]}
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
  onTocReady,
  hideTocNav = false,
  onFatalError,
  contentCategory,
  contentTrack,
  title,
  abstract,
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

  // 组件内部自行计算 effectiveKind：以 content_category 为准，content_track=essay 兜底。
  // 不依赖外部一次性传值，避免父组件漏传导致裁剪不生效。
  const effectiveKind: 'paper' | 'sci_pop' | 'fun' | 'rant' | 'plain' = (() => {
    const cat = (contentCategory ?? '').toLowerCase()
    if (cat === 'fun') return 'fun'
    if (cat === 'rant') return 'rant'
    if (cat === 'science' || cat === 'science_pop' || cat === 'popular' || cat === 'scipop' || cat === '科普') return 'sci_pop'
    if (cat === 'academic' || cat === 'paper') return 'paper'
    if (contentTrack === 'essay') return 'fun' // 兜底：essay 一律按娱乐处理
    return 'paper'
  })()

  // 底部操作栏的「目录」按钮通过 window 事件唤出抽屉：目录条目是在
  // 本组件里从 Markdown 解析出来的，把状态提上去反而要重解析一遍。
  useEffect(() => {
    const onOpen = () => setTocOpen(true)
    window.addEventListener(TOC_OPEN_EVENT, onOpen)
    return () => window.removeEventListener(TOC_OPEN_EVENT, onOpen)
  }, [])

  const { data, isLoading, isError, error: queryError, refetch } = useQuery({
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
  // 再按轨道裁掉学术小节（fun/rant/sci_pop），并把原稿里的邮箱一律脱敏。
  // 兜底：若 effectiveKind=paper 但原稿以 Open Access 开头（说明 content_category 没标对），
  // 强制走 fun 分支剥刊头。
  const cleaned = (() => {
    if (!data) return data
    let kind = effectiveKind
    if (kind === 'paper' && /^Open Access/i.test(data.trim())) kind = 'fun'
    const stripped = stripAcademicSections(stripHtmlComments(data), kind, title)
    const humanized = kind === 'fun' || kind === 'rant' ? humanizeFunMarkdown(stripped) : stripped
    const deduped =
      kind === 'fun' || kind === 'rant'
        ? stripLeadingDuplicateAbstract(humanized, abstract)
        : humanized
    const noRepeat =
      kind === 'fun' || kind === 'rant' ? dedupeRepeatedParagraphs(deduped) : deduped
    const noRepeatSentence =
      kind === 'fun' || kind === 'rant'
        ? dedupeRepeatedSentences(noRepeat)
        : noRepeat
    return scrubManuscriptEmails(noRepeatSentence)
  })()

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
 const onTocReadyRef = useRef(onTocReady)
 useEffect(() => {
   onTocReadyRef.current = onTocReady
 }, [onTocReady])
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
 onTocReadyRef.current?.(entries)
 }, [data, refs])

  useEffect(() => {
    if (isError) onFatalError?.(queryError)
  }, [isError, queryError, onFatalError])

  // 超宽条图适配：宽高比 ≥ 4 的图（常见于从 PDF 里裁出来的一行公式截图），
  // 按 100% 宽度等比缩放后在 390px 的手机上只剩十几像素高，字迹完全糊掉。
  // 这里把这类图包进可横向滚动的容器，按可读宽度展示。
  useEffect(() => {
    const root = articleRef.current
    if (!root) return
    const wrapWide = () => {
      root.querySelectorAll<HTMLImageElement>('img:not([data-wide])').forEach((img) => {
        const mark = () => {
          if (!img.naturalWidth || !img.naturalHeight) return
          if (img.naturalWidth / img.naturalHeight < 4) return
          if (img.closest('.md-wide-figure')) return
          img.dataset.wide = '1'
          const box = document.createElement('div')
          box.className = 'md-wide-figure'
          img.parentNode?.insertBefore(box, img)
          box.appendChild(img)
          const hint = document.createElement('span')
          hint.className = 'md-wide-figure__hint'
          hint.textContent = '左右滑动查看完整图片'
          box.parentNode?.insertBefore(hint, box.nextSibling)
        }
        if (img.complete) mark()
        else img.addEventListener('load', mark, { once: true })
      })
    }
    wrapWide()
    const timer = window.setTimeout(wrapWide, 400)
    return () => window.clearTimeout(timer)
  }, [data, refsOpen])

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
      {/* 手机上左右各留 14px：390pt 屏里正文行宽从 350 → 362，
          每行多容纳约 1.5 个汉字，长文读起来明显不挤。 */}
      <div className="mx-auto flex max-w-6xl items-start px-3.5 py-6 sm:px-5 sm:py-8">
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

        {toc.length > 2 && !hideTocNav && (
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
            一条常驻工具条会压住摘要开头，读者第一眼先看到一排图标而不是正文。
            容器用正常流占位（不再用负 margin 上提）：上提会让圆钮压在
            摘要卡右上角的边框上，看着像脱层。 */}
        <div className="sticky top-2 z-10 mb-1 flex justify-end">
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
              {prefs.serif ? '衬线' : '无衬线'}
            </button>
          </div>
        </div>
        <article
          ref={articleRef}
          data-content-kind={effectiveKind}
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
