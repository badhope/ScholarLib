import { useEffect } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'

// v5：详情页已改为"点开即正文"，/reader/$resourceId 不再独立存在。
// 前端兜底跳转：保留路由不 404，301 由后端另一路做。
export const Route = createFileRoute('/reader/$resourceId')({
  component: ReaderRedirect,
})

function ReaderRedirect() {
  const { resourceId } = Route.useParams()
  const navigate = useNavigate()
  useEffect(() => {
    void navigate({
      to: '/catalog/$resourceId',
      params: { resourceId },
      hash: 'article',
      replace: true,
    })
  }, [navigate, resourceId])
  return null
}
