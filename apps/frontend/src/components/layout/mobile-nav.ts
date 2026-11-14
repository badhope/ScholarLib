import {
  Bell,
  BookOpen,
  ClipboardCheck,
  FileSignature,
  Gavel,
  Heart,
  Home,
  Coffee,
  Layers,
  Scale,
  Building2,
  Lightbulb,
  PenLine,
  Rocket,
  ScrollText,
  Activity,
  Flag,
  Settings,
  ShieldCheck,
  Upload,
  Users,
  CalendarDays,
  Megaphone,
  MessagesSquare,
  Library,
  type LucideIcon,
  User,
} from 'lucide-react'

export interface MobileTab {
  to: string
  label: string
  icon: LucideIcon
}

export interface MobileMoreItem {
  to: string
  label: string
  icon: LucideIcon
  /** 仅登录用户可见 */
  auth?: boolean
  adminOnly?: boolean
  /** 任一角色命中即可见（admin 视为全角色） */
  roles?: string[]
  /** 折叠菜单里的分组标题 */
  group: string
}

// 折叠菜单分组顺序
export const MOBILE_MORE_GROUP_ORDER = ['我的', '工作台', '期刊', '消息', '内容与社区', '用户与权限', '期刊与发布', '系统与安全', '设置'] as const

// 底部固定 5 Tab：首页 / 论文 / 副刊 / 讨论 / 我的。
// 「我的」指向 /me（身份等级同事已落地；/profile 会重定向到 /me）。
export const MOBILE_TABS: MobileTab[] = [
  { to: '/', label: '首页', icon: Home },
  { to: '/papers', label: '论文', icon: BookOpen },
  { to: '/fun', label: '副刊', icon: Coffee },
  { to: '/forum', label: '讨论', icon: MessagesSquare },
  { to: '/me', label: '我的', icon: User },
]

// 折叠菜单（header 右上角"⋯"弹出）：收进抽屉时代的次级入口，
// 避免删抽屉后指标/卷期/政策/关于/后台等入口失联。
export const MOBILE_MORE: MobileMoreItem[] = [
  { to: '/dashboard', label: '概览', icon: Home, auth: true, group: '我的' },
  { to: '/submissions', label: '我的提交', icon: ScrollText, auth: true, group: '我的' },
  { to: '/appeals', label: '作者申诉', icon: Scale, auth: true, group: '我的' },
  { to: '/follows', label: '关注与订阅', icon: Heart, auth: true, group: '我的' },
  { to: '/recommendations', label: '推荐', icon: Lightbulb, auth: true, group: '我的' },
  { to: '/library', label: '阅读列表', icon: Library, auth: true, group: '我的' },
  { to: '/review/assignments', label: '审稿工作台', icon: ClipboardCheck, auth: true, roles: ['reviewer', 'editor_in_chief'], group: '工作台' },
  {
    to: '/editor/workbench',
    label: '主编工作台',
    icon: Gavel,
    auth: true,
    roles: ['editor', 'section_editor', 'board_editor', 'deputy_editor', 'chief_editor', 'editor_in_chief'],
    group: '工作台',
  },
  { to: '/ingest', label: '导入', icon: Upload, auth: true, roles: ['author', 'editor', 'section_editor'], group: '工作台' },
  { to: '/sections', label: '栏目', icon: Layers, group: '期刊' },
  { to: '/archive', label: '卷期归档', icon: CalendarDays, group: '期刊' },
  { to: '/about', label: '关于与指标', icon: Building2, group: '期刊' },
  { to: '/guide', label: '投稿与操作指南', icon: PenLine, group: '期刊' },
  { to: '/notifications', label: '通知', icon: Bell, auth: true, group: '消息' },
  { to: '/settings', label: '账号设置', icon: Settings, auth: true, group: '设置' },
  { to: '/admin/users', label: '用户管理', icon: Users, auth: true, adminOnly: true, group: '用户与权限' },
  { to: '/admin/claims', label: '认领审批', icon: FileSignature, auth: true, adminOnly: true, group: '用户与权限' },
  { to: '/admin/role-applications', label: '角色申请', icon: ClipboardCheck, auth: true, adminOnly: true, group: '用户与权限' },
  { to: '/admin/announcements', label: '公告管理', icon: Megaphone, auth: true, adminOnly: true, group: '内容与社区' },
  { to: '/admin/forum-boards', label: '社区版块', icon: Layers, auth: true, adminOnly: true, group: '内容与社区' },
  { to: '/admin/reports', label: '举报处置', icon: Flag, auth: true, adminOnly: true, group: '内容与社区' },
  { to: '/admin/releases', label: '发布门禁', icon: Rocket, auth: true, adminOnly: true, group: '期刊与发布' },
  { to: '/admin/settings', label: '期刊设置', icon: Settings, auth: true, adminOnly: true, group: '期刊与发布' },
  { to: '/admin/audit-logs', label: '审计日志', icon: ShieldCheck, auth: true, adminOnly: true, group: '系统与安全' },
  { to: '/admin/system-health', label: '系统健康', icon: Activity, auth: true, adminOnly: true, group: '系统与安全' },
]

// 中心悬浮按钮（FAB）跳转目标：导入页（投稿/导入属于创建类操作）。
export const MOBILE_FAB_TO = '/ingest'
