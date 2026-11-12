import { useEffect, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { AxiosError } from 'axios'
import { toast } from 'sonner'
import { useRegister } from '@/hooks/api/use-auth'
import { useCapabilities } from '@/hooks/use-capabilities'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export const Route = createFileRoute('/register')({
  component: RegisterPage,
})

export function RegisterPage() {
  const navigate = useNavigate()
  const registerMut = useRegister()
  const capabilities = useCapabilities()
  const emailDelivery = capabilities.data?.email_delivery ?? false
  const captchaRequired = capabilities.data?.captcha_required_for_registration ?? true
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [captcha, setCaptcha] = useState<{ token: string; question: string } | null>(null)
  const [captchaAnswer, setCaptchaAnswer] = useState('')

  useEffect(() => {
    if (capabilities.isLoading || !captchaRequired) {
      setCaptcha(null)
      return
    }
    let cancelled = false
    void api
      .get<{ token: string; question: string }>('/auth/captcha')
      .then((r) => {
        if (!cancelled) setCaptcha(r.data)
      })
      .catch(() => {
        if (!cancelled) toast.error('验证码加载失败，请刷新页面重试')
      })
    return () => {
      cancelled = true
    }
  }, [capabilities.isLoading, captchaRequired])

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) {
      toast.error('两次输入的密码不一致')
      return
    }
    if (password.length < 8) {
      toast.error('密码至少 8 位')
      return
    }
    try {
      if (captchaRequired) {
        if (!captcha) {
          toast.error('验证码还没加载好，请稍等或刷新页面')
          return
        }
        if (!captchaAnswer.trim()) {
          toast.error('请先回答验证码')
          return
        }
      }
      const result = await registerMut.mutateAsync({
        email,
        username,
        password,
        captcha_token: captchaRequired ? captcha?.token : undefined,
        captcha_answer: captchaRequired ? captchaAnswer.trim() : undefined,
      })
      if (!('access_token' in result) || !result.access_token) {
        // 注册端点对成功与冲突返回同一响应（防枚举），且注册响应不再建立会话：
        // 有邮件投递 → 去验证页；否则 → 去登录页用刚设置的密码登录。
        if (emailDelivery) {
          toast.success('注册成功，请查收邮件完成验证')
          void navigate({ to: '/verify-email', search: { email } })
        } else {
          toast.success('注册请求已受理，请使用刚设置的密码登录')
          void navigate({ to: '/login' })
        }
        return
      }
      // 兼容旧后端（滚动发布期间仍可能返回 TokenResponse）。
      // 后端默认 console 邮件后端：验证链接只写进服务器日志，不会真的发信。
      // 只有 SMTP 真的接通时才引导用户去收件箱，否则直接进工作台。
      if (emailDelivery) {
        toast.success('注册成功，请查收邮件完成验证')
        void navigate({ to: '/verify-email', search: { email } })
      } else {
        toast.success('注册成功，已自动登录')
        void navigate({ to: '/dashboard' })
      }
    } catch (err) {
      const msg =
        err instanceof AxiosError
          ? (err.response?.data as { detail?: string })?.detail ?? '注册失败'
          : '注册失败'
      toast.error(msg)
    }
  }

  return (
    <div className="mx-auto flex min-h-[80vh] max-w-md items-center">
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-2xl">注册</CardTitle>
          <CardDescription>
          创建 Rubbish 账号，即可投稿、审稿与在线阅读。
          {capabilities.isFetched && !emailDelivery && (
            <span className="mt-2 block text-xs text-muted-foreground">
              当前站点未开通邮件服务：注册后可直接用邮箱和密码登录，邮箱验证与找回密码暂不可用，
              忘记密码请联系编辑部。
            </span>
          )}
        </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                minLength={3}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">确认密码</Label>
              <Input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="captcha">验证码：{captcha?.question ?? '加载中…'}</Label>
              <Input
                id="captcha"
                inputMode="numeric"
                autoComplete="off"
                value={captchaAnswer}
                onChange={(e) => setCaptchaAnswer(e.target.value)}
                placeholder="填计算结果，防批量注册"
              />
              <p className="text-xs text-muted-foreground">自建算术题，不接第三方验证码，不产生费用。</p>
            </div>
            <Button type="submit" className="w-full" disabled={registerMut.isPending}>
              {registerMut.isPending ? '注册中…' : '注册'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            已有账号？{' '}
            <Link to="/login" className="text-primary hover:underline">
              登录
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
