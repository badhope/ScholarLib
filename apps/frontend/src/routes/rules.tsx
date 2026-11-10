import { createFileRoute, redirect } from '@tanstack/react-router'

// /rules 已并入 /guide 的「政策规范 / 等级」页签，保留旧地址做 301 式跳转，
// 避免旧邮件、旧外链和搜索引擎收录落到空页。
export const Route = createFileRoute('/rules')({
  beforeLoad: ({ search }: { search: { tab?: string } }) => {
    throw redirect({
      to: '/guide',
      search: { tab: search.tab === 'levels' ? 'levels' : 'policies' },
    })
  },
  component: () => null,
})
