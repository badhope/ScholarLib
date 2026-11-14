import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { requireAdminGuard } from '@/lib/route-guards'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export const Route = createFileRoute('/admin/system-health')({
  beforeLoad: () => requireAdminGuard(),
  component: SystemHealthPage,
})

type Check = {
  key: string
  label: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}

type Health = {
  status: 'ok' | 'warn' | 'fail'
  version: string
  db_revision: string | null
  code_revision: string | null
  db_latency_ms: number | null
  counts: Record<string, number>
  disk_free_gb: number | null
  disk_used_pct: number | null
  load_1m: number | null
  checks: Check[]
}

function StatusIcon({ status }: { status: Check['status'] }) {
  if (status === 'ok') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (status === 'warn') return <AlertTriangle className="h-4 w-4 text-amber-600" />
  return <XCircle className="h-4 w-4 text-destructive" />
}

export function SystemHealthPage() {
  const [data, setData] = useState<Health | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      const res = await api.get<Health>('/admin/system/health')
      setData(res.data)
    } catch {
      toast.error('系统健康数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div>
      <PageHeader
        title="系统健康"
        description="数据库、迁移、磁盘、内容积压与邮件通道的聚合状态；只读，不暴露连接串与密钥。"
        actions={
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className="mr-1.5 h-4 w-4" />
            刷新
          </Button>
        }
      />

      {!data ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {loading ? '加载中…' : '暂无数据'}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-muted-foreground">总体状态</CardTitle>
              </CardHeader>
              <CardContent>
                <Badge
                  variant={
                    data.status === 'ok'
                      ? 'secondary'
                      : data.status === 'fail'
                        ? 'destructive'
                        : 'outline'
                  }
                >
                  {data.status === 'ok' ? '正常' : data.status === 'fail' ? '故障' : '需关注'}
                </Badge>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-muted-foreground">数据库延迟</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold tabular-nums">
                {data.db_latency_ms ?? '—'} <span className="text-xs font-normal">ms</span>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-muted-foreground">磁盘剩余</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold tabular-nums">
                {data.disk_free_gb ?? '—'} <span className="text-xs font-normal">GB</span>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-xs text-muted-foreground">版本</CardTitle>
              </CardHeader>
              <CardContent className="text-sm font-medium">{data.version}</CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="h-4 w-4" />
                检查项
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 md:grid-cols-2">
              {data.checks.map((c) => (
                <div key={c.key} className="flex items-start gap-3 rounded-md border p-3">
                  <StatusIcon status={c.status} />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{c.label}</p>
                    <p className="mt-0.5 break-words text-xs text-muted-foreground">{c.detail}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">数据与迁移</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">用户</p>
                <p className="font-medium tabular-nums">{data.counts.users ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">资源</p>
                <p className="font-medium tabular-nums">{data.counts.resources ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">投稿</p>
                <p className="font-medium tabular-nums">{data.counts.submissions ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">库迁移版本</p>
                <p className="font-medium">{data.db_revision ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">代码迁移版本</p>
                <p className="font-medium">{data.code_revision ?? '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">负载（1m）</p>
                <p className="font-medium tabular-nums">{data.load_1m ?? '—'}</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
