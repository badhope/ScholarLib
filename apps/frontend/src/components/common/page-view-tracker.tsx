import { useEffect } from 'react'
import { useLocation } from '@tanstack/react-router'

/**
 * 第一方匿名访问统计：只上报路径与来源，不采集 IP / UA / 用户 ID。
 * 管理端、审稿台、个人中心等私密路径不上报。
 */
const PRIVATE_PREFIXES = ['/admin', '/review', '/editor', '/me', '/settings', '/notifications']

export function PageViewTracker() {
  const location = useLocation()

  useEffect(() => {
    const path = location.pathname
    if (PRIVATE_PREFIXES.some((prefix) => path.startsWith(prefix))) return
    const key = `pv:${path}`
    if (sessionStorage.getItem(key)) return
    sessionStorage.setItem(key, '1')

    const body = JSON.stringify({ path, referrer: document.referrer || null })
    // keepalive 让页面切换/关闭时也能把最后一个事件发出去。
    void fetch('/api/telemetry/pageview', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {
      // 统计失败不能影响阅读；下次进入同一路径仍会重试。
      sessionStorage.removeItem(key)
    })
  }, [location.pathname])

  return null
}
