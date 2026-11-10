import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ClipboardList, Eye, Pencil } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/**
 * 带「编辑 / 预览」双态的 Markdown 输入框。
 *
 * 站内长文本表单（审稿意见、申诉理由、反馈处理说明）统一用它：
 * 写的人能随时看到读者会看到的排版，也能一键插入结构模板；
 * 计数器只提示，不替代后端的硬校验。
 */
export function MarkdownField({
  id,
  label,
  description,
  value,
  onChange,
  placeholder,
  template,
  minRecommended = 0,
  maxLength,
  rows = 6,
  disabled,
}: {
  id: string
  label: string
  description?: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  template?: string
  minRecommended?: number
  maxLength?: number
  rows?: number
  disabled?: boolean
}) {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')
  const count = value.trim().length
  const tooShort = minRecommended > 0 && count > 0 && count < minRecommended
  const tooLong = maxLength != null && count > maxLength

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Label htmlFor={id}>{label}</Label>
          {description ? (
            <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-1">
          {template ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onChange(value.trim() ? `${value.trim()}\n\n${template}` : template)}
              disabled={disabled}
            >
              <ClipboardList className="h-3.5 w-3.5" />
              插入模板
            </Button>
          ) : null}
          <Button
            type="button"
            variant={mode === 'preview' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => setMode((m) => (m === 'edit' ? 'preview' : 'edit'))}
          >
            {mode === 'edit' ? <Eye className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {mode === 'edit' ? '预览' : '继续编辑'}
          </Button>
        </div>
      </div>

      {mode === 'edit' ? (
        <Textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={rows}
          maxLength={maxLength}
          disabled={disabled}
        />
      ) : (
        <div className="min-h-[9rem] rounded-md border bg-muted/20 px-3 py-2.5">
          {value.trim() ? (
            <div className="markdown-body text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">还没有填写，切换到「继续编辑」开始写。</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <span
          className={cn(
            'text-muted-foreground',
            tooShort && 'text-amber-700 dark:text-amber-300',
            tooLong && 'text-destructive',
          )}
        >
          已写 {count} 字
          {minRecommended > 0 ? ` · 建议不少于 ${minRecommended} 字` : ''}
          {maxLength != null ? ` · 上限 ${maxLength} 字` : ''}
        </span>
        <span className="text-muted-foreground">支持 Markdown；预览只在本机显示，不会提前提交。</span>
      </div>
    </div>
  )
}
