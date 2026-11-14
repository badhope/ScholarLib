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
  useSubmissionDownloadTicket,
  useSubmitReview,
  useUploadReviewAttachment,
} from '@/hooks/api/use-modules'
import type { AssignmentStatus, ReviewSubmit } from '@/lib/types'
import { typeLabel } from '@/lib/resource-labels'
import { extractError } from '@/lib/utils'
import { isSafeExternalUrl, safeHref } from '@/lib/url-safety'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { MarkdownContent } from '@/components/common/markdown-content'
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

function SimilarityNotice({
  score,
  matches,
}: {
  score?: number | null
  matches?: Array<{ kind: 'resource' | 'submission'; id: number; title: string; score: number }>
}) {
  if (score == null || score < 35) return null
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/70 p-3 text-xs dark:bg-amber-950/20">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">站内相似度 {score.toFixed(1)} / 100</Badge>
        <span className="text-muted-foreground">
          {score >= 70 ? '高度重复，建议核对' : '建议核对'} · 仅比对本站资源与已接收投稿，不是 CNKI/CrossCheck 结论
        </span>
      </div>
      {(matches?.length ?? 0) > 0 ? (
        <ul className="mt-2 space-y-1">
          {matches!.slice(0, 3).map((m) => (
            <li key={`${m.kind}-${m.id}`} className="flex justify-between gap-3">
              <span className="min-w-0 truncate">
                {m.kind === 'resource' ? '已刊' : '投稿'}：{m.title}
              </span>
              <span className="shrink-0 tabular-nums">{m.score.toFixed(1)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

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
  const [mobilePane, setMobilePane] = useState<'manuscript' | 'form'>('manuscript')
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
    setMobilePane('manuscript')
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
        <DialogContent className="h-[100dvh] max-h-[100dvh] w-screen max-w-none overflow-hidden rounded-none p-0 sm:h-[96vh] sm:max-h-[96vh] sm:w-[96vw] sm:max-w-[96vw] sm:rounded-lg">
          <div className="flex h-full min-h-0 flex-col">
            <DialogHeader className="shrink-0 border-b px-5 py-4">
              <DialogTitle>审稿工作台</DialogTitle>
              <DialogDescription>
                电脑端左侧读稿、右侧打分；手机端在下方切换「读稿件 / 写评审」。
              </DialogDescription>
            </DialogHeader>
            <Tabs
              value={mobilePane}
              onValueChange={(v) => setMobilePane(v as 'manuscript' | 'form')}
              className="shrink-0 border-b px-4 py-2 lg:hidden"
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="manuscript">读稿件</TabsTrigger>
                <TabsTrigger value="form">写评审</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1fr)_440px] lg:overflow-hidden">
              <div
                className={`shrink-0 border-b px-5 py-4 lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-r ${
                  mobilePane === 'form' ? 'hidden lg:block' : ''
                }`}
              >
                {reviewTargetId !== null && (
                  <ReviewManuscriptPane assignmentId={reviewTargetId} />
                )}
              </div>
              <form
                onSubmit={onSubmitReview}
                className={`flex flex-col lg:min-h-0 ${
                  mobilePane === 'manuscript' ? 'hidden lg:flex' : ''
                }`}
              >
                <div className="space-y-4 px-4 py-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
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
                </div>
                <DialogFooter className="sticky bottom-0 flex-col border-t bg-background px-4 py-3 sm:flex-row">
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
            </div>
          </div>
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

function SubmissionDownloadLinks({
  submissionId,
  compact = false,
}: {
  submissionId: number
  compact?: boolean
}) {
  const pdfTicket = useSubmissionDownloadTicket(submissionId, 'pdf')
  const docxTicket = useSubmissionDownloadTicket(submissionId, 'docx')
  const isWeChat = /MicroMessenger/i.test(navigator.userAgent)
  const [wechatUrl, setWechatUrl] = useState<string | null>(null)

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      toast.success('下载链接已复制')
    } catch {
      const input = document.createElement('textarea')
      input.value = url
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
      toast.success('下载链接已复制')
    }
  }

  const link = (
    format: 'docx' | 'pdf',
    ticket: string | undefined,
  ) => {
    const label = format === 'pdf' ? '下载 PDF' : '下载 Word'
    const className = compact
      ? 'inline-flex shrink-0 items-center gap-1 text-primary hover:underline'
      : 'inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-2.5 text-sm font-medium hover:bg-muted'
    return (
      <a
        href={ticket ?? '#'}
        // 浏览器（含手机浏览器）一律按文件保存；只有微信不加 download，
        // 因为它不支持直接落盘，改走“浏览器打开”引导。
        download={!isWeChat}
        rel="noopener"
        className={className}
        onClick={(e) => {
          // 票据还没取到/取失败时回退到带 Authorization 的 Blob 下载。
          if (!ticket) {
            e.preventDefault()
            void downloadSubmissionFile(submissionId, format)
            return
          }
          // 微信内置浏览器不会直接保存 PDF，拦下来给可执行的打开方式。
          if (isWeChat) {
            e.preventDefault()
            setWechatUrl(ticket)
            void copyLink(ticket)
          }
        }}
      >
        <Download className={compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
        {label}
      </a>
    )
  }

  return (
    <>
      {link('docx', docxTicket.data)}
      {link('pdf', pdfTicket.data)}
      <Dialog
        open={wechatUrl !== null}
        onOpenChange={(open) => !open && setWechatUrl(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>微信里不能直接保存 PDF</DialogTitle>
            <DialogDescription>
              下载链接已复制。请点右上角「···」→「在浏览器打开」，粘贴到地址栏即可下载。
            </DialogDescription>
          </DialogHeader>
          <div className="break-all rounded-md bg-muted p-2 text-xs text-muted-foreground">
            {wechatUrl}
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => wechatUrl && void copyLink(wechatUrl)}
            >
              复制链接
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (wechatUrl) window.location.href = wechatUrl
              }}
            >
              仍然尝试打开
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function ReviewManuscriptPane({ assignmentId }: { assignmentId: number }) {
  const { data, isLoading, isError, error } = useReviewSubmissionDetail(assignmentId)
  if (isLoading) return <LoadingSkeleton rows={6} />
  if (isError) return <ErrorState message={extractError(error, '加载稿件失败')} />
  if (!data) return null
  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="text-lg font-semibold leading-snug">{data.title}</h3>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge variant="secondary">{typeLabel(data.type)}</Badge>
          <Badge variant="outline">{data.discipline}</Badge>
          {data.subdiscipline && <Badge variant="outline">{data.subdiscipline}</Badge>}
          <Badge variant="outline">状态：{data.status}</Badge>
        </div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">作者</div>
        <div>{(data.authors ?? []).join(' · ') || '—'}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">摘要</div>
        <p className="whitespace-pre-wrap leading-relaxed">{data.abstract || '—'}</p>
      </div>
      <SimilarityNotice score={data.similarity_score} matches={data.similarity_matches} />
      {data.manuscript_body ? (
        <div>
          <div className="mb-1 text-xs text-muted-foreground">
            正文（双盲稿已自动隐藏作者姓名与邮箱）
          </div>
          <div className="max-h-[55vh] overflow-y-auto rounded-md border bg-muted/20 p-3">
            <MarkdownContent text={data.manuscript_body} className="text-sm leading-relaxed" />
          </div>
        </div>
      ) : data.preview ? (
        <div>
          <div className="text-xs text-muted-foreground">正文预览（完整正文请打开下方 PDF/Word）</div>
          <p className="whitespace-pre-wrap leading-relaxed text-muted-foreground">
            {data.preview}
          </p>
        </div>
      ) : null}
      {(data.keywords?.length ?? 0) > 0 && (
        <div>
          <div className="text-xs text-muted-foreground">关键词</div>
          <div className="mt-1 flex flex-wrap gap-1">
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
          <div className="mt-1 flex flex-wrap gap-1">
            {data.jel_codes.map((c) => (
              <Badge key={c} variant="outline" className="text-xs">
                {c}
              </Badge>
            ))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-2 border-t pt-3">
        <SubmissionDownloadLinks submissionId={data.id} />
      </div>
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
          <div className="space-y-4 pr-1 text-sm">
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
            <SimilarityNotice score={data.similarity_score} matches={data.similarity_matches} />
            {data.manuscript_body ? (
              <div>
                <div className="mb-1 text-xs text-muted-foreground">
            正文（双盲稿已自动隐藏作者姓名与邮箱）
          </div>
                <div className="max-h-[55vh] overflow-y-auto rounded-md border bg-muted/20 p-3">
                  <MarkdownContent text={data.manuscript_body} className="text-sm leading-relaxed" />
                </div>
              </div>
            ) : data.preview ? (
              <div>
                <div className="text-xs text-muted-foreground">
                  正文预览（完整正文请用下方 PDF/Word 打开）
                </div>
                <p className="whitespace-pre-wrap text-muted-foreground">
                  {data.preview}
                </p>
              </div>
            ) : null}
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
                  <SubmissionDownloadLinks submissionId={data.id} compact />
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
