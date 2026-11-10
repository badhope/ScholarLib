import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'
import { ClipboardCheck, Loader2 } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'

interface ApplicationRow {
  id: number
  target_role: string
  status: 'pending' | 'approved' | 'rejected'
  statement: string
  decision_note: string | null
  created_at: string | null
}

interface EligibilityEntry {
  accepted_papers?: number
  best_rqs?: number | null
  reviews_completed?: number
  already_role: boolean
  eligible: boolean
  // 仅 L6：是否已持有 L5 审稿人角色（L6 的硬前提）。
  has_reviewer_role?: boolean
  thresholds: Record<string, number>
}

interface ApplicationsMeResponse {
  applications: ApplicationRow[]
  eligibility: Record<'reviewer' | 'senior_reviewer', EligibilityEntry>
}

const ROLE_LABEL: Record<string, string> = {
  reviewer: '审稿人（L5）',
  senior_reviewer: '资深审稿人（L6）',
}

const STATUS_LABEL: Record<string, string> = {
  pending: '待审',
  approved: '已通过',
  rejected: '未通过',
}

async function fetchMyApplications(): Promise<ApplicationsMeResponse> {
  return (await api.get<ApplicationsMeResponse>('/gamification/applications/me')).data
}

/** 申请审稿人 / 资深审稿人：资格画像 + 提交 + 申请历史。 */
export function RoleApplicationsSection() {
  const { isAuthenticated } = useAuth()
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['gamification', 'applications-me'],
    queryFn: fetchMyApplications,
    enabled: isAuthenticated,
    staleTime: 30_000,
  })
  const [target, setTarget] = useState<'reviewer' | 'senior_reviewer' | null>(null)
  const [statement, setStatement] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!isAuthenticated) {
    return (
      <section>
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          <ClipboardCheck className="h-4 w-4" /> 申请审稿人
        </h2>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">登录后可申请</CardTitle>
            <CardDescription>
              L5 审稿人 / L6 资深审稿人走「申请 → 编辑部审批」；
              <Link to="/login" className="ml-1 text-primary hover:underline">
                去登录
              </Link>
            </CardDescription>
          </CardHeader>
        </Card>
      </section>
    )
  }

  const submit = async (role: 'reviewer' | 'senior_reviewer') => {
    if (statement.trim().length < 20) {
      toast.error('申请说明至少 20 字：写写你的研究背景与审稿意愿')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/gamification/applications', { target_role: role, statement: statement.trim() })
      toast.success('申请已提交，编辑部会在审核后通知你')
      setTarget(null)
      setStatement('')
      void qc.invalidateQueries({ queryKey: ['gamification', 'applications-me'] })
    } catch (err) {
      const detail = (
        err as { response?: { data?: { detail?: { message?: string } | string } } }
      ).response?.data?.detail
      const msg =
        typeof detail === 'object' && detail !== null ? detail.message : extractError(err, '提交失败')
      toast.error(msg ?? '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const renderTarget = (role: 'reviewer' | 'senior_reviewer') => {
    const e = data?.eligibility?.[role]
    if (!e) return null
    const pending = data?.applications.some((a) => a.target_role === role && a.status === 'pending')
    return (
      <div className="rounded-lg border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium">{ROLE_LABEL[role]}</p>
          {e.already_role ? (
            <Badge>已拥有</Badge>
          ) : pending ? (
            <Badge variant="outline">审核中</Badge>
          ) : e.eligible ? (
            <Badge variant="secondary">可申请</Badge>
          ) : (
            <Badge variant="outline">未达标</Badge>
          )}
        </div>
        <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
          {role === 'reviewer' ? (
            <>
              <li>
                已录用稿件：<span className="tabular-nums text-foreground">{e.accepted_papers ?? 0}</span>
                {' '}/ {e.thresholds?.accepted_papers ?? '—'} 篇
              </li>
              <li>
                最高质量分（RQS）：
                <span className="tabular-nums text-foreground">
                  {e.best_rqs != null ? Math.round(e.best_rqs) : '—'}
                </span>
                {' '}/ {e.thresholds?.best_rqs ?? '—'} 分（未评分稿件不参与门槛）
              </li>
            </>
          ) : (
            <>
              <li>
                已完成审稿：
                <span className="tabular-nums text-foreground">{e.reviews_completed ?? 0}</span>
                {' '}/ {e.thresholds.reviews_completed} 份
              </li>
              <li>
                L5 审稿人角色：
                <span className="tabular-nums text-foreground">
                  {e.has_reviewer_role ? '已拥有' : '未拥有'}
                </span>
                （L6 为 L5 之上的阶梯）
              </li>
            </>
          )}
        </ul>
        {!e.already_role && !pending && (
          <Button
            size="sm"
            className="mt-3"
            variant={e.eligible ? 'default' : 'outline'}
            disabled={!e.eligible || submitting}
            onClick={() => setTarget(role)}
          >
            {e.eligible ? '提交申请' : '资格未达标'}
          </Button>
        )}
        {target === role && (
          <div className="mt-3 space-y-2">
            <Textarea
              rows={4}
              value={statement}
              onChange={(ev) => setStatement(ev.target.value.slice(0, 2000))}
              placeholder="申请说明（至少 20 字）：你的研究方向、审稿经验或参与社区的情况。"
            />
            <div className="flex gap-2">
              <Button size="sm" disabled={submitting} onClick={() => void submit(role)}>
                {submitting ? (
                  <>
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> 提交中…
                  </>
                ) : (
                  '确认提交'
                )}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setTarget(null)}>
                取消
              </Button>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <ClipboardCheck className="h-4 w-4" /> 申请审稿人
      </h2>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">申请标准（冻结口径）</CardTitle>
          <CardDescription>
            满足标准即可申请，编辑部审批后授予角色并解锁对应工作台；L7–L9 编辑职不开放申请，由编辑部直接提拔。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载资格数据…</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {renderTarget('reviewer')}
              {renderTarget('senior_reviewer')}
            </div>
          )}
          {data && data.applications.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium">我的申请记录</p>
              <ul className="space-y-2">
                {data.applications.map((a) => (
                  <li key={a.id} className="rounded-md border p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">{ROLE_LABEL[a.target_role] ?? a.target_role}</span>
                      <Badge
                        variant={
                          a.status === 'approved'
                            ? 'default'
                            : a.status === 'rejected'
                              ? 'destructive'
                              : 'outline'
                        }
                      >
                        {STATUS_LABEL[a.status] ?? a.status}
                      </Badge>
                    </div>
                    {a.decision_note ? (
                      <p className="mt-1 text-xs text-muted-foreground">编辑部备注：{a.decision_note}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  )
}
