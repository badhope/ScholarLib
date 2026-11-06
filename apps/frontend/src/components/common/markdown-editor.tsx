import { useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

/**
 * 在线 Word 级 Markdown 编辑器（2.0）。
 *
 * 投稿表单的正文编辑不再是裸 textarea：工具栏覆盖《投稿规范》要求的全
 * 部排版语义（标题一/二、加粗、斜体、删除线、行内码、书名号、中文引号、
 * 高亮、下划线、上下标、列表、表格、引用、代码块），所见即所存——编辑
 * 器产出的 Markdown 在阅读页与 Word/JATS 导出中有同样的语义。
 */

export interface MarkdownEditorProps {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  minHeight?: number
  disabled?: boolean
  testId?: string
}

interface ToolAction {
  label: string
  title: string
  wrap?: [string, string]
  linePrefix?: string
  block?: string
}

const TOOLS: ToolAction[] = [
  { label: 'H1', title: '标题一', linePrefix: '# ' },
  { label: 'H2', title: '标题二', linePrefix: '## ' },
  { label: 'H3', title: '标题三', linePrefix: '### ' },
  { label: 'B', title: '加粗（Ctrl+B）', wrap: ['**', '**'] },
  { label: 'I', title: '斜体（Ctrl+I）', wrap: ['*', '*'] },
  { label: 'S', title: '删除线', wrap: ['~~', '~~'] },
  { label: '</>', title: '行内代码', wrap: ['`', '`'] },
  { label: '《》', title: '书名号', wrap: ['《', '》'] },
  { label: '「」', title: '中文引号', wrap: ['「', '」'] },
  { label: '“”', title: '中文双引号', wrap: ['“', '”'] },
  { label: '高亮', title: '高亮（导出为黄色标记）', wrap: ['<mark>', '</mark>'] },
  { label: 'U', title: '下划线', wrap: ['<u>', '</u>'] },
  { label: 'x²', title: '上标', wrap: ['<sup>', '</sup>'] },
  { label: 'x₂', title: '下标', wrap: ['<sub>', '</sub>'] },
  { label: '• 列表', title: '无序列表', linePrefix: '- ' },
  { label: '1. 列表', title: '有序列表', linePrefix: '1. ' },
  { label: '❝ 引用', title: '引用块', linePrefix: '> ' },
  {
    label: '表格',
    title: '三线表骨架',
    block: '\n| 项目 | 数值 |\n| --- | --- |\n| 甲 | 1 |\n| 乙 | 2 |\n',
  },
  {
    label: '代码块',
    title: '代码块',
    block: '\n```python\nprint("hello")\n```\n',
  },
  { label: '分割线', title: '分割线', block: '\n---\n' },
]

export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  minHeight = 320,
  disabled,
  testId,
}: MarkdownEditorProps) {
  const areaRef = useRef<HTMLTextAreaElement | null>(null)
  const [tab, setTab] = useState<'edit' | 'preview'>('edit')

  const charCount = useMemo(() => value.replace(/\s/g, '').length, [value])

  const applyTool = (tool: ToolAction) => {
    const area = areaRef.current
    if (!area || disabled) return
    const start = area.selectionStart
    const end = area.selectionEnd
    const selected = value.slice(start, end)

    let next: string
    let caretStart: number
    let caretEnd: number
    if (tool.block !== undefined) {
      next = value.slice(0, start) + tool.block + value.slice(end)
      caretStart = start + tool.block.length
      caretEnd = caretStart
    } else if (tool.linePrefix !== undefined) {
      const lineStart = value.lastIndexOf('\n', start - 1) + 1
      const lineEndIdx = value.indexOf('\n', end)
      const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx
      const lines = value.slice(lineStart, lineEnd).split('\n')
      const prefixed = lines.map((l) => (l.trim() ? tool.linePrefix + l : l)).join('\n')
      next = value.slice(0, lineStart) + prefixed + value.slice(lineEnd)
      caretStart = lineStart
      caretEnd = lineStart + prefixed.length
    } else {
      const [before, after] = tool.wrap as [string, string]
      const inner = selected || ''
      next = value.slice(0, start) + before + inner + after + value.slice(end)
      caretStart = start + before.length
      caretEnd = caretStart + inner.length
    }
    onChange(next)
    requestAnimationFrame(() => {
      area.focus()
      area.setSelectionRange(caretStart, caretEnd)
    })
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
      const key = e.key.toLowerCase()
      if (key === 'b') {
        e.preventDefault()
        applyTool(TOOLS.find((t) => t.label === 'B') as ToolAction)
      } else if (key === 'i') {
        e.preventDefault()
        applyTool(TOOLS.find((t) => t.label === 'I') as ToolAction)
      }
    }
  }

  return (
    <div className="rounded-lg border bg-background" data-testid={testId ?? 'markdown-editor'}>
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1.5">
        {TOOLS.map((tool) => (
          <button
            key={tool.label}
            type="button"
            title={tool.title}
            disabled={disabled}
            onClick={() => applyTool(tool)}
            className={cn(
              'rounded px-1.5 py-1 text-xs font-medium text-muted-foreground transition-colors',
              'hover:bg-muted hover:text-foreground disabled:opacity-40',
            )}
            data-testid={`md-tool-${tool.title}`}
          >
            {tool.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground" data-testid="md-char-count">
            {charCount} 字
          </span>
          <Tabs value={tab} onValueChange={(v) => setTab(v as 'edit' | 'preview')}>
            <TabsList className="h-7">
              <TabsTrigger value="edit" className="h-7 px-2 text-xs">
                编辑
              </TabsTrigger>
              <TabsTrigger value="preview" className="h-7 px-2 text-xs">
                预览
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>
      {tab === 'edit' ? (
        <textarea
          ref={areaRef}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          spellCheck={false}
          style={{ minHeight }}
          className="w-full resize-y rounded-b-lg bg-transparent px-3 py-2 font-mono text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
      ) : (
        <div
          className="overflow-auto px-4 py-3"
          style={{ minHeight }}
          data-testid="md-preview"
        >
          {value.trim() ? (
            <div className="markdown-body text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无内容</p>
          )}
        </div>
      )}
    </div>
  )
}

export default MarkdownEditor
