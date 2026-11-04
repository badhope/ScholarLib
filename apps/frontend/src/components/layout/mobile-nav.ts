import {
  Bell,
  BookOpen,
  ClipboardCheck,
  FileSignature,
  Gavel,
  Heart,
  Home,
  Building2,
  Lightbulb,
  PenLine,
  Scroll,
  ScrollText,
  Settings,
  ShieldCheck,
  Upload,
  Users,
  Award,
  CalendarDays,
  Compass,
  Megaphone,
  MessagesSquare,
  type LucideIcon,
  User,
} from 'lucide-react'

export interface MobileTab {
  to: string
  label: string
  icon: LucideIcon
  /** 为 true 时点击不跳转，而是打开"更多"底部抽屉 */
  openSheet?: boolean
}

export interface MobileMoreItem {
  to: string
  label: string
  icon: LucideIcon
  adminOnly?: boolean
  /** 任一角色命中即可见（admin 视为全角色） */
  roles?: string[]
  /** "更多"抽屉里的分组标题；按 MOBILE_MORE_GROUP_ORDER 的顺序呈现 */
  group: string
}

// 抽屉分组顺序：高频的"我的"在最上，管理类收在最后——层层递进，
// 避免一次摊开 17 个入口让用户眼花。
export const MOBILE_MORE_GROUP_ORDER = ['我的', '工作台', '期刊', '设置', '站点管理'] as const

// 底部 Tab 栏：4 个固定入口。中心 FAB 由外壳单独渲染，不在此列表。
// 人的逻辑：第一个 Tab 是公开首页（不登录也能逛），登录后的概览移入"更多"抽屉。
export const MOBILE_TABS: MobileTab[] = [
  { to: '/', label: '首页', icon: Home },
  // 第二个 Tab 给「浏览」而非「目录」：移动端需要分类入口，
  // 直接甩一张大表格是最差的移动体验。
  { to: '/browse', label: '浏览', icon: Compass },
  { to: '/notifications', label: '通知', icon: Bell },
  { to: '/__more', label: '我的', icon: User, openSheet: true },
]

// "更多"底部抽屉的次级导航（按 isAdmin + 角色过滤，再按 group 分组渲染）。
export const MOBILE_MORE: MobileMoreItem[] = [
  { to: '/dashboard', label: '概览', icon: Home, group: '我的' },
  { to: '/profile', label: '个人中心', icon: Award, group: '我的' },
  { to: '/submissions', label: '我的提交', icon: ScrollText, group: '我的' },
  { to: '/follows', label: '关注与订阅', icon: Heart, group: '我的' },
  { to: '/recommendations', label: '推荐', icon: Lightbulb, group: '我的' },
  { to: '/forum', label: '讨论区', icon: MessagesSquare, group: '我的' },
  { to: '/catalog', label: '资源目录', icon: BookOpen, group: '期刊' },
  { to: '/review/assignments', label: '审稿工作台', icon: ClipboardCheck, roles: ['reviewer'], group: '工作台' },
  {
    to: '/submissions/pending',
    label: '编辑工作台',
    icon: Gavel,
    roles: ['editor', 'section_editor'],
    group: '工作台',
  },
  { to: '/ingest', label: '导入', icon: Upload, roles: ['author', 'editor', 'section_editor'], group: '工作台' },
  { to: '/archive', label: '卷期归档', icon: CalendarDays, group: '期刊' },
  { to: '/levels', label: '等级与规范', icon: Compass, group: '期刊' },
  { to: '/authors', label: '作者指南', icon: PenLine, group: '期刊' },
  { to: '/policies', label: '政策规范', icon: Scroll, group: '期刊' },
  { to: '/about', label: '关于本刊', icon: Building2, group: '期刊' },
  { to: '/settings', label: '账号设置', icon: Settings, group: '设置' },
  { to: '/admin/users', label: '用户管理', icon: Users, adminOnly: true, group: '站点管理' },
  { to: '/admin/claims', label: '认领审批', icon: FileSignature, adminOnly: true, group: '站点管理' },
  { to: '/admin/role-applications', label: '角色申请', icon: ClipboardCheck, adminOnly: true, group: '站点管理' },
  { to: '/admin/audit-logs', label: '审计日志', icon: ShieldCheck, adminOnly: true, group: '站点管理' },
  { to: '/admin/announcements', label: '公告管理', icon: Megaphone, adminOnly: true, group: '站点管理' },
  { to: '/admin/settings', label: '期刊设置', icon: Settings, adminOnly: true, group: '站点管理' },
]

// 中心悬浮按钮（FAB）跳转目标：导入页（投稿/导入属于创建类操作）。
// 可见性由外壳按角色控制（author/editor/section_editor/admin），纯读者
// 不显示 FAB——避免点进去只有 403 空壳。
export const MOBILE_FAB_TO = '/ingest'
