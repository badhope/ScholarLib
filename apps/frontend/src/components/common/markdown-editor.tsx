import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  Focus,
  ImagePlus,
  ListTree,
  Search,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
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
import { MarkdownContent } from '@/components/common/markdown-content'
import { cn, extractError } from '@/lib/utils'

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
  /** 传入后显示「图片」按钮；返回可直接放进 Markdown 的 URL。 */
  onUploadImage?: (file: File) => Promise<string>
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
const H4: ToolAction = { label: 'H4', title: '标题四', linePrefix: '#### ' }
const BOLD: ToolAction = {
  label: 'B',
  title: '加粗（Ctrl+B）',
  wrap: ['**', '**'],
}
const ITALIC: ToolAction = {
  label: 'I',
  title: '斜体（Ctrl+I）',
  wrap: ['*', '*'],
}
const UNDERLINE: ToolAction = {
  label: 'U',
  title: '下划线',
  wrap: ['<u>', '</u>'],
}
const HIGHLIGHT: ToolAction = {
  label: '高亮',
  title: '高亮',
  wrap: ['<mark>', '</mark>'],
}
const SUPER: ToolAction = {
  label: 'x²',
  title: '上标',
  wrap: ['<sup>', '</sup>'],
}
const SUB: ToolAction = {
  label: 'x₂',
  title: '下标',
  wrap: ['<sub>', '</sub>'],
}
const BOOK: ToolAction = { label: '《》', title: '书名号', wrap: ['《', '》'] }
const QUOTE_CN: ToolAction = {
  label: '「」',
  title: '中文引号',
  wrap: ['「', '」'],
}
const QUOTE_DOUBLE: ToolAction = {
  label: '“”',
  title: '中文双引号',
  wrap: ['“', '”'],
}
const LIST: ToolAction = {
  label: '• 列表',
  title: '无序列表',
  linePrefix: '- ',
}
const CHECKLIST: ToolAction = {
  label: '☑ 清单',
  title: '任务清单',
  linePrefix: '- [ ] ',
}
const ORDERED: ToolAction = {
  label: '1. 列表',
  title: '有序列表',
  linePrefix: '1. ',
}
const QUOTE: ToolAction = {
  label: '❝ 引用',
  title: '引用块',
  linePrefix: '> ',
}
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
const DIVIDER: ToolAction = {
  label: '分割线',
  title: '分割线',
  block: '\n---\n',
}
const LINK: ToolAction = {
  label: '链接',
  title: '插入链接（Ctrl+K）',
  wrap: ['[', '](https://)'],
}
const INLINE_CODE: ToolAction = {
  label: '`代码`',
  title: '行内代码',
  wrap: ['`', '`'],
}
const FORMULA: ToolAction = {
  label: '$x$',
  title: '行内公式',
  wrap: ['$', '$'],
}
const FORMULA_BLOCK: ToolAction = {
  label: '∑ 公式',
  title: '块级公式',
  block: '\n$$\n\\frac{a}{b}\n$$\n',
}

const HEADING_TOOLS = [H1, H2, H3, H4]
const PARAGRAPH_TOOLS = [LIST, ORDERED, CHECKLIST, QUOTE, DIVIDER]
const INSERT_TOOLS = [
  LINK,
  INLINE_CODE,
  FORMULA,
  FORMULA_BLOCK,
  TABLE,
  CODE,
  HIGHLIGHT,
  UNDERLINE,
  SUPER,
  SUB,
  BOOK,
  QUOTE_CN,
  QUOTE_DOUBLE,
]

export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  minHeight = 320,
  disabled,
  testId,
  onUploadImage,
}: MarkdownEditorProps) {
  const areaRef = useRef<HTMLTextAreaElement | null>(null)
  const imageRef = useRef<HTMLInputElement | null>(null)
  const [tab, setTab] = useState<'edit' | 'split' | 'preview'>('edit')
  const [uploadingImage, setUploadingImage] = useState(false)
  const [findOpen, setFindOpen] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [focusMode, setFocusMode] = useState(false)
  const [findTerm, setFindTerm] = useState('')
  const [replaceTerm, setReplaceTerm] = useState('')
  const history = useRef({ past: [] as string[], future: [] as string[] })
  const lastValue = useRef(value)
  const applyingHistory = useRef(false)
  const [historyState, setHistoryState] = useState({
    canUndo: false,
    canRedo: false,
  })

  const refreshHistoryState = () => {
    setHistoryState({
      canUndo: history.current.past.length > 0,
      canRedo: history.current.future.length > 0,
    })
  }

  // 受控组件的外部重置（例如提交页恢复草稿）不能让旧历史继续可撤销。
  useEffect(() => {
    if (value === lastValue.current) {
      applyingHistory.current = false
      return
    }
    if (!applyingHistory.current) {
      history.current = { past: [], future: [] }
      refreshHistoryState()
    }
    lastValue.current = value
    applyingHistory.current = false
  }, [value])

  const commit = (next: string) => {
    if (next === lastValue.current) return
    history.current.past.push(lastValue.current)
    if (history.current.past.length > 100) history.current.past.shift()
    history.current.future = []
    lastValue.current = next
    applyingHistory.current = true
    refreshHistoryState()
    onChange(next)
  }

  const undo = () => {
    const previous = history.current.past.pop()
    if (previous === undefined) return
    history.current.future.unshift(lastValue.current)
    lastValue.current = previous
    applyingHistory.current = true
    refreshHistoryState()
    onChange(previous)
  }

  const redo = () => {
    const next = history.current.future.shift()
    if (next === undefined) return
    history.current.past.push(lastValue.current)
    lastValue.current = next
    applyingHistory.current = true
    refreshHistoryState()
    onChange(next)
  }

  const canUndo = historyState.canUndo
  const canRedo = historyState.canRedo
  const headings = useMemo(
    () =>
      Array.from(value.matchAll(/^(#{1,6})\s+(.+)$/gm)).map((match) => ({
        level: match[1].length,
        text: match[2].trim(),
        index: match.index ?? 0,
      })),
    [value],
  )

  const focusSelection = (start: number, end = start) => {
    const area = areaRef.current
    if (!area) return
    area.focus()
    area.setSelectionRange(start, end)
    area.scrollIntoView?.({ block: 'center' })
  }

  const findNext = () => {
    if (!findTerm) return
    const area = areaRef.current
    if (!area) return
    const from =
      area.selectionEnd > area.selectionStart
        ? area.selectionEnd
        : area.selectionStart
    let index = value.indexOf(findTerm, from)
    if (index < 0) index = value.indexOf(findTerm)
    if (index < 0) {
      toast.error('没有找到要查找的内容')
      return
    }
    focusSelection(index, index + findTerm.length)
  }

  const replaceOne = () => {
    const area = areaRef.current
    if (!area || !findTerm) return
    if (value.slice(area.selectionStart, area.selectionEnd) !== findTerm) {
      findNext()
      return
    }
    const next =
      value.slice(0, area.selectionStart) +
      replaceTerm +
      value.slice(area.selectionEnd)
    commit(next)
    requestAnimationFrame(() =>
      focusSelection(area.selectionStart + replaceTerm.length),
    )
  }

  const replaceAll = () => {
    if (!findTerm) return
    const next = value.split(findTerm).join(replaceTerm)
    const count = value.split(findTerm).length - 1
    if (count === 0) {
      toast.error('没有找到要替换的内容')
      return
    }
    commit(next)
    toast.success(`已替换 ${count} 处`)
  }

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
      const prefixed = lines
        .map((l) => (l.trim() ? tool.linePrefix + l : l))
        .join('\n')
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
    commit(next)
    requestAnimationFrame(() => {
      area.focus()
      area.setSelectionRange(caretStart, caretEnd)
    })
  }

  const changeIndent = (outdent: boolean) => {
    const area = areaRef.current
    if (!area || disabled) return
    const start = area.selectionStart
    const end = area.selectionEnd

    if (start === end && !outdent) {
      insertText('  ')
      return
    }

    const lineStart = value.lastIndexOf('\n', start - 1) + 1
    const lineEndIdx = value.indexOf('\n', end)
    const lineEnd = lineEndIdx === -1 ? value.length : lineEndIdx
    const block = value.slice(lineStart, lineEnd)
    const lines = block.split('\n')
    const currentLine = value.slice(lineStart, start).split('\n').length - 1

    let removedPrefix = 0
    const changed = lines.map((line, index) => {
      if (!line.trim()) return line
      if (!outdent) return `  ${line}`
      const prefix = line.startsWith('\t')
        ? 1
        : line.startsWith('  ')
          ? 2
          : line.startsWith(' ')
            ? 1
            : 0
      if (index === currentLine) removedPrefix = prefix
      return prefix ? line.slice(prefix) : line
    })

    const transformed = changed.join('\n')
    const next = value.slice(0, lineStart) + transformed + value.slice(lineEnd)
    let nextStart: number
    let nextEnd: number
    if (start === end) {
      nextStart = outdent
        ? Math.max(lineStart, start - removedPrefix)
        : start + 2
      nextEnd = nextStart
    } else {
      nextStart = lineStart
      nextEnd = lineStart + transformed.length
    }
    commit(next)
    requestAnimationFrame(() => {
      area.focus()
      area.setSelectionRange(nextStart, nextEnd)
    })
  }

  const insertText = (text: string) => {
    const area = areaRef.current
    if (disabled) return
    const start = area?.selectionStart ?? value.length
    const end = area?.selectionEnd ?? value.length
    const next = value.slice(0, start) + text + value.slice(end)
    commit(next)
    requestAnimationFrame(() => {
      area?.focus()
      const caret = start + text.length
      area?.setSelectionRange(caret, caret)
    })
  }

  const uploadImageFile = async (file?: File | null) => {
    if (!file || !onUploadImage) return
    if (!file.type.startsWith('image/')) {
      toast.error('只能上传图片文件')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('图片不能超过 5MB')
      return
    }
    setUploadingImage(true)
    try {
      const url = await onUploadImage(file)
      insertText(`\n![${file.name.replace(/\.\w+$/, '') || '图片'}](${url})\n`)
    } catch (err) {
      toast.error(extractError(err, '图片上传失败'))
    } finally {
      setUploadingImage(false)
    }
  }

  const onPickImage = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    await uploadImageFile(file)
  }

  const onDrop = async (e: React.DragEvent<HTMLTextAreaElement>) => {
    const file = e.dataTransfer.files?.[0]
    if (!file || !onUploadImage) return
    e.preventDefault()
    await uploadImageFile(file)
  }

  const onPaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!onUploadImage) return
    const file = Array.from(e.clipboardData.files)[0]
    if (!file?.type.startsWith('image/')) return
    e.preventDefault()
    await uploadImageFile(file)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const modifier = e.ctrlKey || e.metaKey
    if (modifier && !e.altKey) {
      const key = e.key.toLowerCase()
      if (key === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
        return
      }
      if (key === 'y') {
        e.preventDefault()
        redo()
        return
      }
      if (key === 'f') {
        e.preventDefault()
        setFindOpen(true)
        return
      }
    }
    if (modifier && !e.shiftKey) {
      const key = e.key.toLowerCase()
      if (key === 'b') {
        e.preventDefault()
        applyTool(BOLD)
      } else if (key === 'i') {
        e.preventDefault()
        applyTool(ITALIC)
      } else if (key === 'k') {
        e.preventDefault()
        applyTool(LINK)
      } else if (key === 'u') {
        e.preventDefault()
        applyTool(UNDERLINE)
      }
    } else if (e.key === 'Tab') {
      e.preventDefault()
      changeIndent(e.shiftKey)
    }
  }

  return (
    <div
      className={cn(
        'rounded-lg border bg-background',
        focusMode &&
          'fixed inset-0 z-50 overflow-auto rounded-none border-0 bg-background p-3',
      )}
      data-testid={testId ?? 'markdown-editor'}
    >
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1.5">
        <ToolMenu
          label="标题"
          tools={HEADING_TOOLS}
          disabled={disabled}
          onPick={applyTool}
        />
        <ToolButton tool={BOLD} disabled={disabled} onPick={applyTool} />
        <ToolButton tool={ITALIC} disabled={disabled} onPick={applyTool} />
        <ToolMenu
          label="段落"
          tools={PARAGRAPH_TOOLS}
          disabled={disabled}
          onPick={applyTool}
        />
        <ToolMenu
          label="插入"
          tools={INSERT_TOOLS}
          disabled={disabled}
          onPick={applyTool}
        />
        <ToolButton
          tool={{ label: '↶', title: '撤销（Ctrl+Z）' }}
          disabled={disabled || !canUndo}
          onPick={undo}
        />
        <ToolButton
          tool={{ label: '↷', title: '重做（Ctrl+Shift+Z）' }}
          disabled={disabled || !canRedo}
          onPick={redo}
        />
        <EmojiStickerPicker onInsert={insertText} disabled={disabled} />
        {onUploadImage && (
          <>
            <input
              ref={imageRef}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              className="hidden"
              onChange={onPickImage}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled || uploadingImage}
              onClick={() => imageRef.current?.click()}
              className="h-7 gap-1 px-1.5 text-xs font-medium text-muted-foreground"
              title="上传图片（PNG / JPEG / GIF / WebP，最大 5MB）"
              aria-label="上传图片"
            >
              <ImagePlus className="h-3.5 w-3.5" />
              {uploadingImage ? '上传中…' : '图片'}
            </Button>
          </>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="查找替换"
            title="查找替换（Ctrl+F）"
            onClick={() => setFindOpen((open) => !open)}
            className="h-7 gap-1 px-1.5 text-xs text-muted-foreground"
          >
            <Search className="h-3.5 w-3.5" />
            查找
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="文档大纲"
            title="文档大纲"
            onClick={() => setOutlineOpen((open) => !open)}
            className="h-7 gap-1 px-1.5 text-xs text-muted-foreground"
          >
            <ListTree className="h-3.5 w-3.5" />
            大纲
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="专注模式"
            title={focusMode ? '退出专注模式' : '专注模式'}
            onClick={() => setFocusMode((active) => !active)}
            className="h-7 gap-1 px-1.5 text-xs text-muted-foreground"
          >
            {focusMode ? (
              <X className="h-3.5 w-3.5" />
            ) : (
              <Focus className="h-3.5 w-3.5" />
            )}
            {focusMode ? '退出' : '专注'}
          </Button>
          <span
            className="text-xs tabular-nums text-muted-foreground"
            data-testid="md-char-count"
          >
            {charCount} 字
          </span>
          <Tabs
            value={tab}
            onValueChange={(v) => setTab(v as 'edit' | 'split' | 'preview')}
          >
            <TabsList className="h-7">
              <TabsTrigger value="edit" className="h-7 px-2 text-xs">
                编辑
              </TabsTrigger>
              <TabsTrigger value="split" className="h-7 px-2 text-xs">
                分栏
              </TabsTrigger>
              <TabsTrigger value="preview" className="h-7 px-2 text-xs">
                预览
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>
      {findOpen && (
        <div
          className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-2 py-1.5"
          data-testid="md-find-panel"
        >
          <input
            aria-label="查找内容"
            value={findTerm}
            onChange={(event) => setFindTerm(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                findNext()
              }
            }}
            placeholder="查找内容"
            className="h-7 w-36 rounded-md border bg-background px-2 text-xs"
          />
          <input
            aria-label="替换为"
            value={replaceTerm}
            onChange={(event) => setReplaceTerm(event.target.value)}
            placeholder="替换为"
            className="h-7 w-36 rounded-md border bg-background px-2 text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={findNext}
          >
            查找下一个
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={replaceOne}
          >
            替换
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={replaceAll}
          >
            全部替换
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="关闭查找"
            className="ml-auto h-7 px-1.5"
            onClick={() => setFindOpen(false)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
      {outlineOpen && (
        <div
          className="max-h-40 overflow-auto border-b bg-muted/20 px-3 py-2"
          data-testid="md-outline-panel"
        >
          {headings.length > 0 ? (
            <ul className="space-y-0.5">
              {headings.map((heading) => (
                <li key={`${heading.index}-${heading.text}`}>
                  <button
                    type="button"
                    aria-label={`大纲：${heading.text}`}
                    className="w-full truncate rounded px-1 py-0.5 text-left text-xs hover:bg-muted"
                    style={{ paddingLeft: `${(heading.level - 1) * 12 + 4}px` }}
                    onClick={() =>
                      focusSelection(
                        heading.index,
                        heading.index + heading.text.length,
                      )
                    }
                  >
                    <span className="mr-1 text-muted-foreground">
                      H{heading.level}
                    </span>
                    {heading.text}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">
              还没有标题。用 # 或 H1-H4 建立大纲。
            </p>
          )}
        </div>
      )}
      {tab === 'preview' ? (
        <div
          className="overflow-auto px-4 py-3"
          style={{ minHeight }}
          data-testid="md-preview"
        >
          {value.trim() ? (
            <MarkdownContent text={value} className="text-sm" />
          ) : (
            <p className="text-sm text-muted-foreground">暂无内容</p>
          )}
        </div>
      ) : (
        <div
          className={cn(
            'grid min-w-0',
            tab === 'split' ? 'lg:grid-cols-2 lg:divide-x' : 'grid-cols-1',
          )}
        >
          <div className="relative min-w-0">
            <textarea
              ref={areaRef}
              value={value}
              disabled={disabled}
              onChange={(e) => commit(e.target.value)}
              onKeyDown={onKeyDown}
              onDrop={onDrop}
              onPaste={onPaste}
              aria-label={
                placeholder ? `Markdown 正文：${placeholder}` : 'Markdown 正文'
              }
              placeholder={placeholder}
              spellCheck={false}
              style={{ minHeight }}
              className="w-full resize-y rounded-b-lg bg-transparent px-3 py-2 font-mono text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50"
            />
          </div>
          {tab === 'split' && (
            <div
              className="max-h-[70vh] overflow-auto border-t px-4 py-3 lg:border-t-0"
              style={{ minHeight }}
              data-testid="md-split-preview"
            >
              {value.trim() ? (
                <MarkdownContent text={value} className="text-sm" />
              ) : (
                <p className="text-sm text-muted-foreground">
                  左侧开始输入后，这里实时排版。
                </p>
              )}
            </div>
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
      aria-label={tool.title}
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
          aria-label={`插入${label}`}
          className="h-7 gap-0.5 px-1.5 text-xs font-medium text-muted-foreground"
        >
          {label}
          <ChevronDown className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-44">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          {label}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {tools.map((tool, index) => (
          <DropdownMenuItem
            key={tool.title}
            onSelect={() => onPick(tool)}
            data-testid={`md-tool-${tool.title}`}
            className={cn('gap-2 text-xs', index === 0 ? 'mt-0.5' : '')}
          >
            <span className="min-w-10 font-mono text-muted-foreground">
              {tool.label}
            </span>
            <span>{tool.title}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default MarkdownEditor
