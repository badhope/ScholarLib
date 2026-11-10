import { createFileRoute, redirect } from '@tanstack/react-router'

// 历史外链 /grade 指向等级与规范页；保留别名，避免 404。
export const Route = createFileRoute('/grade')({
  beforeLoad: () => { throw redirect({ to: '/levels' }) },
})
