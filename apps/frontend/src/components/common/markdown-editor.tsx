import { useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { EmojiStickerPicker } from '@/components/common/emoji-sticker-picker'
import { cn } from '@/lib/utils'

/**
 * 在线 Word 级 Markdown 编辑器。
 *
 * 工具栏不再把 20+ 个按钮平铺（移动端会折成 4 行、正文被挤到很下面）。
 * 现在只保留高频的「标题 / 加粗 / 斜体 / 段落 / 插入」五个入口，
 * 其余语义收进两个分组菜单；编辑/预览和字数固定在右侧。
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

const H1: ToolAction = { label: 'H1', title: '标题一', linePrefix: '# ' }
const H2: ToolAction = { label: 'H2', title: '标题二', linePrefix: '## ' }
const H3: ToolAction = { label: 'H3', title: '标题三', linePrefix: '### ' }
const BOLD: ToolAction = { label: 'B', title: '加粗（Ctrl+B）', wrap: ['**', '**'] }
const ITALIC: ToolAction = { label: 'I', title: '斜体（Ctrl+I）', wrap: ['*', '*'] }
const UNDERLINE: ToolAction = { label: 'U', title: '下划线', wrap: ['<u>', '</u>'] }
const HIGHLIGHT: ToolAction = { label: '高亮', title: '高亮', wrap: ['<mark>', '</mark>'] }
const SUPER: ToolAction = { label: 'x²', title: '上标', wrap: ['<sup>', '</sup>'] }
const SUB: ToolAction = { label: 'x₂', title: '下标', wrap: ['<sub>', '</sub>'] }
const BOOK: ToolAction = { label: '《》', title: '书名号', wrap: ['《', '》'] }
const QUOTE_CN: ToolAction = { label: '「」', title: '中文引号', wrap: ['「', '」'] }
const QUOTE_DOUBLE: ToolAction = { label: '“”', title: '中文双引号', wrap: ['“', '”'] }
const LIST: ToolAction = { label: '• 列表', title: '无序列表', linePrefix: '- ' }
const ORDERED: ToolAction = { label: '1. 列表', title: '有序列表', linePrefix: '1. ' }
const QUOTE: ToolAction = { label: '❝ 引用', title: '引用块', linePrefix: '> ' }
const TABLE: ToolAction = {
  label: '表格',
  title: '三线表骨架',
  block: '\n| 项目 | 数值 |\n| --- | --- |\n| 甲 | 1 |\n| 乙 | 2 |\n',
}
const CODE: ToolAction = {
  label: '代码块',
  title: '代码块',
  block: '\n```python\nprint("hello")\n```\n',
}
const DIVIDER: ToolAction = { label: '分割线', title: '分割线', block: '\n---\n' }

const HEADING_TOOLS = [H1, H2, H3]
const PARAGRAPH_TOOLS = [LIST, ORDERED, QUOTE, DIVIDER]
const INSERT_TOOLS = [TABLE, CODE, HIGHLIGHT, UNDERLINE, SUPER, SUB, BOOK, QUOTE_CN, QUOTE_DOUBLE]

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

  const insertText = (text: string) => {
    const area = areaRef.current
    if (disabled) return
    const start = area?.selectionStart ?? value.length
    const end = area?.selectionEnd ?? value.length
    const next = value.slice(0, start) + text + value.slice(end)
    onChange(next)
    requestAnimationFrame(() => {
      area?.focus()
      const caret = start + text.length
      area?.setSelectionRange(caret, caret)
    })
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
      const key = e.key.toLowerCase()
      if (key === 'b') {
        e.preventDefault()
        applyTool(BOLD)
      } else if (key === 'i') {
        e.preventDefault()
        applyTool(ITALIC)
      }
    }
  }

  return (
    <div className="rounded-lg border bg-background" data-testid={testId ?? 'markdown-editor'}>
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1.5">
        <ToolMenu label="标题" tools={HEADING_TOOLS} disabled={disabled} onPick={applyTool} />
        <ToolButton tool={BOLD} disabled={disabled} onPick={applyTool} />
        <ToolButton tool={ITALIC} disabled={disabled} onPick={applyTool} />
        <ToolMenu label="段落" tools={PARAGRAPH_TOOLS} disabled={disabled} onPick={applyTool} />
        <ToolMenu label="插入" tools={INSERT_TOOLS} disabled={disabled} onPick={applyTool} />
        <EmojiStickerPicker onInsert={insertText} disabled={disabled} />

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs tabular-nums text-muted-foreground" data-testid="md-char-count">
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

function ToolButton({
  tool,
  disabled,
  onPick,
}: {
  tool: ToolAction
  disabled?: boolean
  onPick: (tool: ToolAction) => void
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      title={tool.title}
      disabled={disabled}
      onClick={() => onPick(tool)}
      className="h-7 min-w-7 px-1.5 text-xs font-semibold"
      data-testid={`md-tool-${tool.title}`}
    >
      {tool.label}
    </Button>
  )
}

function ToolMenu({
  label,
  tools,
  disabled,
  onPick,
}: {
  label: string
  tools: ToolAction[]
  disabled?: boolean
  onPick: (tool: ToolAction) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-7 gap-0.5 px-1.5 text-xs font-medium text-muted-foreground"
        >
          {label}
          <ChevronDown className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-44">
        <DropdownMenuLabel className="text-xs text-muted-foreground">{label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {tools.map((tool, index) => (
          <DropdownMenuItem
            key={tool.title}
            onSelect={() => onPick(tool)}
            data-testid={`md-tool-${tool.title}`}
            className={cn('gap-2 text-xs', index === 0 ? 'mt-0.5' : '')}
          >
            <span className="min-w-10 font-mono text-muted-foreground">{tool.label}</span>
            <span>{tool.title}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default MarkdownEditor
