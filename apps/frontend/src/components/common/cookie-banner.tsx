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
    // 位置：手机端走正常文档流（在页面标题上方占一行，不覆盖任何内容）；
    // 原来是 fixed 贴顶/贴底，实测会把页面 H1、列表首条、文章底部 CTA 盖住。
    // 桌面端仍固定左下角——原来贴右下会盖住文章右侧的「操作」面板。
    // z-40：低于 Radix Dialog overlay 的 z-50——模态层压住横幅由层级保证，
    // 不再依赖 DOM 顺序（历史上 E2E 的 strict-mode 冲突也源于两者同层）
    <div
      role="dialog"
      aria-live="polite"
      aria-label="Cookie 使用同意"
      data-testid="cookie-banner"
      className="relative z-40 mx-4 mt-3 max-h-[30vh] overflow-y-auto rounded-xl border bg-background/95 p-3 shadow-lg backdrop-blur sm:fixed sm:bottom-5 sm:left-5 sm:right-auto sm:top-auto sm:m-0 sm:w-[20rem] sm:p-4"
    >
      <div className="flex flex-col gap-2.5 sm:gap-3">
        <div className="text-xs leading-relaxed text-foreground/90">
          <p className="text-[13px] font-medium">本站使用 Cookie</p>
          <p className="mt-1 hidden text-foreground/70 sm:block">
            必要 Cookie 用于保持登录与防跨站伪造；本站无广告、无第三方追踪。
            <a href="/privacy" className="ml-1 underline hover:text-foreground">
              隐私政策
            </a>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={essentialOnly}
            data-testid="cookie-banner-essential"
          >
            仅必要
          </Button>
          <Button
            type="button"
            size="sm"
            className="flex-1"
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
