import { useEffect, useState, type ReactNode } from 'react'
import { Link, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { LogOut, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useLogout } from '@/hooks/api/use-auth'
import { useUnreadCount } from '@/hooks/api/use-modules'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { ThemeToggle } from '@/components/theme-toggle'
import { BrandMark } from '@/components/common/brand-mark'
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

// 底部抽屉：自带遮罩、ESC 关闭、打开时锁 body 滚动。移动原生交互，不依赖居中 Dialog。
function BottomSheet({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="更多">
      <div className="absolute inset-0 bg-black/50" aria-hidden="true" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl border-t bg-background p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] animate-in slide-in-from-bottom duration-200">
        {children}
      </div>
    </div>
  )
}

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
      className={cn(
        'flex min-h-[44px] flex-col items-center justify-center gap-0.5 text-xs',
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
  const [sheetOpen, setSheetOpen] = useState(false)
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

  // 认证页（登录/注册/找回密码/验证邮箱）不展示底部 Tab 栏与 FAB，避免未登录时露出需鉴权入口
  const isAuthPage = [
    '/login',
    '/register',
    '/forgot-password',
    '/reset-password',
    '/verify-email',
  ].some((p) => location.pathname.startsWith(p))
  const showChrome = !isAuthPage

  // 路由切换后关闭抽屉，避免点击导航后抽屉仍遮挡内容
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSheetOpen(false)
  }, [location.pathname])

  // 资源详情页自带底部固定操作栏（z-40），会盖住 Tab 栏；这类页面不再
  // 叠加中心 FAB，否则 FAB 悬在操作栏上方遮挡内容。
  // 阅读页 0.9 起取消了自己的操作栏（操作收进标题栏「⋯」），只靠 Tab 栏。
  const hasOwnBottomBar = /^\/catalog\/\d+/.test(location.pathname)
  // 沉浸阅读：Tab 栏随滚动方向隐藏，把整屏还给正文；上滑即回来。
  const immersive = /^\/reader\//.test(location.pathname)
  const [barHidden, setBarHidden] = useState(false)

  // 沉浸阅读：向下滚动藏起 Tab 栏，向上滚动或回到顶部时露出。
  // 阅读页可能是 window 滚动（富文本），也可能是内部容器滚动（PDF），
  // 两个源都要监听，否则其中一种模式下栏不会动。
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
    window.addEventListener('scroll', onScroll, { passive: true })
    const inner = document.querySelector('[data-reader-scroll]')
    inner?.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      inner?.removeEventListener('scroll', onScroll)
    }
  }, [immersive])


  // FAB 只在「浏览类」页面出现。表单页（设置、账号安全、后台、投稿）
  // 的输入框经常落在屏幕中下部，悬浮按钮正好压在上面——实测在
  // /account/security 的「当前密码」输入框中心点能命中 FAB。
  // 导入入口在「我的」抽屉里也有一份，收起 FAB 不会断掉任何路径。
  const FAB_ROUTES = ['/dashboard', '/catalog', '/library', '/follows', '/recommendations', '/notifications']
  // 导入（元数据抓取）是作者/编辑部的投稿辅助工具；纯读者看不到入口，
  // 避免点进去是一个与自身角色无关的表单。
  const canIngest =
    isAdmin ||
    ['author', 'editor', 'section_editor'].some((r) => (user?.roles ?? []).includes(r))
  const showFab =
    showChrome &&
    isAuthenticated &&
    canIngest &&
    !hasOwnBottomBar &&
    FAB_ROUTES.some((p) => location.pathname === p || location.pathname.startsWith(p + '/'))

  // 期刊门面模式：首页走独立的全宽 editorial 版式，不套移动端 Tab 壳（与桌面端一致）。
  // 提前返回必须放在全部 hooks 之后（rules of hooks）。
  const AUTH_FACADE = ['/login', '/register', '/forgot-password', '/reset-password', '/verify-email']
  if (location.pathname === '/' || AUTH_FACADE.includes(location.pathname)) {
    return (
      <div className="min-h-screen bg-background">
        <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
          <PageTransition>
            <Outlet />
          </PageTransition>
        </ModuleErrorBoundary>
        <CookieBanner />
      </div>
    )
  }

  const isActive = (to: string) =>
    to !== '/__more' && (location.pathname === to || location.pathname.startsWith(to + '/'))

  const onLogout = async () => {
    try {
      await logoutMut.mutateAsync()
      toast.success('已退出登录')
    } catch {
      // backend 失败也清本地
    }
    setSheetOpen(false)
    void navigate({ to: '/login' })
  }

  const go = (to: string) => {
    setSheetOpen(false)
    void navigate({ to })
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* 紧凑头部：仅 logo + 主题切换（移动端不堆功能） */}
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <BrandMark className="h-5 w-5 shrink-0" />
          <span>Rubbish</span>
        </Link>
        <ThemeToggle />
      </header>

      {/* 内容区：移动端单列、限宽、底部留白避开底部固定栏。
          文章详情/阅读页自带一条操作栏（在线阅读/下载/登录同步进度）叠在
          Tab 栏之上，两层加起来约 7.5rem；只留 pb-24 的话最后一段正文会
          被压在操作栏底下（390×844 实测：摘要卡末行、参考文献标题都被挡）。 */}
      <main
        className={cn(
          'flex-1 overflow-y-auto',
          hasOwnBottomBar
            ? 'pb-[calc(8.5rem+env(safe-area-inset-bottom))]'
            : immersive
              ? 'pb-[calc(4.5rem+env(safe-area-inset-bottom))]'
              : showChrome
                ? 'pb-24'
                : 'pb-4',
        )}
      >
        <div className="mx-auto w-full max-w-screen-sm px-4 py-4">
          {/* 页面级错误边界：崩溃时底部 Tab 栏仍可用，换页自动复位 */}
          <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
            <PageTransition>
              <Outlet />
            </PageTransition>
          </ModuleErrorBoundary>
        </div>
      </main>

      {/* 悬浮按钮：仅登录用户、且在浏览类页面可见，跳导入（创建类操作）。
          放在右下角而不是水平居中：居中时它正好压住信息流卡片的标题与
          作者行（如工作台「为你推荐」第一条），读起来像排版坏了。 */}
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

      {/* 底部 Tab 栏：4 等分，中心 FAB 浮于其上（仅非认证页） */}
      {showChrome && (
        <nav
          className={cn(
            'fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-4 items-stretch border-t bg-background/95 backdrop-blur pb-[env(safe-area-inset-bottom)]',
            'transition-transform duration-300 ease-out',
            immersive && barHidden ? 'translate-y-full' : 'translate-y-0',
          )}
          aria-label="主导航"
        >
          {MOBILE_TABS.map((tab) => (
            <MobileTabButton
              key={tab.to}
              tab={tab}
              active={tab.openSheet ? sheetOpen : isActive(tab.to)}
              badge={unread?.unread}
              onClick={() => (tab.openSheet ? setSheetOpen(true) : go(tab.to))}
            />
          ))}
        </nav>
      )}

      {/* "更多"底部抽屉 */}
      <BottomSheet open={sheetOpen} onClose={() => setSheetOpen(false)}>
        {isAuthenticated && user ? (
          <>
            <div className="mb-3 flex items-center gap-3 border-b pb-3">
              <Avatar className="h-10 w-10">
                <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{user.username}</div>
                <div className="text-xs text-muted-foreground">已登录</div>
              </div>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label="关闭"
                className="text-muted-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex flex-col">
              {MOBILE_MORE_GROUP_ORDER.map((group) => {
                const items = moreItems.filter((i) => i.group === group)
                if (items.length === 0) return null
                return (
                  <div key={group} className="mt-2 first:mt-0">
                    <p className="px-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground">
                      {group}
                    </p>
                    {items.map((item) => {
                      const Icon = item.icon
                      return (
                        <button
                          key={item.to}
                          type="button"
                          onClick={() => go(item.to)}
                          className="flex min-h-[44px] w-full items-center gap-3 rounded-md px-2 text-left text-sm hover:bg-accent"
                        >
                          <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
                          <span>{item.label}</span>
                        </button>
                      )
                    })}
                  </div>
                )
              })}
              <button
                type="button"
                onClick={onLogout}
                className="mt-2 flex min-h-[48px] w-full items-center gap-3 rounded-md border-t px-2 pt-3 text-left text-sm text-destructive hover:bg-destructive/10"
              >
                <LogOut className="h-5 w-5 shrink-0" />
                <span>退出登录</span>
              </button>
            </div>
          </>
        ) : (
          <div className="flex flex-col gap-3 py-2">
            <Button asChild className="min-h-[44px]">
              <Link to="/login" onClick={() => setSheetOpen(false)}>
                登录
              </Link>
            </Button>
            <Button asChild variant="outline" className="min-h-[44px]">
              <Link to="/register" onClick={() => setSheetOpen(false)}>
                注册
              </Link>
            </Button>
          </div>
        )}
      </BottomSheet>
    </div>
  )
}
