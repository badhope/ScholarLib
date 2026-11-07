import { createFileRoute, redirect } from '@tanstack/react-router'
import { getAuthState } from '@/lib/auth'

// /profile 已迁移到 /me（身份权限轴 + 身份内等级激励轴）。
// 保留旧路由，301 式重定向，避免书签与外链 404。
export const Route = createFileRoute('/profile')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
    throw redirect({ to: '/me' })
  },
})
