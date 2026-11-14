import ReactMarkdown, { defaultUrlTransform, type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeRaw from 'rehype-raw'
import rehypeKatex from 'rehype-katex'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import 'katex/dist/katex.min.css'
import { cn } from '@/lib/utils'

/**
 * 论坛/编辑器/文章预览共用的 Markdown 渲染。
 *
 * 以前这里只挂了 GFM：公式显示成 `$...$`、data 图片被清洗掉、HTML 图注
 * 不生效。现在统一补齐四件事：
 * 1. remark-math + KaTeX 渲染行内/块级公式；
 * 2. rehype-raw 保留编辑器插入的 <u>/<mark>/<figure> 等排版标签；
 * 3. 白名单清洗（含 id/class/colspan/rowspan），既保留排版又挡 XSS；
 * 4. data:image 图片白名单，避免上传图或公式图被默认 URL 清洗清空。
 */
export const markdownSanitizeSchema = {
  ...defaultSchema,
  tagNames: [
    ...new Set([
      ...(defaultSchema.tagNames ?? []),
      'u',
      'mark',
      'sup',
      'sub',
      'figure',
      'figcaption',
      'details',
      'summary',
      'kbd',
      'picture',
      'source',
    ]),
  ],
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src ?? []), 'data'],
  },
  attributes: {
    ...defaultSchema.attributes,
    '*': [...(defaultSchema.attributes?.['*'] ?? []), 'className', 'id'],
    a: [...(defaultSchema.attributes?.a ?? []), 'target', 'rel'],
    img: [
      ...(defaultSchema.attributes?.img ?? []),
      'loading',
      'decoding',
      'width',
      'height',
    ],
    code: [...(defaultSchema.attributes?.code ?? []), 'className'],
    table: [...(defaultSchema.attributes?.table ?? []), 'align'],
    td: [...(defaultSchema.attributes?.td ?? []), 'colSpan', 'rowSpan', 'align'],
    th: [...(defaultSchema.attributes?.th ?? []), 'colSpan', 'rowSpan', 'align'],
    input: [...(defaultSchema.attributes?.input ?? []), 'checked', 'disabled', 'type'],
    details: [...(defaultSchema.attributes?.details ?? []), 'open'],
  },
}

const markdownComponents: Components = {
  a: ({ href, children, ...props }) => {
    const external = typeof href === 'string' && /^https?:\/\//i.test(href)
    return (
      <a
        href={href}
        {...props}
        {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      >
        {children}
      </a>
    )
  },
  img: ({ src, alt, ...props }) =>
    typeof src === 'string' && src ? (
      <img src={src} alt={alt ?? ''} loading="lazy" decoding="async" {...props} />
    ) : null,
  table: ({ children }) => (
    <div className="md-table-wrap">
      <table>{children}</table>
    </div>
  ),
}

/**
 * CommonMark 的左右侧翼规则对「**作者：**马必略」这类中文相邻的强调标记
 * 常判为不合法，渲染后会露出字面 **。这里在 mdast 文本节点上兜底，
 * 只处理文本节点，不碰代码块/公式；编辑器预览、投稿预览和文章页共用。
 */
type MdNode = {
  type?: string
  value?: string
  children?: MdNode[]
}

export function remarkCjkStrong() {
  return (tree: MdNode) => {
    const repair = (node: MdNode) => {
      if (!Array.isArray(node.children)) return
      const out: MdNode[] = []
      for (const child of node.children) {
        if (child.type === 'text' && typeof child.value === 'string' && child.value.includes('**')) {
          const parts = child.value.split(/(\*\*[^*\n]+\*\*)/g)
          for (const part of parts) {
            if (!part) continue
            const match = /^\*\*([^*\n]+)\*\*$/.exec(part)
            if (match) out.push({ type: 'strong', children: [{ type: 'text', value: match[1] }] })
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

export function markdownUrlTransform(url: string): string {
  return url.startsWith('data:image/') ? url : defaultUrlTransform(url)
}

export function MarkdownContent({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  return (
    <div className={cn('markdown-body', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCjkStrong, remarkMath]}
        rehypePlugins={[
          rehypeRaw,
          [rehypeSanitize, markdownSanitizeSchema],
          [rehypeKatex, { strict: false }],
        ]}
        urlTransform={markdownUrlTransform}
        components={markdownComponents}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

/**
 * 列表卡片里的两行摘要：只渲染行内样式，不渲染图片、标题和链接。
 * 这样 **加粗** 会真的加粗，而不是把星号露出来。
 */
export function MarkdownExcerpt({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const clean = text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/<[^>]+>/g, '')
    .trim()
  return (
    <div className={cn('markdown-body markdown-excerpt', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        allowedElements={['strong', 'em', 'del', 'code', 'br']}
        unwrapDisallowed
        skipHtml
      >
        {clean}
      </ReactMarkdown>
    </div>
  )
}
