import type { LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  auth?: boolean
  adminOnly?: boolean
  /**
   * 任一角色命中即可见（admin 视为拥有全部角色）。只影响导航可见性，
   * 真正的权限由后端 require_* 依赖强制。
   */
  roles?: string[]
  /** 侧边栏一级分组标题：角色化导航 —— 读者/作者/审稿人/编辑各自只见自己的分区 */
  group?: string
  /** 二级分组：后台「站点管理」内部再分层（内容治理/用户权限/期刊发布/系统） */
  subgroup?: string
}

export interface NavViewer {
  isAuthenticated: boolean
  isAdmin: boolean
  roles: string[]
}

/**
 * 导航可见性过滤：登录要求 + 管理员限定 + 角色命中（任一）。
 *
 * 不用「登录就显示审稿工作台」这种粗粒度判断：普通作者点进去只会看到
 * 403 空壳。admin 绕过角色检查（后端同样把 admin 视为全角色）。
 */
export function filterNav<T extends NavItem>(items: T[], viewer: NavViewer): T[] {
  return items.filter((item) => {
    if (item.auth && !viewer.isAuthenticated) return false
    if (item.adminOnly && !viewer.isAdmin) return false
    if (item.roles && !viewer.isAdmin && !item.roles.some((r) => viewer.roles.includes(r))) {
      return false
    }
    return true
  })
}

/**
 * 侧边栏高亮解析：**最长前缀胜出**。
 *
 * - `/submissions/pending` 同时匹配「我的提交」(`/submissions`) 与
 *   「编辑工作台」(`/submissions/pending`)，取更长的那个，避免编辑工作台
 *   页面误高亮成"我的提交"（语义归属错误）。
 * - 段级匹配（`===` 或 `${to}/` 前缀）而非裸 `startsWith`，避免
 *   `/submissionsfoo` 误匹配 `/submissions` 这类假阳性。
 *
 * 抽成纯函数是为了可测：这段逻辑曾内联在 AppShell 组件里，无法单测覆盖。
 */
export function resolveActiveNavPath(
  pathname: string,
  items: NavItem[],
): string | undefined {
  return items
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0]?.to
}
