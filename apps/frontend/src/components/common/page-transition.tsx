import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useRouterState } from '@tanstack/react-router'
import { motion, useReducedMotion } from 'motion/react'

/**
 * 路由级过渡：新页淡入并轻微上浮。
 *
 * 刻意**不用** AnimatePresence：`mode="wait"` 会把新页的挂载推迟到旧页退出动画
 * 结束后，而依赖 router state 的页面（如 ingest → submissions 的预填弹窗）
 * 会在推迟期间丢掉状态。这里只做「进入」动画，卸载保持同步。
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const location = useLocation()
  const reduce = useReducedMotion()
  const routerPending = useRouterState({ select: (s) => s.status === 'pending' })
  const [flash, setFlash] = useState(false)

  useEffect(() => {
    setFlash(true)
    const timer = window.setTimeout(() => setFlash(false), 450)
    return () => window.clearTimeout(timer)
  }, [location.pathname])

  const loadingBar = (routerPending || flash) ? (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[80] h-0.5 overflow-hidden bg-primary/15" aria-hidden>
      <div className="route-progress h-full w-1/3 bg-primary" />
    </div>
  ) : null

  if (reduce) {
    return (
      <>
        {loadingBar}
        {children}
      </>
    )
  }

  return (
    <>
    {loadingBar}
    <motion.div
      key={location.pathname}
      initial={{ opacity: 0.55, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
    </>
  )
}
