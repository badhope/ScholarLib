import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { LogOut, Plus, LayoutGrid } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useLogout } from '@/hooks/api/use-auth'
import { useUnreadCount } from '@/hooks/api/use-modules'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AppearanceMenu } from '@/components/appearance-menu'
import { BrandMark } from '@/components/common/brand-mark'
import { AmbientBackdrop } from '@/components/common/ambient-backdrop'
import { ModuleErrorBoundary } from '@/components/common/error-boundary'
import { PageTransition } from '@/components/common/page-transition'
import { CookieBanner } from '@/components/common/cookie-banner'
import { filterNav } from '@/lib/nav'
import {
  MOBILE_TABS,
  MOBILE_MORE,
  MOBILE_MORE_GROUP_ORDER,
  MOBILE_FAB_TO,
  type MobileTab,
} from './mobile-nav'

function MobileTabButton({
  tab,
  active,
  badge,
  onClick,
}: {
  tab: MobileTab
  active: boolean
  badge?: number
  onClick: () => void
}) {
  const Icon = tab.icon
  const showBadge = tab.to === '/notifications' && (badge ?? 0) > 0
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      data-active={active ? 'true' : 'false'}
      className={cn(
        'mobile-tab flex min-h-[44px] flex-col items-center justify-center gap-0.5 text-xs',
        active ? 'text-primary' : 'text-muted-foreground',
      )}
    >
      <span className="relative">
        <Icon className="h-5 w-5" />
        {showBadge && (
          <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-destructive" />
        )}
      </span>
      <span>{tab.label}</span>
    </button>
  )
}

export function MobileAppShell() {
  const { isAuthenticated, isAdmin, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const logoutMut = useLogout()
  const { data: unread } = useUnreadCount({ enabled: isAuthenticated })

  const moreItems = filterNav(MOBILE_MORE, {
    isAuthenticated,
    isAdmin,
    roles: user?.roles ?? [],
  })

  // 认证页（登录/注册/找回密码/验证邮箱）不展示底部 Tab 栏与 FAB
  const isAuthPage = [
    '/login',
    '/register',
    '/forgot-password',
    '/reset-password',
    '/verify-email',
  ].some((p) => location.pathname.startsWith(p))
  const showChrome = !isAuthPage

  // 首页是期刊门面 Hero，自带报头/导航/页脚：不套 MobileAppShell 的 h-14 头部，
  // 但必须渲染底部 4 Tab（任务要求首页也能切 Tab）。
  const isHome = location.pathname === '/'

  // 资源详情页自带底部固定操作栏（z-40），会盖住 Tab 栏
  const hasOwnBottomBar = /^\/catalog\/\d+/.test(location.pathname)
  // 沉浸阅读：Tab 栏随滚动方向隐藏
  const immersive = /^\/reader\//.test(location.pathname)
  const [barHidden, setBarHidden] = useState(false)

  useEffect(() => {
    if (!immersive) {
      setBarHidden(false)
      return
    }
    let lastY = 0
    const onScroll = (e: Event) => {
      const el = e.target as HTMLElement | Document
      const y =
        el instanceof HTMLElement && el !== document.documentElement
          ? el.scrollTop
          : window.scrollY
      const dy = y - lastY
      if (y < 48) setBarHidden(false)
      else if (dy > 14) setBarHidden(true)
      else if (dy < -14) setBarHidden(false)
      lastY = y
    }
    window.addEventListener('scroll', onScroll, { passive: true, capture: true })
    return () => {
      window.removeEventListener('scroll', onScroll, { capture: true })
    }
  }, [immersive])

  // FAB 只在「浏览类」页面出现
  const FAB_ROUTES = ['/dashboard', '/catalog', '/library', '/follows', '/recommendations', '/notifications', '/forum']
  const canIngest =
    isAdmin ||
    ['author', 'editor', 'section_editor'].some((r) => (user?.roles ?? []).includes(r))
  const showFab =
    showChrome &&
    isAuthenticated &&
    canIngest &&
    !hasOwnBottomBar &&
    !isHome &&
    FAB_ROUTES.some((p) => location.pathname === p || location.pathname.startsWith(p + '/'))

  // 认证页：完全裸奔，不套任何壳
  if (isAuthPage) {
    return (
      <div className="min-h-screen bg-background">
        <CookieBanner />
        <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
          <PageTransition>
            <Outlet />
          </PageTransition>
        </ModuleErrorBoundary>
      </div>
    )
  }

  const isActive = (to: string) =>
    location.pathname === to || location.pathname.startsWith(to + '/')

  const onLogout = async () => {
    try {
      await logoutMut.mutateAsync()
      toast.success('已退出登录')
    } catch {
      // backend 失败也清本地
    }
    void navigate({ to: '/login' })
  }

  const go = (to: string) => {
    void navigate({ to })
  }

  // 底部 4 Tab 栏：首页与所有非认证页都渲染
  // z-50 确保压在首页自己的 sticky header(z-40) 与 back-to-top 按钮之上
  const bottomTab = showChrome && !hasOwnBottomBar && (
    <nav
      className={cn(
        'fixed inset-x-0 bottom-0 z-50 grid h-16 grid-cols-5 items-stretch border-t bg-background backdrop-blur pb-[env(safe-area-inset-bottom)]',
        'transition-transform duration-300 ease-out',
        immersive && barHidden ? 'translate-y-full' : 'translate-y-0',
      )}
      aria-label="主导航"
    >
      {MOBILE_TABS.map((tab) => (
        <MobileTabButton
          key={tab.to}
          tab={tab}
          active={isActive(tab.to)}
          badge={unread?.unread}
          onClick={() => go(tab.to)}
        />
      ))}
    </nav>
  )

  // 首页：不套 MobileAppShell 头部，只渲染内容 + 底部 Tab
  if (isHome) {
    return (
      <div className="flex min-h-screen flex-col bg-background">
        <AmbientBackdrop />
        <main className="relative z-10 flex-1 pb-[calc(8rem+env(safe-area-inset-bottom))]">
          <CookieBanner />
          <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
            <PageTransition>
              <Outlet />
            </PageTransition>
          </ModuleErrorBoundary>
        </main>
        {bottomTab}
      </div>
    )
  }

  // 普通内页：header + 内容 + 底部 Tab
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AmbientBackdrop />
      {/* 紧凑头部：logo + 主题切换 + 显式「功能」入口 */}
      <header className="app-header-rule sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-background/95 px-4 backdrop-blur relative supports-[backdrop-filter]:bg-background/60">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <BrandMark className="h-5 w-5 shrink-0" />
          <span>Rubbish</span>
        </Link>
        <div className="flex items-center gap-1.5">
          <AppearanceMenu />
          {/* 次级入口不再藏在「⋯」里：用带文字的胶囊按钮，第一眼就知道能展开 */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-9 gap-1.5 rounded-full px-3"
                aria-label="打开功能菜单"
              >
                <LayoutGrid className="h-4 w-4" />
                <span className="text-xs font-medium">功能</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-[70vh] w-56 overflow-y-auto">
              {isAuthenticated && user ? (
                <>
                  <div className="flex items-center gap-2 px-2 py-1.5">
                    <Avatar className="h-7 w-7">
                      <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{user.username}</div>
                    </div>
                  </div>
                  <DropdownMenuSeparator />
                </>
              ) : (
                <>
                  <DropdownMenuLabel>未登录</DropdownMenuLabel>
                  <DropdownMenuItem asChild>
                    <Link to="/login">登录</Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/register">注册</Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              {MOBILE_MORE_GROUP_ORDER.map((group) => {
                const items = moreItems.filter((i) => i.group === group)
                if (items.length === 0) return null
                return (
                  <div key={group}>
                    <DropdownMenuLabel className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {group}
                    </DropdownMenuLabel>
                    {items.map((item) => {
                      const Icon = item.icon
                      return (
                        <DropdownMenuItem key={item.to} asChild>
                          <Link to={item.to} className="flex items-center gap-2">
                            <Icon className="h-4 w-4 text-muted-foreground" />
                            <span>{item.label}</span>
                          </Link>
                        </DropdownMenuItem>
                      )
                    })}
                  </div>
                )
              })}
              {isAuthenticated && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={onLogout} className="text-destructive">
                    <LogOut className="h-4 w-4" />
                    <span>退出登录</span>
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* 内容区：底部留白避开固定 Tab 栏 */}
      <main
        className={cn(
          'relative z-10 flex-1 overflow-y-auto',
          hasOwnBottomBar
            ? 'pb-[calc(8.5rem+env(safe-area-inset-bottom))]'
            : immersive
              ? 'pb-[calc(4.5rem+env(safe-area-inset-bottom))]'
              : showChrome
                ? 'pb-[calc(8rem+env(safe-area-inset-bottom))]'
                : 'pb-4',
        )}
      >
        <div className="mx-auto w-full max-w-screen-sm px-4 py-4">
          <CookieBanner />
          <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
            <PageTransition>
              <Outlet />
            </PageTransition>
          </ModuleErrorBoundary>
        </div>
      </main>

      {/* FAB：右下角，悬浮在 Tab 栏上方 */}
      {showFab && (
        <Button
          aria-label="导入"
          onClick={() => go(MOBILE_FAB_TO)}
          className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-4 z-40 h-14 w-14 rounded-full shadow-lg"
          size="icon"
        >
          <Plus className="h-6 w-6" />
        </Button>
      )}

      {bottomTab}
    </div>
  )
}
