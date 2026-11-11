import { Link } from '@tanstack/react-router'
import { BookOpen, Compass, Home } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * 全站 404：替换 TanStack 默认的裸 "Not Found" 文本。
 * 在壳层内渲染（保留导航），给出明确的中文说明与下一步去处。
 */
export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg items-center justify-center px-4">
      <div className="state-panel flex flex-col items-center gap-4 text-center">
        <span className="state-icon">
          <Compass className="h-8 w-8" />
        </span>
        <div className="space-y-1.5">
          <h1 className="state-title text-3xl font-semibold tabular-nums">404</h1>
          <p className="text-base font-medium">页面不存在或已被移动</p>
          <p className="text-sm text-muted-foreground">
            链接可能输错了，或者这条内容已经下架。从下面的入口继续浏览吧。
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link to="/">
              <Home className="h-4 w-4" />
              返回首页
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/catalog">
              <BookOpen className="h-4 w-4" />
              浏览资源目录
            </Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
