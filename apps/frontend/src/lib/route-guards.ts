import { redirect } from '@tanstack/react-router'
import { getAuthState } from '@/lib/auth'

/**
 * 路由守卫辅助：把「已登录但越权」与「未登录」区分开。
 *
 * 此前所有 adminOnly 页面对非管理员一律跳 /login —— 用户明明已经登录，
 * 却被要求再登录一次，困惑且像 bug。现在：
 * - 未登录 → /login（正常认证流）
 * - 已登录但无权 → /403（明确的越权页，提供返回路径）
 */
export function requireAdminGuard(): void {
  const state = getAuthState()
  if (!state.isAuthenticated) throw redirect({ to: '/login' })
  if (!state.isAdmin) throw redirect({ to: '/403' })
}


/** 主编/副主编可访问的站点管理页（比 admin 宽一档，覆盖非 is_admin 的主编）。 */
export function requireChiefGuard(): void {
  const state = getAuthState()
  if (!state.isAuthenticated) throw redirect({ to: '/login' })
  const roles = state.user?.roles ?? []
  if (!state.isAdmin && !roles.some((r) => ['chief_editor', 'deputy_editor', 'editor_in_chief'].includes(r))) {
    throw redirect({ to: '/403' })
  }
}

/** 商城后台：主编/副主编，或单独授予 shop_manager 的账号。 */
export function requireShopManagerGuard(): void {
  const state = getAuthState()
  if (!state.isAuthenticated) throw redirect({ to: '/login' })
  const roles = state.user?.roles ?? []
  if (
    !state.isAdmin &&
    !roles.some((r) => ['chief_editor', 'deputy_editor', 'editor_in_chief', 'shop_manager'].includes(r))
  ) {
    throw redirect({ to: '/403' })
  }
}
