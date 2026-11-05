import { useState } from 'react'
import { createFileRoute, redirect, useNavigate, useSearch } from '@tanstack/react-router'
import { Check, Download, Eye, FileText, X } from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  downloadSubmissionFile,
  useAcceptAssignment,
  useDeclineAssignment,
  useMyReviewAssignments,
  useReviewSubmissionDetail,
  useSubmitReview,
} from '@/hooks/api/use-modules'
import type { AssignmentStatus, Recommendation, ReviewSubmit } from '@/lib/types'
import { typeLabel } from '@/lib/resource-labels'
import { extractError } from '@/lib/utils'
import { isSafeExternalUrl, safeHref } from '@/lib/url-safety'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
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
import { waitingChip } from '@/components/common/waiting-chip'

export const Route = createFileRoute('/review/assignments')({
  beforeLoad: () => {
    // 审稿工作台需要登录；具体 reviewer 角色由后端强制（403 由 UI 兜底）
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: ReviewWorkbenchPage,
})

interface ReviewSearch {
  status?: AssignmentStatus | 'all'
  page?: number
}

const STATUS_TABS: { value: AssignmentStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待回应' },
  { value: 'accepted', label: '已接受' },
  { value: 'declined', label: '已拒绝' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已撤销' },
]

const RECOMMENDATION_OPTIONS: { value: Recommendation; label: string }[] = [
  { value: 'accept', label: '接收（Accept）' },
  { value: 'minor_revision', label: '小修（Minor Revision）' },
  { value: 'major_revision', label: '大修（Major Revision）' },
  { value: 'reject', label: '拒稿（Reject）' },
]

// 与后端 RQS v3.0 的七个学术价值维度一一对应（rubric.py）。
// 旧的 originality/methodology/clarity/significance 四个临时维度已废弃——
// 它们与公开的评分口径对不上，导致"审稿人打分"与"文章页展示的 RQS"是
// 两套互不相干的数字。
const SCORE_DIMENSIONS = [
  { key: 'problem', label: '问题价值' },
  { key: 'argument', label: '论证链' },
  { key: 'method', label: '方法透明度' },
  { key: 'evidence', label: '证据强度' },
  { key: 'novelty', label: '创新与定位' },
  { key: 'integrity', label: '学术诚信' },
  { key: 'presentation', label: '表达与结构' },
]

function statusBadge(status: AssignmentStatus) {
  switch (status) {
    case 'pending':
      return <Badge variant="secondary">待回应</Badge>
    case 'accepted':
      return <Badge className="bg-primary/15 text-primary">已接受</Badge>
    case 'declined':
      return <Badge variant="outline">已拒绝</Badge>
    case 'completed':
      return <Badge className="bg-emerald-500/15 text-emerald-700">已完成</Badge>
    case 'cancelled':
      return <Badge variant="outline">已撤销</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

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

function ReviewWorkbenchPage() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as ReviewSearch
  const statusTab = (search.status ?? 'all') as AssignmentStatus | 'all'
  const page = search.page ?? 1
  const status = statusTab === 'all' ? undefined : statusTab

  const { data, isLoading, isError, refetch } = useMyReviewAssignments(
    status,
    page,
    20,
  )
  const acceptMut = useAcceptAssignment()
  const declineMut = useDeclineAssignment()
  const submitMut = useSubmitReview()

  const [reviewTargetId, setReviewTargetId] = useState<number | null>(null)
  const [reviewForm, setReviewForm] = useState<ReviewFormState>(EMPTY_REVIEW)
  const [declineTargetId, setDeclineTargetId] = useState<number | null>(null)
  // 查看稿件详情的 assignmentId（仅 pending/accepted/completed 可查）
  const [submissionViewId, setSubmissionViewId] = useState<number | null>(null)

  const updateSearch = (patch: Partial<ReviewSearch>) => {
    void navigate({
      to: '/review/assignments',
      search: { ...search, ...patch },
      replace: true,
    })
  }

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
        description="查看分配给您的审稿任务，接受邀请后填写审稿报告。"
      />

      <Tabs
        value={statusTab}
        onValueChange={(v) =>
          updateSearch({
            status: v as AssignmentStatus | 'all',
            page: 1,
          })
        }
      >
        <TabsList>
          {STATUS_TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="加载失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState
          title="暂无审稿任务"
          description="编辑分配审稿任务后会显示在这里。"
        />
      ) : (
        <div className="space-y-4">
          {data.data.map((a) => (
            <Card key={a.id}>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <h3 className="font-medium">
                    {a.submission_title ?? `#${a.submission_id}`}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {statusBadge(a.status)}
                    {(a.status === 'pending' || a.status === 'accepted') &&
                      waitingChip(a.invited_at, {
                        urgentAfterDays: 5,
                        urgentSuffix: ' · 请尽快',
                      })}
                    <span>邀请于 {new Date(a.invited_at).toLocaleString()}</span>
                    {a.due_date && (
                      <span>· 截止 {new Date(a.due_date).toLocaleString()}</span>
                    )}
                    {a.completed_at && (
                      <span>
                        · 完成于 {new Date(a.completed_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {/* 审稿人在 pending/accepted/completed 都可查看完整稿件（declined/cancelled 不可） */}
                  {['pending', 'accepted', 'completed'].includes(a.status) && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSubmissionViewId(a.id)}
                    >
                      <Eye className="h-4 w-4" /> 查看稿件
                    </Button>
                  )}
                  {a.status === 'pending' && (
                    <>
                      <Button
                        size="sm"
                        onClick={() => onAccept(a.id)}
                        disabled={acceptMut.isPending}
                      >
                        <Check className="h-4 w-4" /> 接受邀请
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDeclineTargetId(a.id)}
                        disabled={declineMut.isPending}
                      >
                        <X className="h-4 w-4" /> 拒绝
                      </Button>
                    </>
                  )}
                  {a.status === 'accepted' && (
                    <Button size="sm" onClick={() => openReviewForm(a.id)}>
                      <FileText className="h-4 w-4" /> 填写审稿报告
                    </Button>
                  )}
                  {a.status === 'completed' && (
                    <Badge variant="outline" className="gap-1">
                      <Eye className="h-3 w-3" /> 报告已提交
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          onPageChange={(p) => updateSearch({ page: p })}
        />
      )}

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
              <p className="text-[11px] text-muted-foreground">
                学术诚信为 0 分即全篇判 D（一票否决）。完整检查项与 0–5 锚点见
                「等级与规范」页。
              </p>
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
              <Label htmlFor="comments_to_editor">
                给编辑的保密意见（可选）
              </Label>
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

      {/* 稿件详情 Dialog —— 单盲剥离仅作用于作者侧的 review reports；
          审稿人需要看完整稿件（abstract / file_path / keywords / jel_codes） */}
      <SubmissionDetailDialog
        assignmentId={submissionViewId}
        onClose={() => setSubmissionViewId(null)}
      />
    </div>
  )
}

function SubmissionDetailDialog({
  assignmentId,
  onClose,
}: {
  assignmentId: number | null
  onClose: () => void
}) {
  const { data, isLoading, isError, error } = useReviewSubmissionDetail(
    assignmentId ?? 0,
  )
  return (
    <Dialog
      open={assignmentId !== null}
      onOpenChange={(o) => !o && onClose()}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>稿件详情</DialogTitle>
          <DialogDescription>
            完整稿件元数据；单盲模式下您的身份对作者保密。
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <LoadingSkeleton rows={4} />
        ) : isError ? (
          <ErrorState message={extractError(error, '加载稿件失败')} />
        ) : !data ? null : (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1 text-sm">
            <div>
              <h3 className="text-base font-semibold">{data.title}</h3>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge variant="secondary">{typeLabel(data.type)}</Badge>
                <Badge variant="outline">{data.discipline}</Badge>
                {data.subdiscipline && (
                  <Badge variant="outline">{data.subdiscipline}</Badge>
                )}
                <Badge variant="outline">状态：{data.status}</Badge>
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">作者</div>
              <div>{(data.authors ?? []).join(' · ') || '—'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">摘要</div>
              <p className="whitespace-pre-wrap leading-relaxed">
                {data.abstract || '—'}
              </p>
            </div>
            {data.preview && (
              <div>
                <div className="text-xs text-muted-foreground">预览</div>
                <p className="whitespace-pre-wrap text-muted-foreground">
                  {data.preview}
                </p>
              </div>
            )}
            {(data.keywords?.length ?? 0) > 0 && (
              <div>
                <div className="text-xs text-muted-foreground">关键词</div>
                <div className="flex flex-wrap gap-1">
                  {data.keywords.map((k) => (
                    <Badge key={k} variant="outline" className="text-xs">
                      {k}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {(data.jel_codes?.length ?? 0) > 0 && (
              <div>
                <div className="text-xs text-muted-foreground">JEL Codes</div>
                <div className="flex flex-wrap gap-1">
                  {data.jel_codes.map((c) => (
                    <Badge key={c} variant="outline" className="text-xs">
                      {c}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              {data.year && (
                <div>
                  <span className="text-muted-foreground">年份：</span>
                  {data.year}
                </div>
              )}
              {data.venue && (
                <div>
                  <span className="text-muted-foreground">期刊/会议：</span>
                  {data.venue}
                </div>
              )}
              {data.doi && (
                <div>
                  <span className="text-muted-foreground">DOI：</span>
                  {data.doi}
                </div>
              )}
              {data.corresponding_author_email && (
                <div>
                  <span className="text-muted-foreground">通讯邮箱：</span>
                  {data.corresponding_author_email}
                </div>
              )}
              {data.external_url && (
                <div className="col-span-2">
                  <span className="text-muted-foreground">外部链接：</span>
                  <a
                    // H1：作者可控外链走协议白名单，javascript: 等一律降级。
                    href={safeHref(data.external_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={
                      isSafeExternalUrl(data.external_url)
                        ? data.external_url
                        : '该链接协议不安全，已禁用'
                    }
                    aria-disabled={!isSafeExternalUrl(data.external_url)}
                    className="text-primary hover:underline"
                  >
                    {data.external_url}
                  </a>
                </div>
              )}
              {data.download_url && (
                <div className="col-span-2">
                  <span className="text-muted-foreground">下载链接：</span>
                  <a
                    // H1：作者可控外链走协议白名单，javascript: 等一律降级。
                    href={safeHref(data.download_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={
                      isSafeExternalUrl(data.download_url)
                        ? data.download_url
                        : '该链接协议不安全，已禁用'
                    }
                    aria-disabled={!isSafeExternalUrl(data.download_url)}
                    className="text-primary hover:underline"
                  >
                    {data.download_url}
                  </a>
                </div>
              )}
              {data.file_path && (
                <div className="col-span-2 flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground">已上传文件：</span>
                  <span className="break-all font-mono">{data.file_path}</span>
                  <button
                    type="button"
                    className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
                    onClick={() => void downloadSubmissionFile(data.id)}
                  >
                    <Download className="h-3.5 w-3.5" />
                    下载稿件
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
