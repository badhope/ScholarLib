import { createRootRouteWithContext } from '@tanstack/react-router'
import { QueryClient } from '@tanstack/react-query'
import { TanStackRouterDevtools } from '@tanstack/router-devtools'
import { AppShell } from '@/components/layout/AppShell'
import { MobileAppShell } from '@/components/layout/MobileAppShell'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { useAuthStore, type AuthUser } from '@/lib/auth'
import { api } from '@/lib/api'
import { Toaster } from '@/components/ui/sonner'
import { NotFoundPage } from '@/components/common/not-found-page'
import { FeedbackLauncher } from '@/components/common/feedback-launcher'
import type { UserResponse } from '@/lib/types'

interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  beforeLoad: async ({ context }) => {
    // 刷新页面后 token 还在但 user 为 null：拉一次 /auth/me 回填 store，
    // 否则 admin 路由守卫会误判跳 /login，AppShell 用户菜单也会消失
    const { token, user } = useAuthStore.getState()
    if (token && !user) {
      try {
        const res = await context.queryClient.fetchQuery<UserResponse>({
          queryKey: ['auth', 'me'],
          queryFn: async () => (await api.get<UserResponse>('/auth/me')).data,
          staleTime: 60_000,
        })
        useAuthStore.getState().setUser({
          id: res.id,
          username: res.username,
          is_admin: res.is_admin,
          roles: res.roles ?? [],
        } satisfies AuthUser)
      } catch (err) {
        // 只有后端明确说「你这个 token 不认」才登出。网络抖动、
        // 5xx 这类瞬时故障不能把用户踢下线——否则刷新一次页面就掉登录。
        const status = (err as { response?: { status?: number } }).response
          ?.status
        if (status === 401 || status === 403) {
          useAuthStore.getState().logout()
        }
      }
    }
  },
  component: RootLayout,
  notFoundComponent: NotFoundPage,
})

function RootLayout() {
  // Playwright 跑 E2E 时 navigator.webdriver === true；
  // 这种情况下隐藏 Router Devtools 浮层，避免它拦截页面右下角按钮的点击
  const showDevtools = import.meta.env.DEV && !navigator.webdriver
  // 移动端用独立的 MobileAppShell（底部 Tab 栏 + FAB + 底部抽屉），
  // 与桌面侧边栏是完全不同的设计，运行时按视口切换，共享同一套路由。
  const isMobile = useIsMobile()
  return (
    <>
      {isMobile ? <MobileAppShell /> : <AppShell />}
      <FeedbackLauncher />
      <Toaster position="top-right" richColors closeButton />
      {showDevtools && <TanStackRouterDevtools />}
    </>
  )
}
