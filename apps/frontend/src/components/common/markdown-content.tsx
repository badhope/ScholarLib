import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { cn } from '@/lib/utils'

/**
 * 论坛/编辑器共用的 Markdown 渲染。
 *
 * 编辑器工具栏会插入 <u> / <mark> / <sup> / <sub> 这类原生 HTML；
 * react-markdown 默认不解析 HTML，用户就会看到一堆标签。这里用
 * rehype-raw 解析，再用 rehype-sanitize 白名单过滤，保留排版能力，
 * 同时挡掉 script / iframe / 事件属性等 XSS 面。
 */
const schema = {
  ...defaultSchema,
  tagNames: [...new Set([...(defaultSchema.tagNames ?? []), 'u', 'mark', 'sup', 'sub'])],
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
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, schema]]}
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
