import { useState } from 'react'
import { createFileRoute, redirect } from '@tanstack/react-router'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Gavel,
  Send,
  UserPlus,
} from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  useBatchAssign,
  useCheckConflicts,
  useEditorDecision,
  useEditorWorkbench,
  useRemindReviewers,
  useReviewerCandidates,
  type ConflictCandidate,
} from '@/hooks/api/use-modules'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export const Route = createFileRoute('/editor/workbench')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: EditorWorkbenchPage,
})

type ColumnKey = 'to_assign' | 'in_review' | 'to_decide' | 'decided'

const COLUMN_META: { key: ColumnKey; title: string; accent: string }[] = [
  { key: 'to_assign', title: '待指派', accent: 'bg-slate-100 text-slate-700 dark:bg-slate-800' },
  { key: 'in_review', title: '评审中', accent: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40' },
  { key: 'to_decide', title: '待裁决', accent: 'bg-amber-100 text-amber-800 dark:bg-amber-950/40' },
  { key: 'decided', title: '已决定', accent: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40' },
]

function EditorWorkbenchPage() {
  const { data, isLoading, isError, refetch } = useEditorWorkbench()
  const candidates = useReviewerCandidates(200)
  const batchMut = useBatchAssign()
  const conflictsMut = useCheckConflicts()
  const remindMut = useRemindReviewers()
  const decisionMut = useEditorDecision()

  // 待指派勾选
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [assignOpen, setAssignOpen] = useState(false)
  const [selectedReviewers, setSelectedReviewers] = useState<number[]>([])
  const [dueDays, setDueDays] = useState(14)
  const [conflicts, setConflicts] = useState<Record<number, ConflictCandidate>>({})

  // 待裁决：当前正在裁决的稿件 id
  const [decidingId, setDecidingId] = useState<number | null>(null)
  const [decision, setDecision] = useState<'accept' | 'minor_revision' | 'major_revision' | 'reject'>('major_revision')
  const [editorNote, setEditorNote] = useState('')

  const columns = data?.columns

  const toggleCheck = (id: number) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openAssignDialog = async () => {
    if (checked.size === 0) {
      toast.info('请先勾选至少一篇待指派稿件')
      return
    }
    setAssignOpen(true)
    setSelectedReviewers([])
    setConflicts({})
    // 对第一篇勾选稿件跑一次冲突检查（多稿件时共用候选名单；冲突提示以该稿件为准）
    const firstSubId = [...checked][0]
    if (candidates.data && candidates.data.length) {
      try {
        const res = await conflictsMut.mutateAsync({
          submission_id: firstSubId,
          reviewer_ids: candidates.data.map((c) => c.id),
        })
        const map: Record<number, ConflictCandidate> = {}
        for (const c of res.candidates) map[c.reviewer_id] = c
        setConflicts(map)
      } catch (err) {
        // 冲突接口失败不阻塞指派，仅静默降级
        console.warn('conflicts check failed', err)
      }
    }
  }

  const onToggleReviewer = (id: number) => {
    setSelectedReviewers((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const onBatchAssign = async () => {
    if (selectedReviewers.length === 0) {
      toast.info('请至少选择一位审稿人')
      return
    }
    try {
      const res = await batchMut.mutateAsync({
        items: [...checked].map((submission_id) => ({
          submission_id,
          reviewer_ids: selectedReviewers,
        })),
        due_days: dueDays,
      })
      toast.success(`已指派 ${res.created_count} 条审稿任务`)
      if (res.skipped.length > 0) {
        toast.warning(`跳过 ${res.skipped.length} 条（自审/状态不符）`)
      }
      setAssignOpen(false)
      setChecked(new Set())
    } catch (err) {
      toast.error(extractError(err, '指派失败'))
    }
  }

  const onRemind = async (assignmentIds: number[]) => {
    if (assignmentIds.length === 0) return
    try {
      const res = await remindMut.mutateAsync({ assignment_ids: assignmentIds })
      toast.success(`已催审 ${res.reminded_count} 位审稿人`)
    } catch (err) {
      toast.error(extractError(err, '催审失败'))
    }
  }

  const onDecide = async () => {
    if (decidingId === null) return
    try {
      await decisionMut.mutateAsync({
        id: decidingId,
        body: { decision, editor_note: editorNote || undefined },
      })
      toast.success('已记录编辑决定')
      setDecidingId(null)
      setEditorNote('')
    } catch (err) {
      toast.error(extractError(err, '裁决失败'))
    }
  }

  const openDecide = (submissionId: number) => {
    setDecidingId(submissionId)
    setDecision('major_revision')
    setEditorNote('')
  }

  return (
    <div>
      <PageHeader
        title="主编工作台"
        description="四栏流水线：待指派 → 评审中 → 待裁决 → 已决定。"
      />

      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="加载失败" onRetry={() => refetch()} />
      ) : !columns ? (
        <EmptyState title="暂无数据" />
      ) : (
        <>
          {/* 桌面四列 / 移动横向滚动 */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {COLUMN_META.map((col) => {
              const bucket = columns[col.key]
              return (
                <div key={col.key} className="space-y-2">
                  <div
                    className={`flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium ${col.accent}`}
                  >
                    <span>{col.title}</span>
                    <Badge variant="secondary">{bucket.count}</Badge>
                  </div>
                  {bucket.items.length === 0 ? (
                    <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                      — 空 —
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {bucket.items.map((item) => (
                        <Card
                          key={item.submission_id}
                          className={
                            item.is_overdue
                              ? 'border-red-400 bg-red-50/50 dark:bg-red-950/10'
                              : undefined
                          }
                        >
                          <CardContent className="space-y-2 py-3 text-sm">
                            <div className="flex items-start gap-2">
                              {col.key === 'to_assign' && (
                                <input
                                  type="checkbox"
                                  checked={checked.has(item.submission_id)}
                                  onChange={() => toggleCheck(item.submission_id)}
                                  className="mt-1 h-4 w-4 shrink-0"
                                />
                              )}
                              <div className="min-w-0 flex-1">
                                <p className="truncate font-medium">
                                  {item.title ?? `#${item.submission_id}`}
                                </p>
                                <p className="mt-0.5 text-xs text-muted-foreground">
                                  {item.type ?? '未分类'} · 提交于{' '}
                                  {new Date(item.submitted_at).toLocaleDateString()}
                                </p>
                              </div>
                            </div>

                            {col.key === 'in_review' && item.assignments && (
                              <div className="space-y-1 border-t pt-2 text-xs">
                                {item.assignments.map((a) => (
                                  <div
                                    key={a.assignment_id}
                                    className={`flex items-center justify-between gap-2 rounded px-1 py-0.5 ${
                                      a.is_overdue
                                        ? 'bg-red-100/70 text-red-700 dark:bg-red-950/30'
                                        : ''
                                    }`}
                                  >
                                    <span className="truncate">
                                      {a.reviewer_username ?? `#${a.reviewer_id}`}
                                      {a.status === 'completed' ? ' · 已交' : ' · 未交'}
                                    </span>
                                    <span className="flex shrink-0 items-center gap-1">
                                      {a.due_label && (
                                        <span
                                          className={
                                            a.is_overdue
                                              ? 'font-semibold text-red-600'
                                              : 'text-muted-foreground'
                                          }
                                        >
                                          <Clock className="inline h-3 w-3" /> {a.due_label}
                                        </span>
                                      )}
                                      {!a.completed_at && (
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          className="h-6 px-1 text-[10px]"
                                          onClick={() => onRemind([a.assignment_id])}
                                          disabled={remindMut.isPending}
                                        >
                                          <Send className="h-3 w-3" /> 催
                                        </Button>
                                      )}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}

                            {col.key === 'to_decide' && item.recommendations && (
                              <div className="space-y-1 border-t pt-2 text-xs">
                                {item.recommendations.map((r) => (
                                  <div key={r.reviewer_id} className="flex items-center gap-2">
                                    <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                                    <span>审稿人 #{r.reviewer_id}</span>
                                    <Badge variant="outline">{r.recommendation ?? '—'}</Badge>
                                  </div>
                                ))}
                                <Button
                                  size="sm"
                                  className="mt-1 w-full"
                                  onClick={() => openDecide(item.submission_id)}
                                >
                                  <Gavel className="h-3 w-3" /> 裁决
                                </Button>
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* 底部批量指派条 */}
          {columns.to_assign.count > 0 && (
            <div className="sticky bottom-4 mt-6 flex items-center justify-between rounded-lg border bg-card px-4 py-3 shadow">
              <span className="text-sm text-muted-foreground">
                已勾选 <span className="font-semibold">{checked.size}</span> / {columns.to_assign.count} 篇
              </span>
              <Button
                onClick={openAssignDialog}
                disabled={checked.size === 0 || batchMut.isPending}
              >
                <UserPlus className="h-4 w-4" /> 批量指派
              </Button>
            </div>
          )}
        </>
      )}

      {/* 批量指派弹层 */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>批量指派审稿人</DialogTitle>
            <DialogDescription>
              已选 {checked.size} 篇稿件。黄色警告为利益冲突项，默认不选。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="max-h-72 space-y-1 overflow-y-auto rounded border p-2">
              {(candidates.data ?? []).map((c) => {
                const conflict = conflicts[c.id]
                const warned = conflict?.warning
                const disabled = conflict?.is_submitter || conflict?.name_matches_author
                return (
                  <label
                    key={c.id}
                    className={`flex items-start gap-2 rounded px-2 py-1.5 text-sm ${
                      warned ? 'bg-amber-50 dark:bg-amber-950/20' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedReviewers.includes(c.id)}
                      onChange={() => onToggleReviewer(c.id)}
                      disabled={disabled}
                      className="mt-0.5 h-4 w-4 shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span>{c.username}</span>
                        {warned && (
                          <Badge variant="outline" className="text-amber-700">
                            <AlertTriangle className="h-3 w-3" /> 冲突
                          </Badge>
                        )}
                      </div>
                      {conflict?.warnings && conflict.warnings.length > 0 && (
                        <ul className="mt-1 list-disc pl-4 text-[11px] text-amber-700">
                          {conflict.warnings.map((w) => (
                            <li key={w}>{w}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </label>
                )
              })}
            </div>
            <div className="flex items-center gap-3">
              <Label htmlFor="due-days" className="shrink-0">
                截止天数
              </Label>
              <Input
                id="due-days"
                type="number"
                min={1}
                max={90}
                value={dueDays}
                onChange={(e) => setDueDays(Number(e.target.value) || 14)}
                className="w-24"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>
              取消
            </Button>
            <Button onClick={onBatchAssign} disabled={batchMut.isPending || selectedReviewers.length === 0}>
              {batchMut.isPending ? '指派中…' : `指派给 ${selectedReviewers.length} 位审稿人`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 裁决弹层 */}
      <Dialog
        open={decidingId !== null}
        onOpenChange={(o) => !o && setDecidingId(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑裁决</DialogTitle>
            <DialogDescription>稿件 #{decidingId}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>决定</Label>
              <Select
                value={decision}
                onValueChange={(v) => setDecision(v as typeof decision)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="accept">录用（Accept）</SelectItem>
                  <SelectItem value="minor_revision">小修（Minor Revision）</SelectItem>
                  <SelectItem value="major_revision">大修（Major Revision）</SelectItem>
                  <SelectItem value="reject">拒稿（Reject）</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="editor-note">给作者的说明（可选）</Label>
              <Input
                id="editor-note"
                value={editorNote}
                onChange={(e) => setEditorNote(e.target.value)}
                placeholder="将随决定通知发送给作者"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDecidingId(null)}>
              取消
            </Button>
            <Button onClick={onDecide} disabled={decisionMut.isPending}>
              {decisionMut.isPending ? '提交中…' : '提交决定'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
