import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { ArrowRight, Bell, Megaphone } from 'lucide-react'
import { useActiveAnnouncement } from '@/hooks/api/use-modules'
import type { Announcement } from '@/lib/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

// 编辑部公告弹窗：只认设备，不认账号（游客也要看到）。
// 关闭后 30 天内不再自动弹出；公告换 slug 会重新出现；
// 顶栏的「公告」按钮随时可重开。公告本身可在管理后台随时下线。
const DISMISS_KEY = 'rubbish_announcement_dismissed'
const DISMISS_DAYS = 30

export function announcementSeen(slug: string): boolean {
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY)
    if (!raw) return false
    const parsed = JSON.parse(raw) as { slug: string; at: number }
    if (parsed.slug !== slug) return false
    return Date.now() - parsed.at < DISMISS_DAYS * 86400_000
  } catch {
    return false
  }
}

function remember(slug: string): void {
  try {
    window.localStorage.setItem(
      DISMISS_KEY,
      JSON.stringify({ slug, at: Date.now() }),
    )
  } catch {
    // 私密模式 / 存储被禁：仅本次会话生效，不持久化。
  }
}

const LEVEL_ACCENT: Record<string, string> = {
  info: 'bg-primary',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  critical: 'bg-destructive',
}

const LEVEL_TEXT: Record<string, string> = {
  info: 'text-primary',
  success: 'text-emerald-600 dark:text-emerald-400',
  warning: 'text-amber-600 dark:text-amber-400',
  critical: 'text-destructive',
}

const LEVEL_LABELS: Record<string, string> = {
  info: '编辑部公告',
  success: '好消息',
  warning: '重要通知',
  critical: '紧急公告',
}

/**
 * 公告卡片弹窗：自动弹出（未读过时）+ 受控开关（顶栏按钮复用同一状态）。
 * 长正文在弹窗内滚动，不撑破小屏视口。
 */
export function AnnouncementDialog({
  announcement,
  open,
  onOpenChange,
}: {
  announcement: Announcement
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const lines = announcement.body.split('\n').filter(Boolean)

  // 告诉全局「现在有模态占用视口」：Cookie 条据此让位，避免手机首屏
  // 被两层浮层同时压住（关掉弹窗后 Cookie 条会自己回来）。
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('rubbish:modal', { detail: open }))
    return () => {
      window.dispatchEvent(new CustomEvent('rubbish:modal', { detail: false }))
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="gap-0 overflow-hidden rounded-xl p-0"
        aria-describedby={undefined}
      >
        <span
          aria-hidden
          className={`absolute inset-x-0 top-0 h-1 ${LEVEL_ACCENT[announcement.level] ?? LEVEL_ACCENT.info}`}
        />
        <DialogHeader className="gap-2 p-6 pb-4">
          <p
            className={`flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.24em] ${
              LEVEL_TEXT[announcement.level] ?? LEVEL_TEXT.info
            }`}
          >
            <Megaphone className="h-3.5 w-3.5" />
            {LEVEL_LABELS[announcement.level] ?? LEVEL_LABELS.info}
          </p>
          <DialogTitle className="pr-6 text-xl leading-snug sm:text-2xl">
            {announcement.title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            来自 Rubbish 编辑部的公告，阅读后可关闭，30 天内不会再次自动弹出。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 px-6 pb-2 text-sm leading-relaxed text-muted-foreground">
          {lines.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
        <DialogFooter className="flex-row flex-wrap items-center justify-between gap-3 border-t bg-background/60 p-4 sm:justify-between">
          <div className="flex flex-wrap gap-4">
            <Link
              to="/levels"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              查看等级与投稿规范 <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              to="/archive"
              className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
            >
              本期目录 <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <Button type="button" onClick={() => onOpenChange(false)}>
            我知道了
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * 顶栏公告入口：未读时带圆点提醒；点击重开弹窗。
 * 无进行中的公告时不渲染。
 */
export function AnnouncementChip({
  announcement,
  seen,
  onOpen,
}: {
  announcement: Announcement | undefined
  seen: boolean
  onOpen: () => void
}) {
  if (!announcement) return null
  return (
    <button
      type="button"
      onClick={onOpen}
      className="relative inline-flex items-center gap-1 rounded-full border bg-card px-2.5 py-1 text-xs text-foreground/80 transition-colors hover:border-primary/40 hover:text-foreground"
      aria-label={seen ? '查看编辑部公告' : '查看未读的编辑部公告'}
    >
      <Bell className="h-3.5 w-3.5" />
      公告
      {!seen && (
        <span
          aria-hidden
          className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-destructive"
        />
      )}
    </button>
  )
}

/**
 * 首页公告组装：自动弹出逻辑 + 弹窗 + 顶栏入口共用一份状态。
 * 任何方式关闭（按钮 / 遮罩 / Esc）都记为已读 —— 否则同会话内
 * 下次进入首页还会再弹。顶栏重开不受影响（重开不写已读）。
 */
export function useAnnouncementPortal() {
  const { data } = useActiveAnnouncement()
  const [open, setOpen] = useState(false)
  const seen = data ? announcementSeen(data.slug) : true

  // 不做自动弹窗：公告以顶栏 chip + 红点提示，点击才展开。
  // 自动弹窗会在首屏正中央盖住刊头与统计卡，移动端尤其像故障。


  const handleOpenChange = (next: boolean) => {
    if (!next && data) remember(data.slug)
    setOpen(next)
  }

  return { announcement: data ?? undefined, open, seen, setOpen, onOpenChange: handleOpenChange }
}
