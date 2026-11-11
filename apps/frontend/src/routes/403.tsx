import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, ShieldOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export const Route = createFileRoute('/403')({
  component: ForbiddenPage,
})

function ForbiddenPage() {
  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
            <ShieldOff className="h-7 w-7 text-muted-foreground" />
          </div>
          <h1 className="text-2xl font-semibold">无权访问</h1>
          <p className="text-sm text-muted-foreground">
            你已登录，但当前账号没有访问此页面的权限。
            如需相应权限，请联系编辑部（站点管理员）为你分配角色。
          </p>
          <div className="flex gap-2">
            <Button asChild variant="outline">
              <Link to="/dashboard">
                <ArrowLeft className="h-4 w-4" /> 返回概览
              </Link>
            </Button>
            <Button asChild>
              <Link to="/">去首页</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
