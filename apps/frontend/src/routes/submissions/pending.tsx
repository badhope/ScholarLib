import { useState } from 'react'
import { createFileRoute, Link, redirect, useNavigate, useSearch } from '@tanstack/react-router'
import {
  ClipboardList,
  Download,
  Eye,
  FileText,
  Gavel,
  Save,
  ShieldCheck,
  UserPlus,
} from 'lucide-react'
import { toast } from 'sonner'
import { waitingChip } from '@/components/common/waiting-chip'
import { getAuthState } from '@/lib/auth'
import { normalizeAbstract } from '@/lib/abstract'
import { useAuth } from '@/hooks/use-auth'
import {
  downloadSubmissionFile,
  useAllSubmissions,
  useAssignAdjudicator,
  useAssignReviewersBulk,
  useCancelAssignment,
  useEditorDecision,
  useSetAnonymizedFile,
  useSubmissionAssignments,
  useSubmissionReports,
  useSubmissionVersions,
  useReviewMatrix,
  useReviewerCandidates,
  usePutAuthors,
} from '@/hooks/api/use-modules'
import type {
  AssignmentResponse,
  AuthorEditInput,
  EditorDecision,
  ReviewMatrixResponse,
  ReviewReportResponse,
  SubmissionResponse,
  SubmissionStatus,
} from '@/lib/types'
import { typeLabel } from '@/lib/resource-labels'
import { extractError, formatDateTime } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { useRequestRework } from '@/hooks/api/use-modules'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { AuthorEditor } from '@/components/common/author-editor'
import { ReviewAttachmentLinks } from '@/components/common/review-attachments'
import {
  Dialog,
  DialogContent,
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

// 指派审稿人时取多少候选。超出时 UI 会明确提示"只取了前 N 个"，
// 避免目标审稿人只是没被列出来却被当成"不存在"。
const REVIEWER_CANDIDATE_LIMIT = 200

export const Route = createFileRoute('/submissions/pending')({
  beforeLoad: () => {
    // 初筛工作台对 editor / section_editor / admin 开放；具体权限由后端
    // require_editor 强制，这里只挡掉完全无关的访客与普通作者。
    const { isAuthenticated, isAdmin, user } = getAuthState()
    if (!isAuthenticated) throw redirect({ to: '/login' })
    const roles = user?.roles ?? []
    if (!isAdmin && !roles.some((r) => ['editor', 'section_editor', 'editor_in_chief'].includes(r))) {
      throw redirect({ to: '/dashboard' })
    }
  },
  component: PendingSubmissionsPage,
})

const DECISION_OPTIONS: { value: EditorDecision; label: string; hint?: string }[] = [
  { value: 'accept', label: '接收（Accept）', hint: '自动入目录' },
  { value: 'minor_revision', label: '小修（Minor Revision）' },
  { value: 'major_revision', label: '大修（Major Revision）' },
  { value: 'reject', label: '拒稿（Reject）' },
]

// 审稿评分维度显示用中文（与 评审质量分 七维口径一致，见 quality/rubric.py；
// 旧四维 originality/methodology/clarity/significance 已废弃，编辑在新维度
// key 上不再回退显示英文原文）
const SCORE_LABELS: Record<string, string> = {
  question: '选题与真问题',
  argument: '论证与自洽',
  method: '方法与可复现',
  evidence: '证据与结论',
  integrity: '规范与诚信',
  concept: '荒诞设定与原创',
  coherence: '内部自洽',
  execution: '一本正经的执行',
  material: '材料与梗的可核查',
  voice: '文风与节奏',
  problem: '问题价值',
  novelty: '创新与定位',
  presentation: '表达清晰度',
  // 历史数据兜底：老报告里存的旧四维 key 仍能显示中文
  originality: '原创性（旧）',
  methodology: '方法学（旧）',
  clarity: '清晰度（旧）',
  significance: '重要性（旧）',
}


type ReportDimensionView = { score?: number; reason?: string; evidence?: string }

/** 兼容 v5 结构（scores.dimensions）与旧报告（scores 直接是数字）。 */
function reportDimensionEntries(scores: Record<string, unknown>): [string, ReportDimensionView][] {
  const dims = scores?.dimensions
  if (dims && typeof dims === 'object' && !Array.isArray(dims)) {
    return Object.entries(dims as Record<string, ReportDimensionView>)
  }
  return Object.entries(scores ?? {})
    .filter(([, value]) => typeof value === 'number')
    .map(([key, value]) => [key, { score: value as number }])
}

// 初筛工作台状态 tab：全部 + 7 种 submission status
type StatusTab = SubmissionStatus | 'all'
const STATUS_TABS: { value: StatusTab; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待分配' },
  { value: 'under_review', label: '审稿中' },
  { value: 'major_revision', label: '大修' },
  { value: 'minor_revision', label: '小修' },
  { value: 'resubmitted', label: '重投' },
  { value: 'accepted', label: '已接收' },
  { value: 'rejected', label: '已拒稿' },
]

interface PendingSearch {
  status?: StatusTab
  page?: number
}

function statusBadge(status: string) {
  switch (status) {
    case 'pending':
      return <Badge variant="secondary">待分配</Badge>
    case 'under_review':
      return <Badge className="bg-primary/15 text-primary">审稿中</Badge>
    case 'major_revision':
      return <Badge className="bg-amber-500/15 text-amber-700">大修</Badge>
    case 'minor_revision':
      return <Badge className="bg-yellow-500/15 text-yellow-700">小修</Badge>
    case 'accepted':
    case 'approved':
      return <Badge className="bg-emerald-500/15 text-emerald-700">已接收</Badge>
    case 'rejected':
      return <Badge variant="destructive">已拒稿</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

function reminderBadge(count?: number, lastAt?: string | null) {
  if (!count || count < 1) return null
  return (
    <Badge
      variant="outline"
      className="text-[10px] text-amber-700"
      title={lastAt ? `最近催办：${formatDateTime(lastAt)}` : undefined}
    >
      已催 {count} 次
    </Badge>
  )
}

function assignmentStatusBadge(status: string) {
  switch (status) {
    case 'pending':
      return <Badge variant="secondary">待回应</Badge>
    case 'accepted':
      return <Badge className="bg-primary/15 text-primary">已接受</Badge>
    case 'declined':
      return (
        <Badge variant="outline" className="border-amber-500/40 text-amber-600">
          待重新指派
        </Badge>
      )
    case 'completed':
      return <Badge className="bg-emerald-500/15 text-emerald-700">已完成</Badge>
    case 'cancelled':
      return <Badge variant="outline">已撤销</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

interface DecisionFormState {
  decision: EditorDecision
  editor_note: string
  /** 审稿意见冲突时必填的裁决理由 */
  arbitration_note: string
}

const EMPTY_DECISION: DecisionFormState = {
  decision: 'minor_revision',
  editor_note: '',
  arbitration_note: '',
}

// 决策按钮只按稿件状态开关；真正的“≥2 位审稿人录用”闸门由矩阵弹窗
// 展示、由后端裁决端点强制。此前用列表里的 reports_completed 判断，
// 但该字段后端从未返回，按钮永远是灰的——编辑根本点不开决定。
function canOpenDecision(s: SubmissionResponse): boolean {
  return ['pending', 'under_review', 'resubmitted'].includes(s.status)
}

function decisionDisabledReason(s: SubmissionResponse): string | undefined {
  return canOpenDecision(s) ? undefined : '当前状态不可裁决'
}

function PendingSubmissionsPage() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as PendingSearch
  const statusTab = (search.status ?? 'all') as StatusTab
  const page = search.page ?? 1
  // 'all' tab 不传 status，让后端返回全部状态
  const statusFilter = statusTab === 'all' ? undefined : statusTab
  // 职权分离（与后端 require_chief_editor 同口径）：四元最终决定是
  // 最终裁决是执行编辑/主编的职权；栏目编辑只有初审、送审与推荐权。
  const { isAdmin, user } = useAuth()
  const isChief = isAdmin || (user?.roles ?? []).some((r) => ['editor', 'editor_in_chief'].includes(r))
  const isSectionOnly = !isChief && (user?.roles ?? []).includes('section_editor')

  const { data, isLoading, isError, refetch } = useAllSubmissions(
    statusFilter,
    page,
    10,
  )
  const decisionMut = useEditorDecision()

  const [detail, setDetail] = useState<SubmissionResponse | null>(null)
  const [assignTarget, setAssignTarget] = useState<SubmissionResponse | null>(null)
  const [assignmentsTarget, setAssignmentsTarget] = useState<SubmissionResponse | null>(null)
  const [decisionTarget, setDecisionTarget] = useState<SubmissionResponse | null>(null)
  // D 级打回：展开/收起 + 逐行填写的修改要求
  const [reworkOpen, setReworkOpen] = useState(false)
  const [reworkRequirements, setReworkRequirements] = useState('')
  const reworkMut = useRequestRework()
  // 拒稿是终态决定，二次确认后才真正执行
  const [rejectConfirm, setRejectConfirm] = useState(false)
  const [reportsTarget, setReportsTarget] = useState<SubmissionResponse | null>(null)
  // 双盲评审的匿名稿外链：只有编辑能写，审稿人取稿件只认这个链接
  const [anonymizedTarget, setAnonymizedTarget] = useState<SubmissionResponse | null>(
    null,
  )
  const [decisionForm, setDecisionForm] = useState<DecisionFormState>(EMPTY_DECISION)
  // 做决定时内嵌审稿报告摘要：推荐 + 评分 + 编辑保密意见，编辑不必另开弹窗
  const decisionReportsQ = useSubmissionReports(decisionTarget?.id ?? 0)
  const decisionMatrixQ = useReviewMatrix(decisionTarget?.id ?? 0)

  const updateSearch = (patch: Partial<PendingSearch>) => {
    void navigate({
      to: '/submissions/pending',
      search: { ...search, ...patch },
      replace: true,
    })
  }

  const onConfirmDecision = async () => {
    if (!decisionTarget) return
    const target = decisionTarget
    // 拒稿：先弹二次确认（终态操作，误触会直接断送作者的这次投稿）
    if (decisionForm.decision === 'reject') {
      setRejectConfirm(true)
      return
    }
    await doDecision(target)
  }

  const doDecision = async (target: SubmissionResponse) => {
    const matrix = decisionMatrixQ.data
    if (decisionForm.decision === 'accept') {
      if (!matrix) {
        toast.error('正在读取审稿进度，请稍后再试')
        return
      }
      if (matrix.accept_count < 2) {
        toast.error(
          `发表需要至少 2 名审稿人给出录用推荐，当前 ${matrix.accept_count}/2。`,
        )
        return
      }
      if (matrix.conflict && !matrix.adjudicator_accepted) {
        toast.error('审稿意见冲突：请先指定第三方裁决人并等待其录用意见。')
        return
      }
    }
    // 冲突时必须填裁决理由
    if (matrix?.conflict && !decisionForm.arbitration_note.trim()) {
      toast.error('审稿意见冲突：请填写裁决理由')
      return
    }
    try {
      await decisionMut.mutateAsync({
        id: target.id,
        body: {
          decision: decisionForm.decision,
          editor_note: decisionForm.editor_note || undefined,
          arbitration_note:
            target.conflict ? decisionForm.arbitration_note : undefined,
        },
      })
      toast.success('决定已记录')
      setDecisionTarget(null)
      setDecisionForm(EMPTY_DECISION)
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="初筛工作台"
        description="分配审稿人、查看审稿报告、做最终决定。支持按状态筛选全部提交。"
      />

      {isSectionOnly && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          你以栏目编辑（L7）身份查看工作台：可以初审、分配审稿人并给出推荐意见，
          最终录用 / 修回 / 拒稿决定由执行编辑（L8）作出。
        </div>
      )}

      <Tabs
        value={statusTab}
        onValueChange={(v) =>
          updateSearch({ status: v as StatusTab, page: 1 })
        }
        className="mb-4"
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
        <Loading />
      ) : isError ? (
        <ErrorState message="加载失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState title="暂无提交" />
      ) : (
        <div className="space-y-4">
          {data.data.map((s) => (
            <Card key={s.id} data-testid="submission-card">
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-medium">{s.title}</h3>
                    {statusBadge(s.status)}
                    {['pending', 'under_review', 'resubmitted'].includes(s.status) &&
                      waitingChip(s.submitted_at)}
                    {s.status === 'accepted' &&
                      s.resource_publication_status === 'draft' &&
                      (s.resource_id ? (
                        <Link
                          to="/catalog/$resourceId"
                          params={{ resourceId: String(s.resource_id) }}
                          className="inline-flex items-center"
                          title="录用时选择了暂存：进入资源详情后可在「管理此条」里刊出"
                        >
                          <Badge className="bg-amber-500/15 text-amber-700">刊前整理 · 去刊出</Badge>
                        </Link>
                      ) : (
                        <Badge className="bg-amber-500/15 text-amber-700">刊前整理</Badge>
                      ))}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline">{typeLabel(s.type)}</Badge>
                    <span>{s.discipline}</span>
                    <span>{s.year}</span>
                    <span>
                      提交于 {new Date(s.submitted_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground">
                  {s.authors.join(', ')}
                </p>
                <p className="line-clamp-2 text-sm">{s.abstract}</p>
                {/* 小屏双列网格：按钮不再挤成一行小字，触控目标 44px 级 */}
                <div className="flex flex-wrap items-center gap-2 max-sm:grid max-sm:grid-cols-2 max-sm:[&>button]:min-h-10">
                  <Button variant="outline" size="sm" onClick={() => setDetail(s)}>
                    <Eye className="h-4 w-4" /> 详情
                  </Button>
                  {s.status === 'pending' && (
                    <Button size="sm" onClick={() => setAssignTarget(s)}>
                      <UserPlus className="h-4 w-4" /> 分配审稿人
                    </Button>
                  )}
                  {(s.status === 'under_review' || s.status === 'resubmitted') && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setAssignmentsTarget(s)}
                    >
                      <ClipboardList className="h-4 w-4" /> 查看分配
                    </Button>
                  )}
                  {['pending', 'under_review', 'resubmitted'].includes(s.status) &&
                    isChief && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setDecisionTarget(s)
                          setDecisionForm(EMPTY_DECISION)
                        }}
                        disabled={decisionMut.isPending || !canOpenDecision(s)}
                        title={decisionDisabledReason(s)}
                      >
                        <Gavel className="h-4 w-4" /> 做决定
                      </Button>
                    )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setReportsTarget(s)}
                  >
                    <FileText className="h-4 w-4" /> 审稿报告
                  </Button>
                  {[
                    'pending',
                    'under_review',
                    'resubmitted',
                    'major_revision',
                    'minor_revision',
                  ].includes(s.status) && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setAnonymizedTarget(s)}
                    >
                      <ShieldCheck className="h-4 w-4" /> 匿名稿
                    </Button>
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

      {/* 详情 Dialog */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{detail?.title}</DialogTitle>
          </DialogHeader>
          {detail && <SubmissionDetailBody sub={detail} />}
        </DialogContent>
      </Dialog>

      {/* 分配审稿人 Dialog */}
      {assignTarget && (
        <AssignReviewerDialog
          submission={assignTarget}
          onClose={() => setAssignTarget(null)}
        />
      )}

      {/* 查看分配 Dialog */}
      {assignmentsTarget && (
        <AssignmentsDialog
          submission={assignmentsTarget}
          onClose={() => setAssignmentsTarget(null)}
        />
      )}

      {/* 匿名稿外链 Dialog */}
      {anonymizedTarget && (
        <AnonymizedFileDialog
          submission={anonymizedTarget}
          onClose={() => setAnonymizedTarget(null)}
        />
      )}

      {/* 做决定 Dialog */}
      <Dialog
        open={!!decisionTarget}
        onOpenChange={(o) => !o && setDecisionTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>做决定 — {decisionTarget?.title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {/* 审稿报告摘要：有报告时直接展示，帮助编辑在同一个弹窗里完成决定 */}
            {decisionReportsQ.data && decisionReportsQ.data.length > 0 && (
              <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm">
                <div className="text-xs font-medium text-muted-foreground">
                  审稿报告摘要（{decisionReportsQ.data.length} 份）
                </div>
                {decisionReportsQ.data.map((r) => (
                  <div key={r.id} className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">推荐：{r.recommendation}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {new Date(r.submitted_at).toLocaleString()}
                      </span>
                    </div>
                    {reportDimensionEntries(r.scores).length > 0 && (
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap gap-2">
                          {reportDimensionEntries(r.scores).map(([k, v]) => (
                            <span key={k} className="rounded bg-muted px-2 py-0.5 text-xs">
                              {SCORE_LABELS[k] ?? k} {v.score ?? '未评'}/100
                            </span>
                          ))}
                        </div>
                        {typeof r.scores.score === 'number' && (
                          <p className="text-xs font-medium tabular-nums">
                            合计 {String(r.scores.score)} 分 · {String(r.scores.grade ?? '')} · 门槛封顶{' '}
                            {String(r.scores.cap ?? '无')}
                          </p>
                        )}
                        {reportDimensionEntries(r.scores).some(([, v]) => v.evidence) && (
                          <details className="text-xs text-muted-foreground">
                            <summary className="cursor-pointer">查看逐维证据</summary>
                            <div className="mt-1 space-y-1">
                              {reportDimensionEntries(r.scores).map(([k, v]) => (
                                <p key={k}>
                                  <strong>{SCORE_LABELS[k] ?? k}</strong>：{v.reason || '无理由'} · 证据：{v.evidence || '无'}
                                </p>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    )}
                    {r.comments_to_editor && (
                      <p className="whitespace-pre-wrap rounded bg-amber-500/10 p-2 text-xs text-amber-700">
                        编辑保密意见：{r.comments_to_editor}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
            {decisionMatrixQ.data && (
              <div className="rounded-md border bg-muted/30 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">
                    已完成 {decisionMatrixQ.data.reports_completed} 份
                  </Badge>
                  <Badge variant="outline">
                    审稿人 {decisionMatrixQ.data.distinct_reviewers} 人
                  </Badge>
                  <Badge
                    className={
                      decisionMatrixQ.data.accept_count >= 2
                        ? 'bg-emerald-500/15 text-emerald-700'
                        : 'bg-amber-500/15 text-amber-700'
                    }
                  >
                    录用推荐 {decisionMatrixQ.data.accept_count}/2
                  </Badge>
                  {decisionMatrixQ.data.conflict && (
                    <Badge className="bg-amber-500/15 text-amber-700">
                      意见冲突
                    </Badge>
                  )}
                  {decisionMatrixQ.data.adjudicator_accepted && (
                    <Badge className="bg-emerald-500/15 text-emerald-700">
                      第三方已裁决
                    </Badge>
                  )}
                </div>
                {decisionMatrixQ.data.accept_count < 2 && (
                  <p className="mt-2 text-xs text-amber-700">
                    发表前需要至少 2 名不同审稿人给出录用推荐。可继续送审，或在意见冲突时指定第三方裁决人。
                  </p>
                )}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="decision">决定</Label>
              <Select
                value={decisionForm.decision}
                onValueChange={(v) =>
                  setDecisionForm((prev) => ({
                    ...prev,
                    decision: v as EditorDecision,
                  }))
                }
              >
                <SelectTrigger id="decision" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DECISION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                      {o.hint && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          ({o.hint})
                        </span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="editor_note">编辑备注（作者可见）</Label>
              <Textarea
                id="editor_note"
                value={decisionForm.editor_note}
                onChange={(e) =>
                  setDecisionForm((prev) => ({
                    ...prev,
                    editor_note: e.target.value,
                  }))
                }
                placeholder="说明决定原因，作者将在投稿详情中看到"
                rows={4}
              />
            </div>
            {decisionMatrixQ.data?.conflict && (
              <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
                <Label htmlFor="arbitration_note" className="text-amber-800 dark:text-amber-200">
                  审稿意见冲突，需填写裁决理由（必填）
                </Label>
                <Textarea
                  id="arbitration_note"
                  value={decisionForm.arbitration_note}
                  onChange={(e) =>
                    setDecisionForm((prev) => ({
                      ...prev,
                      arbitration_note: e.target.value,
                    }))
                  }
                  placeholder="说明为何采纳某份意见、驳回另一份"
                  rows={3}
                />
              </div>
            )}
          </div>

          {/* D 级打回：评分不达标时不直接拒稿，而是要求审稿人补审/作者修改。
              与"做决定"并列而不是藏在菜单里——它是与录用/拒稿同级的处置。 */}
          <div className="space-y-2 rounded-lg border border-destructive/25 bg-destructive/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-destructive">打回补审（D 级处置）</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setReworkOpen((v) => !v)}
                type="button"
              >
                {reworkOpen ? '收起' : '发起打回'}
              </Button>
            </div>
            {reworkOpen && (
              <div className="space-y-2">
                <p className="text-[11px] text-muted-foreground">
                  打回会同时通知审稿人（补审或说明理由）与作者（逐条修改要求）。
                  至少填 3 条具体问题——只说"不合格"对作者没有帮助。
                </p>
                {decisionTarget?.quality_score != null && decisionTarget.quality_score < 40 && (
                  <p className="rounded bg-destructive/10 px-2 py-1 text-[11px] text-destructive">
                    当前评分 {decisionTarget?.quality_score ?? '—'} 分（不合格，低于 40），
                    按规范不能直接录用。
                  </p>
                )}
                <Textarea
                  placeholder="每行一条修改要求，至少 3 行（例如：补充样本量的说明）"
                  value={reworkRequirements}
                  onChange={(e) => setReworkRequirements(e.target.value)}
                  rows={4}
                  className="text-xs"
                />
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={reworkMut.isPending}
                  onClick={async () => {
                    const reqs = reworkRequirements
                      .split(String.fromCharCode(10))
                      .map((x) => x.trim())
                      .filter(Boolean)
                    if (reqs.length < 3) {
                      toast.error('请至少填写 3 条具体修改要求')
                      return
                    }
                    if (!decisionTarget) return
                    try {
                      await reworkMut.mutateAsync({ id: decisionTarget.id, requirements: reqs })
                      toast.success('已打回：审稿人与作者都已收到通知')
                      setReworkOpen(false)
                      setReworkRequirements('')
                      setDecisionTarget(null)
                    } catch (err) {
                      toast.error(extractError(err, '打回失败'))
                    }
                  }}
                >
                  {reworkMut.isPending ? '提交中…' : '确认打回'}
                </Button>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDecisionTarget(null)}>
              取消
            </Button>
            <Button onClick={onConfirmDecision} disabled={decisionMut.isPending}>
              {decisionMut.isPending ? '处理中…' : '确认决定'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 审稿报告 Dialog */}
      {reportsTarget && (
        <ReportsDialog
          submission={reportsTarget}
          onClose={() => setReportsTarget(null)}
        />
      )}

      {/* 拒稿二次确认：终态操作，先想清楚再执行 */}
      <ConfirmDialog
        open={rejectConfirm}
        title="确认拒稿"
        description="拒稿后该投稿将进入「已拒稿」状态，作者不能继续修改或重投。确定要拒稿吗？"
        confirmText="确认拒稿"
        destructive
        onConfirm={() => {
          setRejectConfirm(false)
          if (decisionTarget) void doDecision(decisionTarget)
        }}
        onOpenChange={(o) => !o && setRejectConfirm(false)}
      />
    </div>
  )
}

// 详情面板：抽出为组件避免主组件过于臃肿
function SubmissionDetailBody({ sub }: { sub: SubmissionResponse }) {
  // 版本历史：编辑需要知道稿件被重投过几次、每次作者说明了什么
  const versionsQ = useSubmissionVersions(sub.id)
  const putAuthors = usePutAuthors()
  // 作者编辑：从 sub.authors（字符串数组）初始化
  const [authors, setAuthors] = useState<AuthorEditInput[]>(() =>
    sub.authors.map((name, i) => ({
      name,
      affiliation: '',
      email: '',
      roles: i === 0 ? ['first'] : [],
      order: i + 1,
    })),
  )
  const [dirty, setDirty] = useState(false)

  const onSaveAuthors = async () => {
    if (authors.length === 0) {
      toast.error('至少需要 1 位作者')
      return
    }
    if (!authors.some((a) => a.roles.includes('first'))) {
      toast.error('必须指定 1 位第一作者')
      return
    }
    try {
      await putAuthors.mutateAsync({ path: 'submission', id: sub.id, authors })
      toast.success('作者列表已保存')
      setDirty(false)
    } catch (err) {
      toast.error(extractError(err, '保存作者失败'))
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{typeLabel(sub.type)}</Badge>
        <span className="text-muted-foreground">{sub.discipline}</span>
        <span className="text-muted-foreground">{sub.year}</span>
        {sub.subdiscipline && (
          <span className="text-muted-foreground">{sub.subdiscipline}</span>
        )}
      </div>

      {/* 作者编辑面板：增删/排序/第一/通讯 */}
      <div className="rounded-md border p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-medium">作者（发布前可编辑）</span>
          <div className="flex items-center gap-2">
            {dirty && <Badge variant="outline" className="text-amber-700">未保存</Badge>}
            <Button size="sm" variant="outline" onClick={onSaveAuthors} disabled={putAuthors.isPending}>
              <Save className="h-3.5 w-4" /> 保存
            </Button>
          </div>
        </div>
        <AuthorEditor
          value={authors}
          onChange={(next) => {
            setAuthors(next)
            setDirty(true)
          }}
        />
      </div>

      {sub.venue && (
        <div>
          <span className="text-muted-foreground">出版物：</span>
          {sub.venue}
        </div>
      )}
      {sub.keywords && sub.keywords.length > 0 && (
        <div>
          <span className="text-muted-foreground">关键词：</span>
          {sub.keywords.join(', ')}
        </div>
      )}
      {sub.jel_codes && sub.jel_codes.length > 0 && (
        <div>
          <span className="text-muted-foreground">JEL Codes：</span>
          {sub.jel_codes.join(', ')}
        </div>
      )}
      {sub.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sub.tags.map((t) => (
            <Badge key={t} variant="secondary">
              {t}
            </Badge>
          ))}
        </div>
      )}
      <div>
        <span className="text-muted-foreground">摘要</span>
        <p className="mt-1 whitespace-pre-wrap">{normalizeAbstract(sub.abstract)}</p>
      </div>
      <div>
        <span className="text-muted-foreground">预览</span>
        <p className="mt-1 whitespace-pre-wrap">{sub.preview}</p>
      </div>
      {sub.doi && (
        <div>
          <span className="text-muted-foreground">DOI：</span>
          {sub.doi}
        </div>
      )}
      {sub.download_url && (
        <div>
          <span className="text-muted-foreground">下载：</span>
          {sub.download_url}
        </div>
      )}
      {sub.external_url && (
        <div>
          <span className="text-muted-foreground">外部链接：</span>
          {sub.external_url}
        </div>
      )}
      {sub.file_path && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">稿件文件：</span>
          <span className="break-all text-primary">{sub.file_path}</span>
          <button
            type="button"
            className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
            onClick={() => void downloadSubmissionFile(sub.id, 'docx')}
          >
            <Download className="h-3.5 w-3.5" />
            Word
          </button>
          <button
            type="button"
            className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
            onClick={() => void downloadSubmissionFile(sub.id, 'pdf')}
          >
            <Download className="h-3.5 w-3.5" />
            PDF
          </button>
        </div>
      )}
      {versionsQ.data && versionsQ.data.length > 0 && (
        <div className="rounded-md border p-3">
          <div className="mb-2 font-medium">版本历史</div>
          <ol className="space-y-1.5">
            {versionsQ.data.map((v) => (
              <li key={v.id} className="flex gap-2">
                <Badge variant="outline" className="shrink-0">
                  v{v.version}
                </Badge>
                <div className="min-w-0">
                  <span className="text-xs text-muted-foreground">
                    {v.version === 1 ? '初次提交' : '重投'} ·{' '}
                    {new Date(v.created_at).toLocaleString()}
                  </span>
                  {v.note && (
                    <p className="mt-0.5 whitespace-pre-wrap">
                      修改说明:{v.note}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="text-xs text-muted-foreground">
        提交于 {new Date(sub.submitted_at).toLocaleString()}
      </div>
    </div>
  )
}

// 分配审稿人对话框：列出本租户所有用户供编辑挑选
function AssignReviewerDialog({
  submission,
  onClose,
}: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  // 专供编辑的候选端点：只返回持 reviewer 角色且启用的账号，非 admin 的
  // editor 也能用（此前走 /admin/users 会 403，下拉永远是空的）。
  const { data: candidateData, isLoading } = useReviewerCandidates(REVIEWER_CANDIDATE_LIMIT, submission.id)
  const candidates = candidateData ?? []
  const truncated = candidates.length >= REVIEWER_CANDIDATE_LIMIT
  const assignMut = useAssignReviewersBulk()
  const [selected, setSelected] = useState<number[]>([])
  const [dueDays, setDueDays] = useState('14')
  const [isExternal, setIsExternal] = useState(false)
  const [externalAffiliation, setExternalAffiliation] = useState('')

  const toggle = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length >= 3 ? prev : [...prev, id],
    )
  }

  const onConfirm = async () => {
    if (selected.length === 0) {
      toast.error('请至少选择一名审稿人（最多 3 名）')
      return
    }
    try {
      const res = await assignMut.mutateAsync({
        id: submission.id,
        body: {
          reviewer_ids: selected,
          due_days: Math.max(1, Math.min(90, Number(dueDays) || 14)),
          is_external: isExternal,
          external_affiliation: isExternal ? externalAffiliation.trim() || undefined : undefined,
        },
      })
      toast.success(`已指派 ${res.assigned} 名审稿人`)
      onClose()
    } catch (err) {
      toast.error(extractError(err, '指派失败'))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>指派审稿人 — {submission.title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            可一次多选（最多 3 名，占 slot 1/2/3）；重复邀请同一审稿人会自动跳过。
          </p>
          <div className="max-h-[40vh] space-y-1 overflow-y-auto">
            {isLoading ? (
              <Loading />
            ) : candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                没有可指派的审稿人：请先在「用户管理」里给用户授予审稿人（reviewer）角色。
              </p>
            ) : (
              candidates.map((u) => {
                const checked = selected.includes(u.id)
                return (
                  <label
                    key={u.id}
                    className="flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-sm hover:bg-accent"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(u.id)}
                      className="h-4 w-4"
                    />
                    <span className="font-medium">{u.username}</span>
                    <span className="text-xs text-muted-foreground">{u.email}</span>
                  {typeof u.score === "number" && u.score > 0 ? (
                    <Badge variant="outline" className="text-[10px]">匹配 {u.score}</Badge>
                  ) : null}
                    {selected.includes(u.id) && (
                      <span className="ml-auto text-xs text-primary">已选</span>
                    )}
                  </label>
                )
              })
            )}
          </div>
          {truncated && (
            <p className="text-xs text-muted-foreground">
              候选列表只取了前 {REVIEWER_CANDIDATE_LIMIT} 个审稿人，目标审稿人不在其中时请用
              「用户管理」确认其角色。
            </p>
          )}
          <div className="space-y-2 rounded-md border p-3">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={isExternal}
                onChange={(e) => setIsExternal(e.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                <span className="font-medium">外审专家（外省/外单位）</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  由主编/编辑指定，标记会写入审稿矩阵与审计；审稿人仍需用站内账号登录。
                </span>
              </span>
            </label>
            {isExternal && (
              <Input
                placeholder="外审单位 / 省份，例如：中山大学（广东）"
                value={externalAffiliation}
                onChange={(e) => setExternalAffiliation(e.target.value)}
                maxLength={120}
              />
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="due_days">审稿截止天数（1–90）</Label>
            <Input
              id="due_days"
              type="number"
              min={1}
              max={90}
              value={dueDays}
              onChange={(e) => setDueDays(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onConfirm} disabled={assignMut.isPending}>
            {assignMut.isPending ? '处理中…' : `确认指派（${selected.length} 人）`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// 查看分配列表对话框
function AssignmentsDialog({
  submission,
  onClose,
}: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  const { data, isLoading, isError, refetch } = useSubmissionAssignments(
    submission.id,
  )
  const matrixQ = useReviewMatrix(submission.id)
  const [adjOpen, setAdjOpen] = useState(false)
  const cancelMut = useCancelAssignment()

  const onCancel = async (assignmentId: number) => {
    try {
      await cancelMut.mutateAsync({
        submissionId: submission.id,
        assignmentId,
      })
      toast.success('已撤销分配')
    } catch (err) {
      toast.error(extractError(err, '撤销失败'))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>审稿分配 — {submission.title}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <Loading />
        ) : isError ? (
          <ErrorState message="加载失败" onRetry={() => refetch()} />
        ) : !data || data.data.length === 0 ? (
          <EmptyState title="暂无审稿分配" />
        ) : (
          <div className="space-y-3">
            {matrixQ.data && (
              <div className="rounded-md border bg-muted/30 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">
                    报告 {matrixQ.data.reports_completed} 份
                  </Badge>
                  <Badge variant="outline">
                    审稿人 {matrixQ.data.distinct_reviewers} 人
                  </Badge>
                  <Badge
                    className={
                      matrixQ.data.accept_count >= 2
                        ? 'bg-emerald-500/15 text-emerald-700'
                        : 'bg-amber-500/15 text-amber-700'
                    }
                  >
                    录用推荐 {matrixQ.data.accept_count}/2
                  </Badge>
                  {matrixQ.data.conflict && (
                    <Badge className="bg-amber-500/15 text-amber-700">意见冲突</Badge>
                  )}
                  {matrixQ.data.adjudicator_assigned && (
                    <Badge variant="outline">
                      第三方裁决人
                    </Badge>
                  )}
                </div>
                {(matrixQ.data.need_adjudication || matrixQ.data.adjudicator_assigned) && (
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-amber-700">
                      {matrixQ.data.need_adjudication
                        ? '审稿意见冲突，需要第三方裁决人给出独立意见后才能录用。'
                        : '已指定第三方裁决人，等待其提交意见。'}
                    </p>
                    {matrixQ.data.need_adjudication && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setAdjOpen(true)}
                      >
                        <Gavel className="mr-1 h-4 w-4" /> 指定第三方裁决人
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
            <div className="space-y-2">
            {data.data.map((a: AssignmentResponse) => (
              <div
                key={a.id}
                className="flex flex-wrap items-center gap-2 rounded border p-2 text-sm"
              >
                <span className="font-medium">
                  {a.reviewer_username ?? `#${a.reviewer_id}`}
                </span>
                {assignmentStatusBadge(a.status)}
                {reminderBadge(a.reminder_count, a.last_reminded_at)}
                <span className="text-xs text-muted-foreground">
                  邀于 {new Date(a.invited_at).toLocaleString()}
                </span>
                {a.due_date && (
                  <span className="text-xs text-muted-foreground">
                    · 截止 {new Date(a.due_date).toLocaleString()}
                  </span>
                )}
                {a.completed_at && (
                  <span className="text-xs text-muted-foreground">
                    · 完成 {new Date(a.completed_at).toLocaleString()}
                  </span>
                )}
                <div className="ml-auto">
                  {['pending', 'accepted'].includes(a.status) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onCancel(a.id)}
                      disabled={cancelMut.isPending}
                    >
                      撤销
                    </Button>
                  )}
                </div>
              </div>
            ))}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
      {adjOpen && matrixQ.data && (
        <AdjudicateDialog
          submission={submission}
          matrix={matrixQ.data}
          onClose={() => setAdjOpen(false)}
        />
      )}
    </Dialog>
  )
}

// 第三方裁决人：只在意见冲突/需要独立裁决时由主编或编辑指定。
function AdjudicateDialog({
  submission,
  matrix,
  onClose,
}: {
  submission: SubmissionResponse
  matrix: ReviewMatrixResponse
  onClose: () => void
}) {
  const { data: candidateData, isLoading } = useReviewerCandidates(REVIEWER_CANDIDATE_LIMIT, submission.id)
  const candidates = (candidateData ?? []).filter(
    (u) => !matrix.assignments.some((a) => a.reviewer_id === u.id),
  )
  const mut = useAssignAdjudicator()
  const [selected, setSelected] = useState<number | null>(null)
  const [dueDays, setDueDays] = useState('14')
  const [reason, setReason] = useState('')

  const onConfirm = async () => {
    if (!selected) {
      toast.error('请选择一位第三方裁决人')
      return
    }
    try {
      await mut.mutateAsync({
        id: submission.id,
        reviewer_id: selected,
        due_days: Math.max(1, Math.min(90, Number(dueDays) || 14)),
        reason: reason.trim() || undefined,
      })
      toast.success('已指定第三方裁决人，并已发送站内通知')
      onClose()
    } catch (err) {
      toast.error(extractError(err, '指定裁决人失败'))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>指定第三方裁决人 — {submission.title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            当前已有 {matrix.distinct_reviewers} 位审稿人提交意见，录用推荐 {matrix.accept_count}/2。
            裁决人不能是本稿已参与评审的审稿人，也不能是作者。
          </p>
          <div className="max-h-[35vh] space-y-1 overflow-y-auto">
            {isLoading ? (
              <Loading />
            ) : candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                没有可用的第三方裁决人：请确认审稿人账号已授予 reviewer 角色，且未参与本稿。
              </p>
            ) : (
              candidates.map((u) => (
                <label
                  key={u.id}
                  className="flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-sm hover:bg-accent"
                >
                  <input
                    type="radio"
                    name="adjudicator"
                    checked={selected === u.id}
                    onChange={() => setSelected(u.id)}
                    className="h-4 w-4"
                  />
                  <span className="font-medium">{u.username}</span>
                  <span className="text-xs text-muted-foreground">{u.email}</span>
                  {typeof u.score === "number" && u.score > 0 ? (
                    <Badge variant="outline" className="text-[10px]">匹配 {u.score}</Badge>
                  ) : null}
                </label>
              ))
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="adj_due">裁决截止天数（1–90）</Label>
            <Input
              id="adj_due"
              type="number"
              min={1}
              max={90}
              value={dueDays}
              onChange={(e) => setDueDays(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="adj_reason">裁决说明（发给裁决人）</Label>
            <Textarea
              id="adj_reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="说明分歧点与需要独立判断的问题"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={onConfirm} disabled={mut.isPending}>
            {mut.isPending ? '处理中…' : '确认指定'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// 审稿报告对话框：编辑可见完整报告（含 comments_to_editor）
function ReportsDialog({
  submission,
  onClose,
}: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  const { data, isLoading, isError, refetch } = useSubmissionReports(
    submission.id,
  )

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>审稿报告 — {submission.title}</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <Loading />
        ) : isError ? (
          <ErrorState message="加载失败" onRetry={() => refetch()} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="暂无已完成的审稿报告" />
        ) : (
          <div className="space-y-4">
            {data.map((r: ReviewReportResponse) => (
              <div key={r.id} className="rounded border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className="bg-emerald-500/15 text-emerald-700">
                    已完成
                  </Badge>
                  <Badge variant="outline">推荐：{r.recommendation}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(r.submitted_at).toLocaleString()}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {reportDimensionEntries(r.scores).map(([k, v]) => (
                    <div key={k} className="rounded bg-muted p-1 text-center text-xs">
                      <div className="font-medium">{SCORE_LABELS[k] ?? k}</div>
                      <div className="text-muted-foreground">{v.score ?? '未评'}/100</div>
                    </div>
                  ))}
                </div>
                {reportDimensionEntries(r.scores).some(([, v]) => v.evidence) && (
                  <div className="mt-2 space-y-1 rounded border bg-muted/20 p-2 text-xs">
                    {reportDimensionEntries(r.scores).map(([k, v]) => (
                      <p key={k}>
                        <strong>{SCORE_LABELS[k] ?? k}</strong>：{v.reason || '无理由'} · 证据：{v.evidence || '无'}
                      </p>
                    ))}
                  </div>
                )}
                {r.comments_to_author && (
                  <div className="mt-2">
                    <div className="text-xs text-muted-foreground">
                      给作者的意见
                    </div>
                    <p className="mt-1 whitespace-pre-wrap">
                      {r.comments_to_author}
                    </p>
                  </div>
                )}
                {r.comments_to_editor && (
                  <div className="mt-2 rounded bg-amber-500/10 p-2">
                    <div className="text-xs text-amber-700">
                      给编辑的保密意见
                    </div>
                    <p className="mt-1 whitespace-pre-wrap">
                      {r.comments_to_editor}
                    </p>
                  </div>
                )}
                {r.attachments && r.attachments.length > 0 && (
                  <div className="mt-2">
                    <div className="text-xs text-muted-foreground">审稿附件</div>
                    <ReviewAttachmentLinks
                      reportId={r.id}
                      attachments={r.attachments}
                    />
                  </div>
                )}
              </div>
            ))}
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

function AnonymizedFileDialog({
  submission,
  onClose,
}: {
  submission: SubmissionResponse
  onClose: () => void
}) {
  const setAnon = useSetAnonymizedFile()
  const [url, setUrl] = useState(submission.anonymized_file_url ?? '')

  const isHttpUrl = (v: string) => /^https?:\/\/\S+/i.test(v.trim())

  const onSave = async () => {
    if (!isHttpUrl(url)) {
      toast.error('请填写 http(s) 开头的匿名稿链接')
      return
    }
    try {
      await setAnon.mutateAsync({ id: submission.id, url: url.trim() })
      toast.success('匿名稿链接已保存')
      onClose()
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  const onClear = async () => {
    try {
      await setAnon.mutateAsync({ id: submission.id, url: null })
      toast.success('匿名稿链接已清除')
      onClose()
    } catch (err) {
      toast.error(extractError(err, '清除失败'))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>匿名稿 — {submission.title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            双盲评审下审稿人只能访问这里填写的匿名稿外链；作者可控的
            download_url / external_url 不会流向审稿人。服务端不具备剥离 PDF
            元数据的能力，请确认上传的匿名稿本身不含作者姓名与单位。
          </p>
          <div className="space-y-1">
            <Label htmlFor="anonymized-file-url">匿名稿链接（http/https）</Label>
            <Input
              id="anonymized-file-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.org/anonymized-manuscript.pdf"
            />
          </div>
        </div>
        <DialogFooter>
          {submission.anonymized_file_url && (
            <Button variant="ghost" onClick={onClear} disabled={setAnon.isPending}>
              清除
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onSave} disabled={setAnon.isPending || !isHttpUrl(url)}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
