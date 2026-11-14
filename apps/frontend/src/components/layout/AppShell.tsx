import { Fragment, useEffect, useState, type FormEvent } from 'react'
import { Link, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import {
  ShieldAlert,
  Activity,
  Bell,
  BookOpen,
  Building2,
  CalendarDays,
  ChevronLeft,
  ClipboardCheck,
  Coffee,
  Gavel,
  Heart,
  Home,
  Layers,
  Library,
  Lightbulb,
  Menu,
  PenLine,
  Rocket,
  Upload,
  Scale,
  ScrollText,
  Search,
  Settings,
  ShieldCheck,
  ShoppingBag,
  User,
  Users,
  Award,
  FileSignature,
  Megaphone,
  MessagesSquare,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { OnboardingTour } from '@/components/common/onboarding-tour'
import { useAuth } from '@/hooks/use-auth'
import { useLogout } from '@/hooks/api/use-auth'
import { useUnreadCount } from '@/hooks/api/use-modules'
import { cn } from '@/lib/utils'
import { BrandMark } from '@/components/common/brand-mark'
import { AmbientBackdrop } from '@/components/common/ambient-backdrop'
import { filterNav, resolveActiveNavPath, type NavItem } from '@/lib/nav'
import { ModuleErrorBoundary } from '@/components/common/error-boundary'
import { PageTransition } from '@/components/common/page-transition'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
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
import { CookieBanner } from '@/components/common/cookie-banner'
import { PageViewTracker } from '@/components/common/page-view-tracker'
import { LanguageToggle } from '@/components/layout/language-toggle'
import { groupLabel, navLabel, text, useLang } from '@/lib/i18n'

const NAV: NavItem[] = [
  // 一级入口固定五项：首页 / 论文 / 副刊 / 讨论 / 我的。
  // 栏目、卷期、指标等期刊门面退到「期刊」二级组，不再和社区抢一级入口。
  { to: '/', label: '首页', icon: Home, group: '一级入口' },
  { to: '/papers', label: '论文', icon: BookOpen, group: '一级入口' },
  { to: '/fun', label: '副刊', icon: Coffee, group: '一级入口' },
  { to: '/forum', label: '讨论', icon: MessagesSquare, group: '一级入口' },
  { to: '/me', label: '我的', icon: User, group: '一级入口' },

  // 我的工作：只放需要登录的个人链路。
  { to: '/dashboard', label: '我的概览', icon: Home, auth: true, group: '我的工作' },
  { to: '/submissions', label: '我的提交', icon: ScrollText, auth: true, group: '我的工作' },
  { to: '/appeals', label: '作者申诉', icon: Scale, auth: true, group: '我的工作' },
  { to: '/library', label: '阅读列表', icon: Library, auth: true, group: '我的工作' },
  { to: '/follows', label: '关注与订阅', icon: Heart, auth: true, group: '我的工作' },
  { to: '/recommendations', label: '推荐', icon: Lightbulb, auth: true, group: '我的工作' },
  {
    to: '/review/assignments',
    label: '审稿工作台',
    icon: ClipboardCheck,
    auth: true,
    roles: ['reviewer', 'editor_in_chief'],
    group: '我的工作',
  },
  { to: '/ingest', label: '导入', icon: Upload, auth: true, roles: ['author', 'editor', 'section_editor', 'board_editor', 'deputy_editor', 'chief_editor', 'editor_in_chief'], group: '我的工作' },
  { to: '/notifications', label: '通知', icon: Bell, auth: true, group: '我的工作' },

  // 期刊门面：指标并入「关于本刊」的页签，规则并入「投稿指南」。
  // 这里只保留四条真正不同的去处，避免同一内容出现两个入口。
  { to: '/sections', label: '栏目', icon: Layers, group: '期刊' },
  { to: '/archive', label: '卷期归档', icon: CalendarDays, group: '期刊' },
  { to: '/about', label: '关于与指标', icon: Building2, group: '期刊' },
  { to: '/guide', label: '投稿指南', icon: PenLine, group: '期刊' },

  // admin 组：用户 → 角色申请 → 期刊四件套（卷/期/信息/设置），审计日志垫底
  { to: '/admin', label: '站点总览', icon: Gavel, auth: true, adminOnly: true, group: '站点管理', subgroup: '总览' },
  { to: '/admin/users', label: '用户管理', icon: Users, auth: true, adminOnly: true, group: '站点管理', subgroup: '用户与权限' },
  { to: '/admin/shop', label: 'R 币商城', icon: ShoppingBag, auth: true, roles: ['chief_editor', 'deputy_editor', 'editor_in_chief', 'shop_manager'], group: '站点管理', subgroup: '内容与社区' },
  { to: '/admin/claims', label: '认领审批', icon: FileSignature, auth: true, adminOnly: true, group: '站点管理', subgroup: '用户与权限' },
  { to: '/admin/role-applications', label: '角色申请', icon: ClipboardCheck, auth: true, adminOnly: true, group: '站点管理', subgroup: '用户与权限' },
  { to: '/admin/announcements', label: '公告管理', icon: Megaphone, auth: true, adminOnly: true, group: '站点管理', subgroup: '内容与社区' },
  { to: '/admin/forum-boards', label: '社区版块', icon: MessagesSquare, auth: true, adminOnly: true, group: '站点管理', subgroup: '内容与社区' },
  { to: '/admin/reports', label: '举报处置', icon: ShieldAlert, auth: true, adminOnly: true, group: '站点管理', subgroup: '内容与社区' },
  { to: '/admin/volumes', label: '卷管理', icon: Layers, auth: true, adminOnly: true, group: '站点管理', subgroup: '期刊与发布' },
  { to: '/admin/issues', label: '期管理', icon: CalendarDays, auth: true, adminOnly: true, group: '站点管理', subgroup: '期刊与发布' },
  { to: '/admin/releases', label: '发布门禁', icon: Rocket, auth: true, adminOnly: true, group: '站点管理', subgroup: '期刊与发布' },
  { to: '/admin/journal', label: '期刊信息', icon: Building2, auth: true, adminOnly: true, group: '站点管理', subgroup: '期刊与发布' },
  { to: '/admin/settings', label: '期刊设置', icon: Settings, auth: true, adminOnly: true, group: '站点管理', subgroup: '期刊与发布' },
  { to: '/admin/audit-logs', label: '审计日志', icon: ShieldCheck, auth: true, adminOnly: true, group: '站点管理', subgroup: '系统与安全' },
  { to: '/admin/system-health', label: '系统健康', icon: Activity, auth: true, adminOnly: true, group: '站点管理', subgroup: '系统与安全' },
]

export function AppShell() {
  // collapsed 仅用于桌面端（≥md）侧边栏宽窄切换
  const [collapsed, setCollapsed] = useState(false)
  // mobileOpen 控制 <md 抽屉开合；路由切换后自动关闭
  const [mobileOpen, setMobileOpen] = useState(false)
  const [cmdOpen, setCmdOpen] = useState(false)
  const [cmdQ, setCmdQ] = useState('')
  const { isAuthenticated, isAdmin, user, logout } = useAuth()
  const displayName = user?.display_name || user?.username || ''
  const navigate = useNavigate()
  const location = useLocation()
  const logoutMut = useLogout()
  const { data: unread } = useUnreadCount({ enabled: isAuthenticated })
  const lang = useLang()

  const visibleNav = filterNav(NAV, {
    isAuthenticated,
    isAdmin,
    roles: user?.roles ?? [],
  })

  const activePath = resolveActiveNavPath(location.pathname, visibleNav)

  // 路由变化时关闭移动端抽屉，避免点击导航后抽屉仍挡住内容
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  // 移动端抽屉打开时锁 body 滚动，避免背景滚动穿透
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = ''
      }
    }
  }, [mobileOpen])

  // ESC 关闭抽屉
  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileOpen])

  // ⌘K / Ctrl+K 全局搜索：任何页面都能唤起，回车跳目录。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCmdOpen((v) => !v)
      }
      if (e.key === 'Escape') setCmdOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submitCmd = (e: FormEvent) => {
    e.preventDefault()
    const q = cmdQ.trim()
    setCmdOpen(false)
    void navigate({ to: '/catalog', search: q ? { q } : {} })
  }

  const onLogout = async () => {
    try {
      await logoutMut.mutateAsync()
      toast.success('已退出登录')
      void navigate({ to: '/login' })
    } catch {
      // 即使 backend logout 失败也清本地状态
      logout()
      void navigate({ to: '/login' })
    }
  }

  // 期刊门面模式：首页走独立的全宽 editorial 版式（自带报头/导航/页脚），
  // 不套工作台侧边栏 —— 否则访客看到的是"作者后台"而不是对外期刊官网。
  // 注意：提前返回必须放在全部 hooks 之后（rules of hooks），
  // 否则会形成条件式 hook 调用（react-hooks/rules-of-hooks 会拦截）。
  // 访客入口页（登录/注册/找回密码/邮箱验证）同样不套工作台侧栏：
  // 未登录用户看到「我的提交/用户管理」这类导航只会困惑，且登录框应居中独立。
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
        <PageViewTracker />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-background">
      <AmbientBackdrop />
      {/* 移动端遮罩：<md 抽屉打开时显示 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow">{text('跳到主要内容', lang)}</a>
      <aside
        className={cn(
          'sticky top-0 z-40 flex h-screen flex-col border-r bg-sidebar text-sidebar-foreground transition-all relative',
          // 桌面端：根据 collapsed 切换宽窄；移动端：固定窄宽 + translate 控制显隐
          'md:sticky md:translate-x-0',
          collapsed ? 'md:w-14' : 'md:w-[220px]',
          'w-[220px] max-md:fixed max-md:transition-transform',
          mobileOpen ? 'max-md:translate-x-0' : 'max-md:-translate-x-full',
        )}
      >
        <div className="flex h-14 items-center justify-between border-b px-4">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <BrandMark className="h-5 w-5 shrink-0" />
            {!collapsed && <span>Rubbish</span>}
          </Link>
          {/* 移动端关闭按钮（仅 <md 显示） */}
          <button
            type="button"
            className="text-sidebar-foreground/60 hover:text-sidebar-foreground md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label={text('关闭菜单', lang)}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {visibleNav.map((item, idx) => {
            const Icon = item.icon
            const active = item.to === activePath
            const showBadge = item.to === '/notifications' && (unread?.unread ?? 0) > 0
            // 角色化分组：组变化时插入分组标题（展开态）或分隔线（折叠态），
            // 让读者/作者/审稿人/编辑一眼看清自己的工作区分块
            const prev = idx > 0 ? visibleNav[idx - 1] : undefined
            const showGroup = item.group !== undefined && (!prev || prev.group !== item.group)
            const showSubgroup =
              !collapsed &&
              item.subgroup !== undefined &&
              item.group !== undefined &&
              (!prev || prev.group !== item.group || prev.subgroup !== item.subgroup)
            return (
              <Fragment key={item.to}>
                {showGroup &&
                  (collapsed ? (
                    <div className="my-2 border-t border-sidebar-foreground/15" aria-hidden />
                  ) : (
                    <p className="nav-group-label mb-1 mt-3 px-3 text-[10px] font-medium uppercase tracking-widest text-sidebar-foreground/45 first:mt-1">
                      {groupLabel(item.group ?? '', lang)}
                    </p>
                  ))}
                {showSubgroup && (
                  <p className="mb-1 mt-2 px-3 text-[10px] font-medium tracking-wide text-sidebar-foreground/35">
                    {groupLabel(item.subgroup ?? '', lang)}
                  </p>
                )}
                <Link
                key={item.to}
                to={item.to}
                data-active={active ? 'true' : 'false'}
                className={cn(
                  'nav-item mb-1 flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground',
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span className="flex-1">{navLabel(item.to, item.label, lang)}</span>}
                {showBadge && !collapsed && (
                  <span className="rounded-full bg-destructive px-2 py-0.5 text-xs text-destructive-foreground">
                    {unread!.unread}
                  </span>
                )}
              </Link>
              </Fragment>
            )
          })}
        </nav>
        {/* 身份卡：始终在左栏底部，回答“我是谁、能做什么” */}
        {!collapsed && (
          <div className="mx-3 mb-2 rounded-lg border border-sidebar-foreground/15 bg-sidebar-accent/30 p-3">
            {isAuthenticated && user ? (
              <div className="flex items-center gap-2.5">
                <Avatar className="h-8 w-8 shrink-0">
                  <AvatarImage src={user.avatar_url ?? undefined} alt="" />
                  <AvatarFallback>{displayName.slice(0, 2).toUpperCase()}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{displayName}</p>
                  <p className="truncate text-[10px] text-sidebar-foreground/55">
                    {user.roles?.some((r) => ['chief_editor','editor_in_chief'].includes(r)) ? '主编' : user.roles?.includes('reviewer') ? '审稿人' : '作者 / 读者'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-[11px] leading-relaxed text-sidebar-foreground/70">登录后可投稿、认领与跟踪审稿。</p>
                <Button asChild size="sm" className="h-8 w-full text-xs"><Link to="/login">登录 / 注册</Link></Button>
              </div>
            )}
          </div>
        )}
        {/* 折叠按钮仅桌面端可见 */}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="hidden h-12 items-center justify-center border-t text-sidebar-foreground/60 hover:text-sidebar-foreground md:flex"
          aria-label={text(collapsed ? '展开侧边栏' : '收起侧边栏', lang)}
        >
          <ChevronLeft className={cn('h-4 w-4 transition-transform', collapsed && 'rotate-180')} />
        </button>
      </aside>

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="app-header-rule sticky top-0 z-20 flex h-14 items-center justify-between gap-2 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          {/* 左侧：移动端汉堡 + 折叠状态下的页面标识 */}
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label={text('打开菜单', lang)}
            >
              <Menu className="h-5 w-5" />
            </Button>
          </div>
          {/* 右侧：主题切换 + 用户菜单/登录注册 */}
          <div className="flex items-center gap-1 sm:gap-2">
            <Button variant="outline" size="sm" className="hidden h-8 gap-2 px-2.5 text-xs sm:inline-flex" onClick={() => setCmdOpen(true)}>
              <Search className="h-3.5 w-3.5" />
              {text('搜索', lang)}
              <kbd className="rounded border bg-muted px-1 font-mono text-[10px] text-muted-foreground">⌘K</kbd>
            </Button>
            <LanguageToggle />
            <AppearanceMenu />
            {isAuthenticated && user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="gap-2" aria-label={text('账号菜单', lang)}>
                    <Avatar className="h-7 w-7">
                      <AvatarImage src={user.avatar_url ?? undefined} alt="" />
                      <AvatarFallback>{displayName.slice(0, 2).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <span className="hidden text-sm sm:inline">{displayName}</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>{displayName}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link to="/shop">
                      <ShoppingBag className="h-4 w-4" />
                      R 币商城
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/me">
                      <Award className="h-4 w-4" />
                      {text('个人中心', lang)}
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to="/settings">
                      <User className="h-4 w-4" />
                      {text('账号设置', lang)}
                    </Link>
                  </DropdownMenuItem>
                  {(user.roles?.includes('reviewer') || user.roles?.includes('editor_in_chief') || isAdmin) && (
                    <DropdownMenuItem asChild>
                      <Link to="/review/assignments">
                        <ClipboardCheck className="h-4 w-4" />
                        {text('审稿工作台', lang)}
                      </Link>
                    </DropdownMenuItem>
                  )}
                  {(user.roles?.some((r) => ['editor', 'section_editor', 'board_editor', 'deputy_editor', 'chief_editor', 'editor_in_chief'].includes(r)) || isAdmin) && (
                    <DropdownMenuItem asChild>
                      <Link to="/editor/workbench">
                        <Gavel className="h-4 w-4" />
                        {text('主编工作台', lang)}
                      </Link>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={onLogout} className="text-destructive">
                    {text('退出登录', lang)}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <div className="flex items-center gap-2">
                <Button asChild variant="ghost" size="sm">
                  <Link to="/login">{text('登录', lang)}</Link>
                </Button>
                <Button asChild size="sm">
                  <Link to="/register">{text('注册', lang)}</Link>
                </Button>
              </div>
            )}
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
          {/* 响应式 padding：移动端紧凑，桌面端宽松 */}
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
            {/* 页面级错误边界：单个路由崩溃时侧边栏/头部仍可用，
                resetKeys 绑定 pathname —— 换页自动复位，无需手动点重试 */}
            <ModuleErrorBoundary name="页面" resetKeys={[location.pathname]}>
              <PageTransition>
                <Outlet />
              </PageTransition>
            </ModuleErrorBoundary>
          </div>
        </main>
      </div>
      {cmdOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[18vh]" onClick={() => setCmdOpen(false)}>
          <form onSubmit={submitCmd} className="w-full max-w-xl overflow-hidden rounded-xl border bg-background shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 border-b px-4 py-3">
              <Search className="h-4 w-4 text-muted-foreground" />
              <input autoFocus value={cmdQ} onChange={(e) => setCmdQ(e.target.value)} placeholder="搜索论文、副刊、作者、关键词…" className="h-9 flex-1 bg-transparent text-sm outline-none" />
              <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">Enter</kbd>
            </div>
            <div className="px-4 py-2 text-[11px] text-muted-foreground">回车进入目录；Esc 关闭。论文与副刊分轨展示。</div>
          </form>
        </div>
      )}
      <OnboardingTour />
      <CookieBanner />
    </div>
  )
}
