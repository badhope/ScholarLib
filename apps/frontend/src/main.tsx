import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { routeTree } from './routeTree.gen'
import { ThemeProvider } from './components/theme-provider'
import { AppErrorBoundary } from './components/common/error-boundary'
import { initMonitoring, installGlobalErrorHandlers } from './lib/monitoring'
// 期刊衬线字体（自托管可变字重，中文按 unicode-range 分片按需加载）
import './index.css'

// window.onerror + unhandledrejection 兜底（ErrorBoundary 只覆盖渲染期错误）
installGlobalErrorHandlers()
// 监控后端初始化。未配置 VITE_SENTRY_DSN 时为 no-op；
// 不 await —— 上报能力晚几十毫秒就绪不影响首屏，错误在此之前由 console reporter 兜住。
void initMonitoring()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      // 切回标签页/网络恢复时刷新：期刊站内容会更新（新刊出论文、评论），
      // 关闭聚焦刷新会让用户看到过期目录（此前 5 分钟内看不到新发表）。
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
})

const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
  context: { queryClient },
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

const root = document.getElementById('root')!
createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AppErrorBoundary>
          <RouterProvider router={router} />
        </AppErrorBoundary>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
