import { useState } from 'react'
import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { ArrowLeft, BarChart3 } from 'lucide-react'
import { getAuthState } from '@/lib/auth'
import { useReviewerCalibration } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export const Route = createFileRoute('/editor/calibration')({
  beforeLoad: () => {
    const state = getAuthState()
    if (!state.isAuthenticated) throw redirect({ to: '/login' })
    const roles = state.user?.roles ?? []
    if (!state.isAdmin && !roles.some((r) => ['editor', 'section_editor', 'editor_in_chief'].includes(r))) {
      throw redirect({ to: '/403' })
    }
  },
  component: CalibrationPage,
})

const FLAG_LABELS: Record<string, string> = {
  harsh: '偏严',
  lenient: '偏宽',
  high_variance: '波动大',
  insufficient_volume: '样本不足',
}

function CalibrationPage() {
  const now = new Date()
  const currentYear = now.getFullYear()
  const currentQuarter = Math.floor(now.getMonth() / 3) + 1
  const [year, setYear] = useState(currentYear)
  const [quarter, setQuarter] = useState(currentQuarter)
  const { data, isLoading, isError, refetch } = useReviewerCalibration(year, quarter)

  const rows = data?.reviewers ?? []
  const years = Array.from({ length: 5 }, (_, i) => currentYear - i)

  return (
    <div>
      <PageHeader
        title="审稿人季度校准"
        description="看每位审稿人相对同稿共识的平均偏移与推荐分布；只用于定向沟通，不自动降级或封禁。"
        actions={
          <Link to="/editor/workbench">
            <Button variant="outline" size="sm">
              <ArrowLeft className="mr-1 h-4 w-4" aria-hidden />
              返回工作台
            </Button>
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="calibration-year">年份</Label>
          <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger id="calibration-year" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {years.map((item) => (
                <SelectItem key={item} value={String(item)}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="calibration-quarter">季度</Label>
          <Select value={String(quarter)} onValueChange={(v) => setQuarter(Number(v))}>
            <SelectTrigger id="calibration-quarter" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[1, 2, 3, 4].map((item) => (
                <SelectItem key={item} value={String(item)}>
                  第 {item} 季度
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {data ? (
          <div className="text-xs text-muted-foreground">
            {new Date(data.period_start).toLocaleDateString()} –{' '}
            {new Date(data.period_end).toLocaleDateString()} · 纳入 {data.submission_count} 篇有评分的稿件
          </div>
        ) : null}
      </div>

      {isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : isError ? (
        <ErrorState message="校准数据加载失败" onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="本季度还没有完成的审稿报告"
          description="审稿人提交报告后，这里会按同稿共识计算偏移；样本不足时不会给出偏严/偏宽结论。"
        />
      ) : (
        <>
          <div className="mb-3 rounded-md border border-dashed bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
            <span className="mr-1 font-medium text-foreground">读法：</span>
            偏移 = 本人总分 − 同稿其他审稿人均分。偏严/偏宽阈值 ±8 分，波动大为平均绝对偏移 ≥15 分；
            少于 2 份报告只标“样本不足”，不据此评价审稿人。
          </div>
          <Card>
            <CardContent className="overflow-x-auto p-0">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-medium">审稿人</th>
                    <th className="px-4 py-3 font-medium">完成报告</th>
                    <th className="px-4 py-3 font-medium">平均总分</th>
                    <th className="px-4 py-3 font-medium">平均偏移</th>
                    <th className="px-4 py-3 font-medium">平均绝对偏移</th>
                    <th className="px-4 py-3 font-medium">录用倾向</th>
                    <th className="px-4 py-3 font-medium">标记</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.reviewer_id} className="border-b last:border-0">
                      <td className="px-4 py-3 font-medium">{row.username}</td>
                      <td className="px-4 py-3 tabular-nums">{row.completed_reviews}</td>
                      <td className="px-4 py-3 tabular-nums">
                        {row.avg_score === null ? '—' : row.avg_score.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {row.avg_deviation === null
                          ? '—'
                          : `${row.avg_deviation > 0 ? '+' : ''}${row.avg_deviation.toFixed(1)}`}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {row.avg_abs_deviation === null
                          ? '—'
                          : row.avg_abs_deviation.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {row.accept_rate === null ? '—' : `${row.accept_rate.toFixed(1)}%`}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {row.flags.length === 0 ? (
                            <Badge variant="outline">稳定</Badge>
                          ) : (
                            row.flags.map((flag) => (
                              <Badge
                                key={flag}
                                variant={flag === 'insufficient_volume' ? 'outline' : 'secondary'}
                              >
                                {FLAG_LABELS[flag] ?? flag}
                              </Badge>
                            ))
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
          <p className="mt-3 flex items-center gap-1 text-xs text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden />
            录用倾向 = accept 1.0 / minor 0.75 / major 0.25 / reject 0.0 的加权均值，不等同于编辑部录用率。
          </p>
        </>
      )}
    </div>
  )
}
