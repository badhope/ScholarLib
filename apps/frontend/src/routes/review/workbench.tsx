import { useState } from 'react'
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { Check, Clock, FileText, X } from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  useAcceptAssignment,
  useDeclineAssignment,
  useReviewerWorkbench,
  useSubmitReview,
} from '@/hooks/api/use-modules'
import type { Recommendation, ReviewSubmit } from '@/lib/types'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/review/workbench')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: ReviewerWorkbenchPage,
})

const RECOMMENDATION_OPTIONS: { value: Recommendation; label: string }[] = [
  { value: 'accept', label: '接收（Accept）' },
  { value: 'minor_revision', label: '小修（Minor Revision）' },
  { value: 'major_revision', label: '大修（Major Revision）' },
  { value: 'reject', label: '拒稿（Reject）' },
]

// 与后端 RQS v3.0 的七个学术价值维度一一对应（rubric.py）。
const SCORE_DIMENSIONS = [
  { key: 'problem', label: '问题价值' },
  { key: 'argument', label: '论证链' },
  { key: 'method', label: '方法透明度' },
  { key: 'evidence', label: '证据强度' },
  { key: 'novelty', label: '创新与定位' },
  { key: 'integrity', label: '学术诚信' },
  { key: 'presentation', label: '表达与结构' },
]

interface ReviewFormState {
  recommendation: Recommendation
  scores: Record<string, number>
  comments_to_editor: string
  comments_to_author: string
}

const EMPTY_REVIEW: ReviewFormState = {
  recommendation: 'minor_revision',
  scores: {
    problem: 3,
    argument: 3,
    method: 3,
    evidence: 3,
    novelty: 3,
    integrity: 5,
    presentation: 3,
  },
  comments_to_editor: '',
  comments_to_author: '',
}

type TabKey = 'pending' | 'completed'

function ReviewerWorkbenchPage() {
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useReviewerWorkbench()
  const acceptMut = useAcceptAssignment()
  const declineMut = useDeclineAssignment()
  const submitMut = useSubmitReview()

  const [tab, setTab] = useState<TabKey>('pending')
  const [reviewTargetId, setReviewTargetId] = useState<number | null>(null)
  const [reviewForm, setReviewForm] = useState<ReviewFormState>(EMPTY_REVIEW)
  const [declineTargetId, setDeclineTargetId] = useState<number | null>(null)

  const pendingCount = data?.pending.count ?? 0
  const completedCount = data?.completed.count ?? 0
  const items =
    tab === 'pending'
      ? data?.pending.items ?? []
      : data?.completed.items ?? []

  const onAccept = async (id: number) => {
    try {
      await acceptMut.mutateAsync(id)
      toast.success('已接受审稿邀请')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const onConfirmDecline = async () => {
    if (declineTargetId === null) return
    const id = declineTargetId
    setDeclineTargetId(null)
    try {
      await declineMut.mutateAsync(id)
      toast.success('已拒绝邀请')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  const openReviewForm = (id: number) => {
    setReviewForm(EMPTY_REVIEW)
    setReviewTargetId(id)
  }

  const onSubmitReview = async (e: React.FormEvent) => {
    e.preventDefault()
    if (reviewTargetId === null) return
    const body: ReviewSubmit = {
      recommendation: reviewForm.recommendation,
      scores: reviewForm.scores,
      comments_to_editor: reviewForm.comments_to_editor || undefined,
      comments_to_author: reviewForm.comments_to_author || undefined,
    }
    try {
      await submitMut.mutateAsync({ id: reviewTargetId, body })
      toast.success('审稿报告已提交')
      setReviewTargetId(null)
    } catch (err) {
      toast.error(extractError(err, '提交失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="审稿工作台"
        description="您的待审与已审任务。超期稿件会标红，请优先处理。"
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <TabsList>
          <TabsTrigger value="pending">
            待审 <span className="ml-1 text-xs">({pendingCount})</span>
          </TabsTrigger>
          <TabsTrigger value="completed">
            已审 <span className="ml-1 text-xs">({completedCount})</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="mt-4">
        {isLoading ? (
          <LoadingSkeleton rows={3} />
        ) : isError ? (
          <ErrorState message="加载失败" onRetry={() => refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={tab === 'pending' ? '暂无待审任务' : '暂无已审稿件'}
            description={
              tab === 'pending'
                ? '编辑分配审稿任务后会出现在这里。'
                : '您提交的审稿报告会显示在这里。'
            }
          />
        ) : (
          <div className="space-y-3">
            {items.map((a) => {
              const overdue = a.is_overdue
              return (
                <Card
                  key={a.assignment_id}
                  className={
                    overdue
                      ? 'border-red-400 bg-red-50/50 dark:bg-red-950/10'
                      : undefined
                  }
                >
                  <CardContent className="space-y-2 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <h3 className="font-medium">
                          {a.title ?? `#${a.submission_id}`}
                        </h3>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          {a.type && <Badge variant="secondary">{a.type}</Badge>}
                          <span>指派于 {new Date(a.invited_at).toLocaleString()}</span>
                          {a.due_label && (
                            <span
                              className={
                                overdue
                                  ? 'inline-flex items-center gap-1 font-semibold text-red-600'
                                  : 'inline-flex items-center gap-1'
                              }
                            >
                              <Clock className="h-3 w-3" />
                              {a.due_label}
                            </span>
                          )}
                          {tab === 'completed' && a.recommendation && (
                            <Badge variant="outline">
                              结论：{a.recommendation}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {tab === 'pending' && (
                          <>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => navigate({
                                to: '/review/assignments',
                                search: { status: 'pending' },
                              })}
                            >
                              查看稿件
                            </Button>
                            {a.status === 'pending' ? (
                              <>
                                <Button
                                  size="sm"
                                  onClick={() => onAccept(a.assignment_id)}
                                  disabled={acceptMut.isPending}
                                >
                                  <Check className="h-4 w-4" /> 接受
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setDeclineTargetId(a.assignment_id)}
                                >
                                  <X className="h-4 w-4" /> 拒绝
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                onClick={() => openReviewForm(a.assignment_id)}
                              >
                                <FileText className="h-4 w-4" /> 填写审稿报告
                              </Button>
                            )}
                          </>
                        )}
                        {tab === 'completed' && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => navigate({
                              to: '/review/assignments',
                              search: { status: 'completed' },
                            })}
                          >
                            查看报告
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>

      {/* 审稿报告 Dialog */}
      <Dialog
        open={reviewTargetId !== null}
        onOpenChange={(o) => !o && setReviewTargetId(null)}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>填写审稿报告</DialogTitle>
          </DialogHeader>
          <form onSubmit={onSubmitReview} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="recommendation">推荐决定</Label>
              <Select
                value={reviewForm.recommendation}
                onValueChange={(v) =>
                  setReviewForm((prev) => ({
                    ...prev,
                    recommendation: v as Recommendation,
                  }))
                }
              >
                <SelectTrigger id="recommendation" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RECOMMENDATION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>评分（1–5）· 对应公开的 RQS v3.0 七个维度</Label>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {SCORE_DIMENSIONS.map((dim) => (
                  <div key={dim.key} className="space-y-1">
                    <Label htmlFor={`score-${dim.key}`} className="text-xs">
                      {dim.label}
                    </Label>
                    <Select
                      value={String(reviewForm.scores[dim.key] ?? 3)}
                      onValueChange={(v) =>
                        setReviewForm((prev) => ({
                          ...prev,
                          scores: { ...prev.scores, [dim.key]: Number(v) },
                        }))
                      }
                    >
                      <SelectTrigger id={`score-${dim.key}`} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <SelectItem key={n} value={String(n)}>
                            {n}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="comments_to_author">给作者的意见</Label>
              <Textarea
                id="comments_to_author"
                value={reviewForm.comments_to_author}
                onChange={(e) =>
                  setReviewForm((prev) => ({
                    ...prev,
                    comments_to_author: e.target.value,
                  }))
                }
                placeholder="作者可见（单盲模式：作者看不到您的身份）"
                rows={4}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="comments_to_editor">给编辑的保密意见（可选）</Label>
              <Textarea
                id="comments_to_editor"
                value={reviewForm.comments_to_editor}
                onChange={(e) =>
                  setReviewForm((prev) => ({
                    ...prev,
                    comments_to_editor: e.target.value,
                  }))
                }
                placeholder="仅编辑可见，作者看不到"
                rows={3}
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setReviewTargetId(null)}
              >
                取消
              </Button>
              <Button type="submit" disabled={submitMut.isPending}>
                {submitMut.isPending ? '提交中…' : '提交审稿报告'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 拒绝确认 */}
      <Dialog
        open={declineTargetId !== null}
        onOpenChange={(o) => !o && setDeclineTargetId(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>拒绝审稿邀请</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            拒绝后将无法再为该稿件提交审稿意见。确认拒绝吗？
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeclineTargetId(null)}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={onConfirmDecline}
              disabled={declineMut.isPending}
            >
              {declineMut.isPending ? '处理中…' : '确认拒绝'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
