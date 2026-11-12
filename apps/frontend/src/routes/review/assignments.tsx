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
  useUploadReviewAttachment,
} from '@/hooks/api/use-modules'
import type { AssignmentStatus, ReviewSubmit } from '@/lib/types'
import { typeLabel } from '@/lib/resource-labels'
import { extractError } from '@/lib/utils'
import { isSafeExternalUrl, safeHref } from '@/lib/url-safety'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'
import {
  ReviewAttachmentLinks,
  ReviewAttachmentPicker,
  ReviewAttachmentUploadButton,
} from '@/components/common/review-attachments'
import {
  EMPTY_REVIEW_FORM,
  ReviewReportFields,
  type ReviewFormValue,
} from '@/components/review/review-report-fields'
import {
  TRACK_DIMENSIONS,
  dimensionIssue,
  scoreReviewTotal,
} from '@/components/review/rubric-score-fields'
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
  const uploadAttachmentMut = useUploadReviewAttachment()

  const [reviewTargetId, setReviewTargetId] = useState<number | null>(null)
  const [reviewForm, setReviewForm] = useState<ReviewFormValue>(EMPTY_REVIEW_FORM)
  const [reviewAttachments, setReviewAttachments] = useState<File[]>([])
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
    setReviewForm(EMPTY_REVIEW_FORM)
    setReviewAttachments([])
    setReviewTargetId(id)
  }

  const onSubmitReview = async (e: React.FormEvent) => {
    e.preventDefault()
    if (reviewTargetId === null) return
    if (reviewForm.special_issue && reviewForm.special_issue_reason.trim().length < 10) {
      toast.error('勾选「特别篇」后必须填写不少于 10 字的理由')
      return
    }
    const dims = TRACK_DIMENSIONS[reviewForm.track]
    const incomplete = dims
      .filter((d) => dimensionIssue(d, reviewForm.dimensions[d.key]) !== null)
      .map((d) => `${d.label}（${dimensionIssue(d, reviewForm.dimensions[d.key])}）`)
    if (incomplete.length) {
      toast.error(`还有 ${incomplete.length} 个维度未完成：${incomplete.join('、')}`)
      return
    }
    const summary = scoreReviewTotal(reviewForm.track, reviewForm.dimensions)
    const body: ReviewSubmit = {
      recommendation: reviewForm.recommendation,
      scores: {
        rubric_version: '5.0',
        track: reviewForm.track,
        dimensions: Object.fromEntries(
          dims.map((d) => [
            d.key,
            {
              score: reviewForm.dimensions[d.key]?.score,
              reason: reviewForm.dimensions[d.key]?.reason.trim(),
              evidence: reviewForm.dimensions[d.key]?.evidence.trim(),
            },
          ]),
        ),
        score: summary.total,
        grade: summary.grade,
      },
      comments_to_editor: reviewForm.comments_to_editor || undefined,
      comments_to_author: reviewForm.comments_to_author || undefined,
      special_issue: reviewForm.special_issue || undefined,
      special_issue_reason: reviewForm.special_issue
        ? reviewForm.special_issue_reason || '审稿人确认篇幅特许'
        : undefined,
    }
    try {
      const report = await submitMut.mutateAsync({ id: reviewTargetId, body })
      let attachmentError: unknown = null
      for (const file of reviewAttachments) {
        try {
          await uploadAttachmentMut.mutateAsync({ reportId: report.id, file })
        } catch (err) {
          attachmentError = err
          break
        }
      }
      if (attachmentError) {
        toast.warning(
          `审稿报告已提交，但附件上传失败：${extractError(attachmentError, '请到已完成任务里补传')}`,
        )
      } else {
        toast.success(
          reviewAttachments.length
            ? `审稿报告与 ${reviewAttachments.length} 个附件已提交`
            : '审稿报告已提交',
        )
      }
      setReviewTargetId(null)
      setReviewAttachments([])
    } catch (err) {
      toast.error(extractError(err, '提交失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="审稿工作台"
        description="填写审稿报告：先过四问，再按七个维度逐项打分；意见支持 Markdown 与预览，提交前可看作者/编辑两个视角。稿件默认下载 Word，也可切换 PDF。"
      />

      <div className="mb-4 rounded-md border border-dashed bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
        <span className="mr-2 font-medium text-foreground">评审依据与版式要求：</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-submission-template.docx" download>
          Word 模板
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-submission-template-word.md" download>
          Word 排版要求
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-editorial-standards.md" download>
          编辑规范
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/authors">
          投稿指南
        </a>
        <div className="mt-1">审稿时请按上述版式与编辑规范核对结构、图表题注、参考文献和篇幅分档。</div>
      </div>

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
                {a.status === 'completed' && a.report_id && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 border-t pt-2">
                    <ReviewAttachmentLinks
                      reportId={a.report_id}
                      attachments={a.attachments}
                    />
                    <ReviewAttachmentUploadButton
                      reportId={a.report_id}
                      onUploaded={() => void refetch()}
                    />
                  </div>
                )}
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
        <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>填写审稿报告</DialogTitle>
          </DialogHeader>
          <form onSubmit={onSubmitReview} className="space-y-4">
            <ReviewReportFields
              value={reviewForm}
              onChange={setReviewForm}
              disabled={submitMut.isPending}
            />

            <ReviewAttachmentPicker
              files={reviewAttachments}
              onChange={setReviewAttachments}
              disabled={submitMut.isPending}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setReviewTargetId(null)}
              >
                取消
              </Button>
              <Button
                type="submit"
                disabled={
                  submitMut.isPending ||
                  (reviewForm.special_issue && reviewForm.special_issue_reason.trim().length < 10)
                }
              >
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
                    onClick={() => void downloadSubmissionFile(data.id, 'docx')}
                  >
                    <Download className="h-3.5 w-3.5" />
                    下载 Word
                  </button>
                  <button
                    type="button"
                    className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
                    onClick={() => void downloadSubmissionFile(data.id, 'pdf')}
                  >
                    <Download className="h-3.5 w-3.5" />
                    下载 PDF
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
