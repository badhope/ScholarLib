import { useState } from 'react'
import { createFileRoute, Link, redirect, useNavigate } from '@tanstack/react-router'
import { getAuthState, useAuthStore } from '@/lib/auth'
import { useMe, useResendVerification } from '@/hooks/api/use-auth'
import { TwoFactorSection } from '@/components/settings/two-factor-section'
import { ChangePasswordCard } from '@/components/settings/change-password-card'
import { ProfileDetailsCard } from '@/components/settings/profile-details-card'
import { NotificationPrefsCard } from '@/components/settings/notification-prefs-card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/common/page-header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from 'sonner'

export const Route = createFileRoute('/settings')({
  validateSearch: (search: Record<string, unknown>): { tab?: 'profile' | 'security' | 'notifications' } => {
    const tab =
      search.tab === 'security'
        ? 'security'
        : search.tab === 'notifications'
          ? 'notifications'
          : search.tab === 'profile'
            ? 'profile'
            : undefined
    return tab ? { tab } : {}
  },
  // 与其他需要登录的页面保持一致：访客进来直接弹回登录页，
  // 而不是渲染一个点什么都 401 的空壳。
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) {
      throw redirect({ to: '/login', search: { redirect: '/settings' } })
    }
  },
  component: SettingsPage,
})

const ROLE_LABELS: Record<string, string> = {
  reader: '读者',
  author: '作者',
  reviewer: '审稿人',
  editor: '编辑',
  senior_reviewer: '资深审稿人',
  section_editor: '栏目编辑',
}

function roleSummary(isAdmin?: boolean, roles?: string[]) {
  const named = (roles ?? []).map((r) => ROLE_LABELS[r] ?? r)
  if (isAdmin) named.unshift('管理员')
  return named.length ? named.join('、') : '普通用户'
}

function ProfileCard() {
  const cached = useAuthStore((s) => s.user)
  const { data: me } = useMe()
  // 以 /auth/me 为准：登录响应里通常没有 is_email_verified
  const user = (me ?? cached) as typeof cached
  const resend = useResendVerification()
  return (
    <Card>
      <CardHeader>
        <CardTitle>资料</CardTitle>
        <CardDescription>当前登录账号的信息。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">展示名</span>
          <span className="truncate text-right font-medium">
            {user?.display_name ?? '未填写'}
          </span>
        </div>
        {user?.affiliation ? (
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">单位</span>
            <span className="text-right font-medium">{user.affiliation}</span>
          </div>
        ) : null}
        {user?.academic_title ? (
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">职称 / 身份</span>
            <span className="text-right font-medium">{user.academic_title}</span>
          </div>
        ) : null}
        <div className="flex justify-between">
          <span className="text-muted-foreground">用户名</span>
          <span className="font-medium">{user?.username ?? '—'}</span>
        </div>
        {/* 邮箱验证：注册后要确认邮箱所有权（点邮件里的链接，或用邮箱验证码
            登录一次）。没验证不影响阅读与投稿，但会影响找回密码与作者页展示，
            所以这里常驻一个明确的状态与一键重发。 */}
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">邮箱</span>
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate font-medium">{user?.email ?? '—'}</span>
            <Badge variant={user?.is_email_verified ? 'default' : 'outline'}>
              {user?.is_email_verified ? '已验证' : '未验证'}
            </Badge>
          </span>
        </div>
        {!user?.is_email_verified && user?.email && (
          <div className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
            <p>
              验证方式有两种：点开注册邮件里的链接；或者到登录页用「邮箱验证码」登录一次。
              两种都算证明你拥有这个邮箱。
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              disabled={resend.isPending}
              onClick={() =>
                resend.mutate(
                  { email: user.email as string },
                  {
                    onSuccess: () => toast.success('验证邮件已重新发送，请查收（含垃圾箱）'),
                    onError: () => toast.error('发送失败，请稍后再试'),
                  },
                )
              }
            >
              {resend.isPending ? '发送中…' : '重发验证邮件'}
            </Button>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">角色</span>
          <span className="text-right font-medium">{roleSummary(user?.is_admin, user?.roles)}</span>
        </div>
        <p className="pt-2 text-xs text-muted-foreground">
          头像与等级展示见{' '}
          <Link to="/profile" className="underline">
            个人中心
          </Link>
          。
        </p>
      </CardContent>
    </Card>
  )
}

function profileKey(user: ReturnType<typeof useMe>['data']) {
  if (!user) return 'profile-empty'
  return [
    user.id,
    user.display_name,
    user.real_name,
    user.affiliation,
    user.department,
    user.academic_title,
    user.location,
    user.research_interests,
    user.website,
    user.google_scholar,
    user.bio,
  ].join('|')
}

function SettingsPage() {
  const search = Route.useSearch()
  const navigate = useNavigate()
  const { data: me } = useMe()
  // 初始 tab 来自 ?tab=security（旧 /account/security 链接转跳进来时直达安全页）
  const [tab, setTab] = useState<'profile' | 'security' | 'notifications'>(search.tab ?? 'profile')

  const onTabChange = (v: string) => {
    setTab(v as 'profile' | 'security' | 'notifications')
    void navigate({
      to: '/settings',
      search: { tab: v as 'profile' | 'security' | 'notifications' },
      replace: true,
    })
  }

  return (
    <div className="w-full max-w-3xl space-y-6">
      <PageHeader
        title="账号设置"
        description="账号资料、个人简介与安全项；所有字段都可以留空，留空不会覆盖已有内容。"
      />

      <Tabs value={tab} onValueChange={onTabChange}>
        <TabsList>
          <TabsTrigger value="profile">资料</TabsTrigger>
          <TabsTrigger value="security">安全</TabsTrigger>
          <TabsTrigger value="notifications">通知</TabsTrigger>
        </TabsList>
        <TabsContent value="profile" className="mt-4 space-y-6">
          <ProfileCard />
          <ProfileDetailsCard key={profileKey(me)} initial={me} />
        </TabsContent>
        <TabsContent value="notifications" className="mt-4">
          <NotificationPrefsCard />
        </TabsContent>
        <TabsContent value="security" className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <TwoFactorSection />
          <ChangePasswordCard />
        </TabsContent>
      </Tabs>
    </div>
  )
}
