import { useState } from 'react'
import { SmilePlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

const GROUPS = [
  {
    label: '常用',
    items: ['😀', '😄', '😂', '😊', '🙂', '😉', '😍', '🤔', '👀', '👍', '👏', '🙌', '🤝', '💪', '🙏', '🎉', '🔥', '✨', '💡', '✅', '❌', '⚠️', '📌', '📚', '☕', '🌙', '😭', '😅', '😮', '🤯'],
  },
  {
    label: '学术',
    items: ['📖', '📝', '📊', '📈', '📉', '🔬', '🧪', '🧬', '💻', '🧮', '📎', '🗂️', '🕯️', '🧠', '🎓', '🏫', '📅', '⏳', '🧐', '🫠'],
  },
  {
    label: '情绪',
    items: ['😤', '😩', '😵', '🫥', '🥲', '😴', '🥳', '😎', '🤓', '🫡', '🤌', '👌', '✌️', '🤞', '💔', '🫶', '🙃', '🫣'],
  },
]

/** 站内“学术表情包”：比外链 GIF 更可控，加载快，也不会突然变成失效图。 */
const STICKERS = [
  { name: '数据呢', src: '/stickers/data.svg' },
  { name: '再想想', src: '/stickers/again.svg' },
  { name: '已阅', src: '/stickers/read.svg' },
  { name: '好活', src: '/stickers/nice.svg' },
  { name: '裂开', src: '/stickers/crack.svg' },
  { name: '先睡', src: '/stickers/sleep.svg' },
  { name: '收到', src: '/stickers/got.svg' },
  { name: '审稿人2', src: '/stickers/reviewer2.svg' },
]

export function EmojiStickerPicker({
  onInsert,
  disabled,
}: {
  onInsert: (text: string) => void
  disabled?: boolean
}) {
  const [group, setGroup] = useState(0)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-7 gap-1 px-1.5 text-xs font-medium text-muted-foreground"
          title="插入表情或学术表情包"
          data-testid="md-tool-emoji"
        >
          <SmilePlus className="h-3.5 w-3.5" />
          表情
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[21rem] p-3" data-testid="emoji-panel">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium">表情</p>
          <div className="flex gap-0.5 rounded-md bg-muted p-0.5">
            {GROUPS.map((g, i) => (
              <button
                key={g.label}
                type="button"
                onClick={() => setGroup(i)}
                className={cn(
                  'rounded px-2 py-0.5 text-[11px] transition-colors',
                  group === i
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-2 grid grid-cols-10 gap-0.5">
          {GROUPS[group].items.map((emoji) => (
            <button
              key={emoji}
              type="button"
              onClick={() => onInsert(emoji)}
              className="flex h-7 items-center justify-center rounded text-base transition-colors hover:bg-muted"
              aria-label={`插入 ${emoji}`}
            >
              {emoji}
            </button>
          ))}
        </div>

        <div className="mt-3 border-t pt-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium">学术表情包</p>
            <span className="text-[10px] text-muted-foreground">点一下插进正文</span>
          </div>
          <div className="mt-1.5 grid grid-cols-4 gap-1.5">
            {STICKERS.map((s) => (
              <button
                key={s.src}
                type="button"
                onClick={() => onInsert(`\n![${s.name}](${s.src})\n`)}
                className="group overflow-hidden rounded-md border bg-muted/30 p-0.5 transition-colors hover:border-primary/30 hover:bg-primary/5"
                title={`插入表情包：${s.name}`}
              >
                <img src={s.src} alt={s.name} className="h-full w-full rounded" loading="lazy" />
                <span className="mt-0.5 block text-center text-[10px] text-muted-foreground group-hover:text-foreground">
                  {s.name}
                </span>
              </button>
            ))}
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
