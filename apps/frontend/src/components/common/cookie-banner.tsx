/**
 * Cookie consent banner — GDPR / ePrivacy lite.
 *
 * Three-state policy stored in localStorage:
 *   - "accepted"  → user accepted all non-essential cookies
 *   - "essential"  → user opted out of non-essential cookies
 *   - unset       → banner is shown; no decision yet
 *
 * Non-essential cookies in this app:
 *   - csrf (set by backend on first GET; same-origin, JS-readable so
 *     double-submit middleware can compare it to X-CSRF-Token header)
 *
 * Essential cookies (always on, not gated by this banner):
 *   - rubbish_refresh_token (httpOnly, server-side)
 *   - rubbish_csrf (when backend csrf middleware is enabled)
 *   - rubbish_tenant (when tenancy middleware runs)
 */
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type ConsentValue = 'accepted' | 'essential'

const CONSENT_KEY = 'rubbish_cookie_consent'

function readConsent(): ConsentValue | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(CONSENT_KEY)
    if (raw === 'accepted' || raw === 'essential') return raw
  } catch {
    // localStorage can be unavailable (private mode, disabled).
    // Fall back to a no-banner state rather than crashing the app.
  }
  return null
}

function writeConsent(value: ConsentValue): void {
  try {
    window.localStorage.setItem(CONSENT_KEY, value)
  } catch {
    // ignore
  }
}

export function CookieBanner() {
  // null = undecided (show banner), otherwise hide.
  const [consent, setConsent] = useState<ConsentValue | null>(() => readConsent())
  // 有模态弹窗（编辑部公告）占用视口时先让位：手机上 390px 宽、844px 高，
  // 弹窗 + Cookie 条同时压屏等于把首屏全部遮死。弹窗关掉后再问。
  const [blocked, setBlocked] = useState(false)

  // Cross-tab sync: if another tab sets a decision, hide here too.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== CONSENT_KEY) return
      setConsent(readConsent())
    }
    function onModal(e: Event) {
      setBlocked(Boolean((e as CustomEvent<boolean>).detail))
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('rubbish:modal', onModal)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('rubbish:modal', onModal)
    }
  }, [])

  if (consent !== null || blocked) return null

  const accept = () => {
    writeConsent('accepted')
    setConsent('accepted')
  }
  const essentialOnly = () => {
    writeConsent('essential')
    setConsent('essential')
  }

  return (
    // 位置：手机端走文档流、贴在内容最上方一行；桌面端固定整条底边。
    // 曾经 fixed 贴底：会盖住列表首条、指标雷达图与文章底部 CTA；
    // 也试过放文档流但塞在页面末尾：读者根本看不到同意入口。
    // z-[60]：低于 Radix Dialog overlay 的 z-50——模态层压住横幅由层级保证，
    // 不再依赖 DOM 顺序（历史上 E2E 的 strict-mode 冲突也源于两者同层）
    <div
      role="dialog"
      aria-live="polite"
      aria-label="Cookie 使用同意"
      data-testid="cookie-banner"
      className="fixed left-3 right-16 bottom-20 z-[80] max-h-[24vh] overflow-y-auto rounded-lg border bg-background/95 px-3 py-2 shadow-sm backdrop-blur sm:left-0 sm:right-0 sm:bottom-0 sm:max-h-none sm:rounded-none sm:border-x-0 sm:border-b-0 sm:px-6 sm:py-2 sm:shadow-[0_-4px_16px_rgba(0,0,0,0.08)]"
    >
      <div className="flex flex-wrap items-center gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="min-w-0 flex-1 text-xs leading-relaxed text-foreground/90">
          <p className="text-[13px] font-medium leading-tight">本站使用 Cookie</p>
          <p className="mt-1 hidden text-foreground/70 sm:block">
            必要 Cookie 用于保持登录与防跨站伪造；本站无广告、无第三方追踪。
            <a href="/privacy" className="ml-1 underline hover:text-foreground">
              隐私政策
            </a>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 px-2.5 text-xs sm:h-9 sm:flex-1"
            onClick={essentialOnly}
            data-testid="cookie-banner-essential"
          >
            仅必要
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 px-3 text-xs sm:h-9 sm:flex-1"
            onClick={accept}
            data-testid="cookie-banner-accept"
          >
            全部接受
          </Button>
        </div>
      </div>
    </div>
  )
}
