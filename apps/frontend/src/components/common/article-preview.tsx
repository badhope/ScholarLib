import { Badge } from '@/components/ui/badge'
import { MarkdownContent } from '@/components/common/markdown-content'

/**
 * 投稿前的“发布效果预览”。
 *
 * 不是 Markdown 源码预览，也不是字段摘要：按文章页同一套 `.markdown-body`
 * 排版渲染标题、作者、摘要、关键词与正文，让作者在提交前看到发布后的样子。
 * 正文里重复的标题 / 摘要 / 关键词会在预览层剥掉，存储原文不动。
 */
export interface ArticlePreviewProps {
  title: string
  authors: string[]
  abstract: string
  keywords: string[]
  body: string
}

function stripDuplicatePreviewParts(body: string, title: string): string {
  let md = body.trim()
  const firstHeading = md.match(/^#{1,6}\s+([^\n]+)\n+/)
  if (firstHeading && firstHeading[1].trim() === title.trim()) {
    md = md.slice(firstHeading[0].length)
  }
  // 预览已经单独渲染摘要与关键词；正文里的同名小节只在这一层隐藏。
  md = md.replace(
    /^#{1,6}\s*(摘\s*要|Abstract)\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/im,
    '',
  )
  md = md.replace(
    /^#{1,6}\s*(关键词|关键字|Keywords?)\s*\n[\s\S]*?(?=\n#{1,6}\s|$)/im,
    '',
  )
  return md.trim()
}

export function ArticlePreview({
  title,
  authors,
  abstract,
  keywords,
  body,
}: ArticlePreviewProps) {
  const main = stripDuplicatePreviewParts(body, title)
  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-lg border bg-card p-4 sm:p-6">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge variant="secondary">发布效果预览</Badge>
        <span className="text-xs text-muted-foreground">
          与文章页同一套排版；提交前最后校对一次
        </span>
      </div>
      <div className="min-w-0 max-w-full">
        <h1 className="mb-2 break-words font-serif text-xl font-semibold leading-snug sm:text-2xl">
          {title || '未填写标题'}
        </h1>
        {authors.length > 0 && (
          <p className="mb-4 break-words text-sm text-muted-foreground">
            {authors.join('、')}
          </p>
        )}
        {abstract.trim() && (
          <section className="md-abstract markdown-body mb-5 rounded-lg border-l-4 border-primary/70 bg-primary/5 px-4 py-3">
            <h2 className="mb-2 text-xs font-bold tracking-[0.2em] text-primary">摘要</h2>
            <MarkdownContent text={abstract} className="text-sm leading-7" />
          </section>
        )}
        {keywords.length > 0 && (
          <div className="mb-5 flex max-w-full flex-wrap gap-2">
            {keywords.map((k) => (
              <Badge
                key={k}
                variant="outline"
                className="max-w-full whitespace-normal break-words text-left"
              >
                {k}
              </Badge>
            ))}
          </div>
        )}
        {main ? (
          <MarkdownContent text={main} className="min-w-0 max-w-full text-sm" />
        ) : (
          <p className="text-sm text-muted-foreground">正文为空，暂无可预览内容。</p>
        )}
      </div>
    </div>
  )
}

export default ArticlePreview
