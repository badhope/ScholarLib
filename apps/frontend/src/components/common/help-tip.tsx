import { HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

/** 操作旁注：鼠标悬停或键盘聚焦时显示，移动端点击也能看。 */
export function HelpTip({ text, className }: { text: string; className?: string }) {
  return (
    <span className={cn('group relative inline-flex align-middle', className)} tabIndex={0} role="note" aria-label={text}>
      <HelpCircle className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="pointer-events-none absolute bottom-full left-1/2 z-[70] mb-2 hidden w-64 -translate-x-1/2 rounded-md border bg-popover px-3 py-2 text-xs font-normal leading-relaxed text-popover-foreground shadow-md group-hover:block group-focus:block">
        {text}
      </span>
    </span>
  )
}
