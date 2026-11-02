import { useState } from 'react'
import { createFileRoute, Link, useNavigate, useSearch } from '@tanstack/react-router'
import { AxiosError } from 'axios'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError, safeInternalPath } from '@/lib/utils'
import { isTwoFactorRequired } from '@/lib/types'
import { useLogin, useRequestEmailCode, useVerifyEmailCode, useTwoFactorLogin } from '@/hooks/api/use-auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

type LoginMode = 'password' | 'email-code'

function LoginPage() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as { redirect?: string }
  const loginMut = useLogin()
  const twoFactorMut = useTwoFactorLogin()
  const sendCodeMut = useRequestEmailCode()
  const verifyCodeMut = useVerifyEmailCode()
  const [mode, setMode] = useState<LoginMode>('password')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // 邮箱验证码登录状态
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [resendIn, setResendIn] = useState(0)

  // 非 null = 凭据已通过，等待第二因子（TOTP / 恢复码）
  const [pendingToken, setPendingToken] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')

  const afterLogin = () => {
    toast.success('登录成功')
    void navigate({ to: safeInternalPath(search.redirect) })
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const result = await loginMut.mutateAsync({ username, password })
      if (isTwoFactorRequired(result)) {
        setPendingToken(result.pending_token)
        setTotpCode('')
        return
      }
      afterLogin()
    } catch (err) {
      toast.error(extractError(err, '登录失败，请检查用户名与密码'))
    }
  }

  // 发送验证码 → 倒计时 60 秒（与后端节流窗口一致）
  const onSendCode = async () => {
    if (!email.trim()) {
      toast.error('请先输入注册邮箱')
      return
    }
    try {
      await sendCodeMut.mutateAsync(email.trim())
      setCodeSent(true)
      setResendIn(60)
      const timer = window.setInterval(() => {
        setResendIn((s) => {
          if (s <= 1) {
            window.clearInterval(timer)
            return 0
          }
          return s - 1
        })
      }, 1000)
      toast.success('验证码已发送', { description: '请查收邮箱（10 分钟内有效，注意垃圾邮件箱）' })
    } catch (err) {
      toast.error(extractError(err, '发送失败，请稍后再试'))
    }
  }

  const onVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const data = await verifyCodeMut.mutateAsync({ email: email.trim(), code: code.trim() })
      if (isTwoFactorRequired(data)) {
        setPendingToken(data.pending_token)
        setTotpCode('')
        setMode('password')
        return
      }
      afterLogin()
    } catch (err) {
      const status = err instanceof AxiosError ? err.response?.status : undefined
      if (status === 401) {
        toast.error('验证码无效或已过期，请重新获取')
        return
      }
      toast.error(extractError(err, '登录失败，请稍后再试'))
    }
  }

  const onSubmitTwoFactor = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pendingToken) return
    try {
      await twoFactorMut.mutateAsync({
        pending_token: pendingToken,
        code: totpCode,
      })
      afterLogin()
    } catch (err) {
      const status =
        err instanceof AxiosError ? err.response?.status : undefined
      if (status === 401) {
        const detail =
          err instanceof AxiosError
            ? (err.response?.data as { detail?: string })?.detail
            : undefined
        if (detail?.includes('session')) {
          toast.error('验证会话已过期，请重新登录')
          setPendingToken(null)
          return
        }
        toast.error('验证码错误，请重试')
        return
      }
      toast.error('验证失败，请重试')
    }
  }

  // OIDC SSO redirect: open /api/auth/oidc/{provider}/login directly.
  // The provider is checked against an allowlist so a polluted env var
  // cannot redirect the user to an attacker-controlled IdP.
  const OIDC_PROVIDERS = ['google', 'github', 'keycloak', 'generic'] as const
  const onOidcLogin = () => {
    const provider = import.meta.env.VITE_OIDC_PROVIDER ?? 'google'
    if (!OIDC_PROVIDERS.includes(provider as (typeof OIDC_PROVIDERS)[number])) {
      toast.error('OIDC provider 配置无效')
      return
    }
    window.location.href = `${api.defaults.baseURL}/auth/oidc/${provider}/login`
  }

  const oidcEnabled = import.meta.env.VITE_OIDC_ENABLED === 'true'

  // --- 第二步：两步验证 ---
  if (pendingToken) {
    return (
      <div className="mx-auto flex min-h-[80vh] max-w-md items-center">
        <Card className="w-full">
          <CardHeader>
            <CardTitle className="text-2xl">两步验证</CardTitle>
            <CardDescription>
              输入身份验证器 App 中的 6 位验证码，或一个未使用的恢复码。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmitTwoFactor} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="totp-code">验证码</Label>
                <Input
                  id="totp-code"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  placeholder="123456 或 xxxx-xxxx-xxxx"
                  autoFocus
                  required
                  minLength={6}
                />
              </div>
              <Button
                type="submit"
                className="w-full"
                disabled={twoFactorMut.isPending}
                data-testid="confirm-2fa"
              >
                {twoFactorMut.isPending ? '验证中…' : '验证并登录'}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="w-full"
                onClick={() => setPendingToken(null)}
              >
                返回重新登录
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-[80vh] max-w-md items-center">
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-2xl">登录</CardTitle>
          <CardDescription>选择一种方式登录 Rubbish。</CardDescription>
        </CardHeader>
        <CardContent>
          {/* 登录方式切换：验证码登录给记不住密码的读者；密码登录保留给
              老用户与密码管理器用户。 */}
          <div
            className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-muted p-1"
            role="tablist"
            aria-label="登录方式"
          >
            {(
              [
                { key: 'password', label: '密码登录' },
                { key: 'email-code', label: '邮箱验证码' },
              ] as const
            ).map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={mode === t.key}
                onClick={() => setMode(t.key)}
                className={cn(
                  'rounded-md py-1.5 text-sm font-medium transition-colors',
                  mode === t.key
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {mode === 'password' ? (
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username">用户名或邮箱</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">密码</Label>
                  <Link
                    to="/forgot-password"
                    className="text-xs text-muted-foreground hover:text-primary"
                  >
                    忘记密码？
                  </Link>
                </div>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
              <Button type="submit" className="w-full" disabled={loginMut.isPending}>
                {loginMut.isPending ? '登录中…' : '登录'}
              </Button>
            </form>
          ) : (
            <form onSubmit={onVerifyCode} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email-code-address">注册邮箱</Label>
                <div className="flex gap-2">
                  <Input
                    id="email-code-address"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={onSendCode}
                    disabled={sendCodeMut.isPending || resendIn > 0 || !email.trim()}
                    className="shrink-0"
                  >
                    {resendIn > 0
                      ? `${resendIn}s 后重发`
                      : sendCodeMut.isPending
                        ? '发送中…'
                        : codeSent
                          ? '重新发送'
                          : '获取验证码'}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="email-code-value">6 位验证码</Label>
                <Input
                  id="email-code-value"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  maxLength={6}
                  required
                />
              </div>
              <Button type="submit" className="w-full" disabled={!codeSent || code.length < 6}>
                {codeSent ? '验证并登录' : '请先获取验证码'}
              </Button>
              <p className="text-xs text-muted-foreground">
                没收到？检查垃圾邮件箱；60 秒后可重新发送。编辑部不会向你索要验证码。
              </p>
            </form>
          )}

          {oidcEnabled && (
            <>
              <div className="my-4 flex items-center gap-2 text-xs text-muted-foreground">
                <Separator className="flex-1" />
                或
                <Separator className="flex-1" />
              </div>
              <Button variant="outline" className="w-full" onClick={onOidcLogin}>
                使用 SSO 登录
              </Button>
            </>
          )}

          <p className="mt-4 text-center text-sm text-muted-foreground">
            没有账号？{' '}
            <Link to="/register" className="text-primary hover:underline">
              注册
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
