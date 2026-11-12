import { createFileRoute, redirect } from '@tanstack/react-router'
import { getAuthState } from '@/lib/auth'

/**
 * 旧审稿工作台地址：保留书签可达，但不再维护第二套表单。
 *
 * 表单已统一到 `/review/assignments`（与桌面、移动端同一套字段：
 * 推荐决定、七维评分、给作者/编辑意见、特别篇、附件、预览）。
 * 这里只做鉴权 + 重定向，避免同一份审稿报告出现两套不一致的实现。
 */
export const Route = createFileRoute('/review/workbench')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
    throw redirect({ to: '/review/assignments' })
  },
  component: () => null,
})
