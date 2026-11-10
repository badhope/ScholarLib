import { createFileRoute, redirect } from '@tanstack/react-router'

// 历史/外部链接使用 /catalog/track/essay 这种两段式路径；正式目录只有
// /catalog?track=essay。这里保留 301 语义的前端重定向，避免直接 404。
export const Route = createFileRoute('/catalog/track/$track')({
  beforeLoad: ({ params }) => {
    const track = params.track === 'paper' ? 'paper' : 'essay'
    throw redirect({ to: '/catalog', search: { track } })
  },
})
