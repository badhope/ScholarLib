import { useEffect, useRef, useState } from 'react'
import {
  createFileRoute,
  Link,
  redirect,
  useNavigate,
  useRouterState,
  useSearch,
} from '@tanstack/react-router'
import {
  Download,
  ExternalLink,
  FileText,
  History,
  LayoutDashboard,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  downloadSubmissionFile,
  downloadSubmissionVersion,
  useDeleteSubmission,
  useMySubmissions,
  useResubmitSubmission,
  useSubmissionReports,
  useSubmissionVersions,
  useUploadSubmissionFile,
  useMeProfile,
} from '@/hooks/api/use-modules'
import type {
  IngestResource,
  ReviewReportResponse,
  SubmissionResponse,
  SubmissionStatus,
} from '@/lib/types'
import { typeLabel } from '@/lib/resource-labels'
import { useIsMobile } from '@/hooks/use-is-mobile'
import { useCapabilities } from '@/hooks/use-capabilities'
import { extractError } from '@/lib/utils'
import { normalizeAbstract } from '@/lib/abstract'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import WorkflowTimeline from '@/components/WorkflowTimeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

// 注册 router state 的 preset 字段：ingest 页通过 navigate state 传预填数据，
// 借助 HistoryState 接口的声明合并让两端都类型安全
declare module '@tanstack/history' {
  interface HistoryState {
    preset?: IngestResource
  }
}

export const Route = createFileRoute('/submissions/')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: SubmissionsPage,
})

interface SubmissionSearch {
  status?: SubmissionStatus | 'all'
  page?: number
}

const STATUS_TABS: { value: SubmissionStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待审核' },
  { value: 'under_review', label: '审核中' },
  { value: 'major_revision', label: '大修' },
  { value: 'minor_revision', label: '小修' },
  { value: 'accepted', label: '已接收' },
  { value: 'rejected', label: '已拒绝' },
]

// 作者可编辑内容的状态（与后端 update_submission 的状态门一致）
const EDITABLE_STATUSES = ['pending', 'major_revision', 'minor_revision']

function statusBadge(status: SubmissionStatus) {
  switch (status) {
    case 'pending':
      return <Badge variant="secondary">待审核</Badge>
    case 'under_review':
      return <Badge className="bg-primary/15 text-primary">审核中</Badge>
    case 'major_revision':
      return <Badge className="bg-amber-500/15 text-amber-700">大修</Badge>
    case 'minor_revision':
      return <Badge className="bg-yellow-500/15 text-yellow-700">小修</Badge>
    case 'accepted':
    case 'approved':
      return <Badge className="bg-emerald-500/15 text-emerald-700">已接收</Badge>
    case 'rejected':
      return <Badge variant="destructive">已拒绝</Badge>
    default:
      return <Badge variant="outline">{status}</Badge>
  }
}

// 状态语义提示：首次投稿的作者最焦虑的是"这个状态是什么意思、我该做什么"。
// 一句话讲清现状与下一步，展示在详情面板状态徽章下方。
const STATUS_HINTS: Record<string, string> = {
  pending: '编辑部尚未处理。编辑会初审并决定是否送外审，通常 3–7 天内更新。',
  under_review: '外审进行中：审稿人正在评审你的稿件，请耐心等待审稿意见。',
  major_revision: '审稿人要求大修：请按修改意见修改稿件，然后使用「重投」提交新版本。',
  minor_revision: '审稿人要求小修：小幅调整后即可「重投」，通常无需再次外审。',
  resubmitted: '修改稿已提交，等待编辑部重新审理。',
  accepted: '已录用！稿件已进入目录（或刊前整理阶段），感谢你的投稿。',
  rejected: '本次未录用。欢迎根据审稿意见完善后另投。',
}

function statusHint(status: string): string {
  return STATUS_HINTS[status] ?? ''
}

function SubmissionsPage() {
  const navigate = useNavigate()
  const { data: meProfile } = useMeProfile()
  const canOpenWorkbench = Boolean(
    meProfile && ['editor', 'editor_in_chief'].includes(meProfile.permission_role),
  )
  // 上传约束来自服务端（/capabilities），前端不再维护第二份规则。
  const caps = useCapabilities()
  const uploadMaxMb = Math.round((caps.data?.upload_max_bytes ?? 50 * 1024 * 1024) / 1024 / 1024)
  const maxUploadBytes = caps.data?.upload_max_bytes ?? 50 * 1024 * 1024
  const acceptAttr = (caps.data?.upload_extensions ?? ['.docx', '.doc', '.pdf', '.txt', '.zip']).join(',')
  const search = useSearch({ strict: false }) as SubmissionSearch
  const statusTab = (search.status ?? 'all') as SubmissionStatus | 'all'
  const page = search.page ?? 1
  const status = statusTab === 'all' ? undefined : statusTab

  const isMobile = useIsMobile()
  const { data, isLoading, isError, refetch } = useMySubmissions(status, page, 20)
  const deleteMut = useDeleteSubmission()
  const uploadMut = useUploadSubmissionFile()
  const resubmitMut = useResubmitSubmission()

  const [detail, setDetail] = useState<SubmissionResponse | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [resubmitOpen, setResubmitOpen] = useState(false)
  const [resubmitNote, setResubmitNote] = useState('')
  // 仅在 detail 对话框打开时拉取审稿报告 / 版本历史（hook 通过 enabled 守卫）；
  // 必须放在 detail useState 之后，否则 TS2448/2454 报"使用先于声明"。
  const reportsQ = useSubmissionReports(detail?.id ?? 0)
  const versionsQ = useSubmissionVersions(detail?.id ?? 0, detail !== null)

  const onUploadFile = async (file: File) => {
    if (!detail) return
    try {
      const updated = await uploadMut.mutateAsync({ id: detail.id, file })
      setDetail(updated)
      toast.success('文件已上传')
      // 结构报告：作者上传后立刻知道"离《投稿规范》还差什么"。
      const report = updated.format_report
      if (report && !report.ok) {
        const missing = report.items.filter((i) => !i.ok).map((i) => i.label).join('、')
        toast.warning(`已上传，但结构检查提示缺少：${missing}`, {
          description: '点击稿件详情查看各项修正建议；不影响编辑部接收。',
          duration: 8000,
        })
      } else if (report?.ok) {
        toast.success('结构检查通过：摘要、关键词、章节与参考文献齐全')
      }
    } catch (err) {
      toast.error(extractError(err, '上传失败'))
    }
  }

  // 大修/小修状态下作者重投，触发 submission → resubmitted → under_review。
  // 重投会把当前稿件内容快照为一个新版本，note 随版本存档并推送给编辑。
  const onResubmit = async () => {
    if (!detail) return
    try {
      const updated = await resubmitMut.mutateAsync({
        id: detail.id,
        note: resubmitNote.trim() || undefined,
      })
      setDetail(updated)
      setResubmitOpen(false)
      setResubmitNote('')
      toast.success('已重投，等待编辑再次审核')
    } catch (err) {
      toast.error(extractError(err, '重投失败'))
    }
  }

  // ingest 页 "提交到目录" 通过 router state 传预填数据：
  // 直接转交给四步向导页（由向导消费 preset 并清空 state）。
  const preset = useRouterState({
    select: (s) => s.location.state?.preset,
  })
  const presetHandled = useRef(false)
  useEffect(() => {
    if (!preset || presetHandled.current) return
    presetHandled.current = true
    void navigate({ to: '/submissions/new', state: { preset }, replace: true })
  }, [preset, navigate])

  const updateSearch = (patch: Partial<SubmissionSearch>) => {
    void navigate({
      to: '/submissions',
      search: { ...search, ...patch },
      replace: true,
    })
  }

  const onConfirmDelete = async () => {
    if (deleteId === null) return
    const target = deleteId
    setDeleteId(null)
    try {
      await deleteMut.mutateAsync(target)
      toast.success('已撤销提交')
    } catch (err) {
      toast.error(extractError(err, '撤销失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="我的提交"
        description="查看你提交的资源及审核状态。"
        actions={
          <>
            {canOpenWorkbench && (
              <Button variant="outline" asChild>
                <Link to="/editor/workbench">
                  <LayoutDashboard className="h-4 w-4" />
                  主编工作台
                </Link>
              </Button>
            )}
            <Button
              onClick={() => {
                void navigate({ to: '/submissions/new' })
              }}
            >
              <Plus className="h-4 w-4" />
              新建提交
            </Button>
          </>
        }
      />

      <Tabs
        value={statusTab}
        onValueChange={(v) =>
          updateSearch({ status: v as SubmissionStatus | 'all', page: 1 })
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
        <Loading />
      ) : isError ? (
        <ErrorState message="加载提交失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState
          title="暂无提交"
          description="新建一条提交，等待管理员审核。"
          action={
            <Button asChild size="sm">
              <Link to="/submissions/new">
                <Plus className="mr-1 h-4 w-4" />
                创建第一条提交
              </Link>
            </Button>
          }
        />
      ) : (
        isMobile ? (
          <div className="mt-4 space-y-3">
            {data.data.map((s) => (
              <div
                key={s.id}
                onClick={() => setDetail(s)}
                className="cursor-pointer rounded-lg border bg-card p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="line-clamp-2 text-sm font-medium">{s.title}</p>
                  {statusBadge(s.status)}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {typeLabel(s.type)} · {s.discipline}
                </p>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <time className="text-xs text-muted-foreground">
                    {new Date(s.submitted_at).toLocaleDateString()}
                  </time>
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    {s.status === 'pending' && (
                      <Button variant="ghost" size="sm" onClick={() => setDeleteId(s.id)}>
                        <Trash2 className="h-4 w-4" />
                        撤销
                      </Button>
                    )}
                    {s.resource_id != null && (
                      <Button variant="ghost" size="sm" asChild>
                        <Link
                          to="/catalog/$resourceId"
                          params={{ resourceId: String(s.resource_id) }}
                        >
                          <ExternalLink className="h-4 w-4" />
                          查看发表
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
        <Card className="mt-4">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>标题</TableHead>
                  <TableHead className="w-20">类型</TableHead>
                  <TableHead>学科</TableHead>
                  <TableHead className="w-24">状态</TableHead>
                  <TableHead className="w-32">提交时间</TableHead>
                  <TableHead className="w-24">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((s) => (
                  <TableRow
                    key={s.id}
                    className="cursor-pointer"
                    onClick={() => setDetail(s)}
                  >
                    {/* 同 catalog 表格：长文本列 max-w+truncate，保证状态/时间/操作列在 1280px 内可见 */}
                    <TableCell className="max-w-[320px] truncate font-medium">
                      {s.title}
                    </TableCell>
                    <TableCell>{typeLabel(s.type)}</TableCell>
                    <TableCell className="max-w-[200px] truncate text-muted-foreground">
                      {s.discipline}
                    </TableCell>
                    <TableCell>{statusBadge(s.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(s.submitted_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      {s.status === 'pending' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDeleteId(s.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                          撤销
                        </Button>
                      )}
                      {/* 录用后物化出的目录条目：作者需要一条直达自己已发表文章的路径，
                          否则"录用"之后整条链路就断在这里了 */}
                      {s.resource_id != null && (
                        <Button variant="ghost" size="sm" asChild>
                          <Link
                            to="/catalog/$resourceId"
                            params={{ resourceId: String(s.resource_id) }}
                          >
                            <ExternalLink className="h-4 w-4" />
                            查看发表
                          </Link>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        )
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
          {detail && (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{detail.type}</Badge>
                {statusBadge(detail.status)}
                <span className="text-muted-foreground">{detail.discipline}</span>
                <span className="text-muted-foreground">{detail.year}</span>
              </div>
              {statusHint(detail.status) && (
                <p className="rounded-md bg-muted/50 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                  {statusHint(detail.status)}
                </p>
              )}
              <WorkflowTimeline
                status={detail.status}
                submittedAt={new Date(detail.submitted_at)}
                reviewedAt={detail.reviewed_at ? new Date(detail.reviewed_at) : null}
              />
              <div>
                <span className="text-muted-foreground">作者：</span>
                {detail.authors.join(', ')}
              </div>
              {detail.venue && (
                <div>
                  <span className="text-muted-foreground">出版物：</span>
                  {detail.venue}
                </div>
              )}
              {detail.subdiscipline && (
                <div>
                  <span className="text-muted-foreground">子学科：</span>
                  {detail.subdiscipline}
                </div>
              )}
              {detail.keywords && detail.keywords.length > 0 && (
                <div>
                  <span className="text-muted-foreground">关键词：</span>
                  {detail.keywords.join(', ')}
                </div>
              )}
              {detail.jel_codes && detail.jel_codes.length > 0 && (
                <div>
                  <span className="text-muted-foreground">JEL Codes：</span>
                  {detail.jel_codes.join(', ')}
                </div>
              )}
              {detail.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {detail.tags.map((t) => (
                    <Badge key={t} variant="secondary">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
              <div>
                <span className="text-muted-foreground">摘要</span>
                <p className="mt-1 whitespace-pre-wrap">{normalizeAbstract(detail.abstract)}</p>
              </div>
              <div>
                <span className="text-muted-foreground">预览</span>
                <p className="mt-1 whitespace-pre-wrap">{detail.preview}</p>
              </div>
              {detail.doi && (
                <div>
                  <span className="text-muted-foreground">DOI：</span>
                  {detail.doi}
                </div>
              )}
              {detail.download_url && (
                <div>
                  <span className="text-muted-foreground">下载：</span>
                  {detail.download_url}
                </div>
              )}
              {detail.external_url && (
                <div>
                  <span className="text-muted-foreground">外部链接：</span>
                  {detail.external_url}
                </div>
              )}
              {detail.admin_note && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
                  <span className="text-muted-foreground">审核备注：</span>
                  {detail.admin_note}
                </div>
              )}
              {detail.editor_note && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                  <span className="text-muted-foreground">编辑备注：</span>
                  {detail.editor_note}
                </div>
              )}
              {/* 录用后物化出的目录条目：已刊出对访客公开；暂存草稿则
                  处于刊前阶段，仅编辑与作者本人可预览（对外 404） */}
              {detail.resource_id != null &&
                (detail.resource_publication_status === 'published' ? (
                  <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <ExternalLink className="h-4 w-4" />
                      <span className="font-medium">已发表</span>
                    </div>
                    <p className="mb-2 text-xs text-muted-foreground">
                      本文已收录进公开目录，任何人无需登录即可查看。
                    </p>
                    <Button size="sm" variant="outline" asChild>
                      <Link
                        to="/catalog/$resourceId"
                        params={{ resourceId: String(detail.resource_id) }}
                      >
                        查看发表页面
                      </Link>
                    </Button>
                  </div>
                ) : (
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <ExternalLink className="h-4 w-4" />
                      <span className="font-medium">刊前预览</span>
                    </div>
                    <p className="mb-2 text-xs text-muted-foreground">
                      录用后暂存为草稿，尚未公开：刊出前仅编辑与作者本人可查看，刊出后对所有人开放。
                    </p>
                    <Button size="sm" variant="outline" asChild>
                      <Link
                        to="/catalog/$resourceId"
                        params={{ resourceId: String(detail.resource_id) }}
                      >
                        预览目录条目
                      </Link>
                    </Button>
                  </div>
                ))}
              <div className="rounded-md border p-3">
                <div className="mb-2 flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  <span className="font-medium">稿件文件</span>
                  {detail.file_path ? (
                    <Badge className="bg-emerald-500/15 text-emerald-700">
                      已上传
                    </Badge>
                  ) : (
                    <Badge variant="outline">未上传</Badge>
                  )}
                </div>
                {detail.file_path && (
                  <div className="mb-2 flex items-center gap-2">
                    <span className="break-all text-xs text-muted-foreground">
                      {detail.file_path}
                    </span>
                    <button
                      type="button"
                      className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
                      onClick={() => void downloadSubmissionFile(detail.id, 'docx')}
                    >
                      <Download className="h-3.5 w-3.5" />
                      下载 Word
                    </button>
                    <button
                      type="button"
                      className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
                      onClick={() => void downloadSubmissionFile(detail.id, 'pdf')}
                    >
                      <Download className="h-3.5 w-3.5" />
                      PDF
                    </button>
                  </div>
                )}
                {/* 仅 pending / major_revision / minor_revision 可上传 */}
                {['pending', 'major_revision', 'minor_revision'].includes(
                  detail.status,
                ) && (
                  <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-primary hover:underline">
                    <Upload className="h-4 w-4" />
                    {detail.file_path ? '替换文件' : '上传稿件'}
                    <input
                      type="file"
                      className="hidden"
                      accept={acceptAttr}
                      disabled={uploadMut.isPending}
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f) {
                          if (f.size > maxUploadBytes) {
                            toast.error(
                              `文件 ${(f.size / 1024 / 1024).toFixed(1)} MB 超过 ${uploadMaxMb} MB 上限，请改用网盘或仓库链接`,
                            )
                          } else {
                            void onUploadFile(f)
                          }
                        }
                        e.target.value = ''
                      }}
                    />
                  </label>
                )}
              </div>
              {/* 审稿意见（单盲：作者只可见 comments_to_author，审稿人身份保密） */}
              {reportsQ.data && reportsQ.data.length > 0 && (
                <div className="rounded-md border p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    <span className="font-medium">审稿意见</span>
                    <span className="text-xs text-muted-foreground">
                      （单盲：审稿人身份保密）
                    </span>
                  </div>
                  <div className="space-y-2">
                    {reportsQ.data.map((r: ReviewReportResponse) => (
                      <div
                        key={r.id}
                        className="rounded bg-muted/50 p-2 text-sm"
                      >
                        <div className="mb-1 flex items-center gap-2">
                          <Badge variant="outline">
                            推荐：{r.recommendation}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {new Date(r.submitted_at).toLocaleString()}
                          </span>
                        </div>
                        {r.comments_to_author ? (
                          <p className="whitespace-pre-wrap">
                            {r.comments_to_author}
                          </p>
                        ) : (
                          <p className="text-xs italic text-muted-foreground">
                            审稿人未给作者意见
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {/* 版本历史：v1 = 初次提交，之后每次重投一个版本 */}
              {versionsQ.data && versionsQ.data.length > 0 && (
                <div className="rounded-md border p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <History className="h-4 w-4" />
                    <span className="font-medium">版本历史</span>
                  </div>
                  <ol className="space-y-2">
                    {versionsQ.data.map((v) => (
                      <li key={v.id} className="flex gap-2 text-sm">
                        <Badge variant="outline" className="shrink-0">
                          v{v.version}
                        </Badge>
                        <div className="min-w-0">
                          <div className="text-xs text-muted-foreground">
                            {v.version === 1 ? '初次提交' : '重投'} ·{' '}
                            {new Date(v.created_at).toLocaleString()}
                            {v.file_path ? ' · 含稿件文件' : ''}
                          </div>
                          {v.file_path && (
                            <button
                              type="button"
                              className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                              onClick={() =>
                                void downloadSubmissionVersion(detail.id, v.version).catch(
                                  (err) => toast.error(extractError(err, '该版本原件不可下载')),
                                )
                              }
                            >
                              <Download className="h-3.5 w-3.5" />
                              下载该版本原件
                            </button>
                          )}
                          {v.note && (
                            <p className="mt-0.5 whitespace-pre-wrap text-sm">
                              修改说明：{v.note}
                            </p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {/* 操作区：可编辑状态下开放「修改稿件」（跳转四步向导）；大修/小修额外开放「重投」 */}
              {EDITABLE_STATUSES.includes(detail.status) && (
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      void navigate({
                        to: '/submissions/new',
                        search: { edit: detail.id },
                      })
                    }}
                  >
                    <Pencil className="h-4 w-4" />
                    修改稿件
                  </Button>
                  {['major_revision', 'minor_revision'].includes(
                    detail.status,
                  ) && (
                    <Button onClick={() => setResubmitOpen(true)}>
                      <RefreshCw className="h-4 w-4" />
                      重投提交
                    </Button>
                  )}
                </div>
              )}
              <div className="text-xs text-muted-foreground">
                提交于 {new Date(detail.submitted_at).toLocaleString()}
                {detail.reviewed_at && (
                  <>
                    {' · 审核于 '}
                    {new Date(detail.reviewed_at).toLocaleString()}
                  </>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>


      {/* 重投 Dialog：可附「针对审稿意见做了哪些修改」，随版本存档并通知编辑 */}
      <Dialog
        open={resubmitOpen}
        onOpenChange={(o) => {
          setResubmitOpen(o)
          if (!o) setResubmitNote('')
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>重投提交</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              重投会把稿件当前内容存为一个新版本并交回编辑。若还没改完，
              先关掉这里用「修改稿件」编辑内容。
            </p>
            <div className="space-y-2">
              <Label htmlFor="resubmit-note">修改说明（可选）</Label>
              <Textarea
                id="resubmit-note"
                rows={4}
                value={resubmitNote}
                onChange={(e) => setResubmitNote(e.target.value)}
                placeholder="例如：按审稿人 1 的意见补充了稳健性检验，重写了 3.2 节。"
              />
            </div>
            <div className="flex justify-end gap-2 border-t pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => setResubmitOpen(false)}
              >
                取消
              </Button>
              <Button
                onClick={onResubmit}
                disabled={resubmitMut.isPending}
                data-testid="confirm-resubmit"
              >
                {resubmitMut.isPending ? '处理中…' : '确认重投'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteId !== null}
        title="撤销提交"
        description="确定撤销这条提交吗？此操作不可撤销。"
        confirmText="撤销"
        destructive
        onConfirm={onConfirmDelete}
        onOpenChange={(o) => !o && setDeleteId(null)}
      />
    </div>
  )
}
