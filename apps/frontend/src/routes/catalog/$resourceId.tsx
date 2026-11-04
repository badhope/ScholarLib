import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import {
  Bookmark,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  Download,
  ExternalLink,
  FileDown,
  Heart,
  MoreVertical,
  Pencil,
  Quote,
  Send,
  Share2,
  Trash2,
  UserCheck,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useIsMobile } from '@/hooks/use-is-mobile'
import {
  useAuthorFollowStatus,
  useClaimResource,
  useClaimStatus,
  useDeleteResource,
  useDisciplineSubscriptionStatus,
  useFollowAuthor,
  useRecordView,
  useReadingProgress,
  useResource,
  useResources,
  useSubscribeDiscipline,
  useUnfollowAuthor,
  useUnsubscribeDiscipline,
  useUpdateResource,
} from '@/hooks/api/use-modules'
import type { ResourceResponse, ResourceUpdate } from '@/lib/types'
import { extractError, formatDateTime, parseListField } from '@/lib/utils'
import { isSafeExternalUrl, safeHref } from '@/lib/url-safety'
import {
  absurdityLevel,
  languageLabel,
  qualityGrade,
  statusLabel,
  typeLabel,
} from '@/lib/resource-labels'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AddToListDialog } from '@/components/common/add-to-list-dialog'
import { BottomSheet } from '@/components/common/bottom-sheet'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { Comments } from '@/components/common/comments'
import { ArticleCover } from '@/components/common/article-cover'
import { MetaItem } from '@/components/common/meta-item'
import { EmptyState, ErrorState, LoadingSkeleton } from '@/components/common/state'

// 详情页向访客开放（后端 GET /catalog/{id} 本就是公开接口）。
// 需登录的能力（阅读、进度、关注）在组件内按 isAuthenticated 降级为登录引导。
export const Route = createFileRoute('/catalog/$resourceId')({
  component: CatalogDetailPage,
})

function CatalogDetailPage() {
  const { resourceId } = Route.useParams()
  const id = Number(resourceId)
  const navigate = useNavigate()
  const { isAdmin, isAuthenticated } = useAuth()

  const { data, isLoading, isError, refetch } = useResource(id)
  const progress = useReadingProgress(id, { enabled: isAuthenticated })
  const recordView = useRecordView()
  const updateMut = useUpdateResource()
  const deleteMut = useDeleteResource()
  const isMobile = useIsMobile()

  // ref guard: avoid double recordView call under React StrictMode
  // 访客不上报浏览记录（后端该接口需要登录）。
  // 存的是「已上报过的资源 id」而不是布尔量：StrictMode 下 effect 会
  // effect → cleanup → effect 跑两遍，cleanup 里把标志复位等于把守卫
  // 抹掉、反而上报两次——正是这段注释想避免的事。
  const viewRecordedRef = useRef<number | null>(null)
  // ref-stabilize the mutation so the effect deps stay [id, isAuthenticated]
  // (the mutation object is recreated each render; depending on it directly
  // would reset the guard and re-record on every render).
  const recordViewRef = useRef(recordView)
  useEffect(() => {
    if (!isAuthenticated || viewRecordedRef.current === id) return
    viewRecordedRef.current = id
    void recordViewRef.current.mutateAsync(id).catch(() => {})
  }, [id, isAuthenticated])

  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  // 作者认领：登录用户可对"无人认领"的存量文章发起认领（编辑部审批）
  const [claimOpen, setClaimOpen] = useState(false)
  const [claimNote, setClaimNote] = useState('')
  const claimStatus = useClaimStatus(id, isAuthenticated)
  const claimMut = useClaimResource()

  const onClaim = async () => {
    try {
      await claimMut.mutateAsync({ resourceId: id, note: claimNote.trim() || undefined })
      toast.success('认领申请已提交，等待编辑部审核')
      setClaimOpen(false)
      setClaimNote('')
    } catch (err) {
      toast.error(extractError(err, '认领失败'))
    }
  }

  if (isLoading) return <LoadingSkeleton rows={6} />
  if (isError || !data) {
    return (
      <ErrorState
        message="加载资源失败"
        onRetry={() => refetch()}
      />
    )
  }

  const onDelete = async () => {
    try {
      await deleteMut.mutateAsync(id)
      toast.success('已删除')
      void navigate({ to: '/catalog' })
    } catch {
      toast.error('删除失败')
    }
  }

  return (
    <div className={isMobile ? 'pb-40' : ''}>
      <Link
        to="/catalog"
        className="mb-4 inline-flex min-h-[36px] items-center text-sm text-muted-foreground hover:text-primary"
      >
        <ChevronLeft className="mr-1 h-4 w-4" />
        返回目录
      </Link>

      {/* 专题封面：详情页只作为视觉锚点，不占首屏正文空间（移动端 16:7 压缩） */}
      <div className="mb-5 overflow-hidden rounded-xl border">
        <ArticleCover resource={data} showDiscipline={false} className="aspect-[16/7] sm:aspect-[16/5]" />
      </div>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {/* 赛道徽章已随赛道下线移除：文章气质由荒诞指数徽章表达。 */}
            <Badge variant="secondary">{typeLabel(data.type)}</Badge>
            {(() => {
              const level = absurdityLevel(data.absurdity_index)
              return level ? (
                <Badge
                  variant={level.variant}
                  title={`荒诞指数 ${data.absurdity_index} / 10 · ${level.description}`}
                >
                  {level.label} {data.absurdity_index?.toFixed(1)}
                </Badge>
              ) : null
            })()}
            {data.r_index != null &&
            (data.reads ?? 0) + (data.downloads ?? 0) + (data.saves ?? 0) >= 3 ? (
              <Badge variant="outline" className="tabular-nums">
                R {data.r_index.toFixed(1)}
                {data.quartile ? ` · ${data.quartile}` : ''}
              </Badge>
            ) : null}
            {data.publication_status !== 'published' && (
              <Badge variant="outline">{statusLabel(data.publication_status)}</Badge>
            )}
          </div>
          {/* 手机上标题占三到四行会把摘要挤出首屏，降到 xl 后两行内可见 */}
          <h1 className="text-xl font-semibold leading-snug tracking-tight sm:text-2xl">{data.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data.authors.join(', ')}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 主体 */}
        <div className="space-y-6 lg:col-span-2">
          {/* 认领入口：登录 + 文章可认领时显示（编辑部导入的早期文章与站内账号无关） */}
          {isAuthenticated && claimStatus.data?.claimable && (
            <Card className="border-dashed">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium">这篇文章还没有挂到任何站内账号名下</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    如果你是本文作者，可以发起认领，编辑部核实后会把文章挂到你的名下。
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={() => setClaimOpen(true)} disabled={claimMut.isPending}>
                  <UserCheck className="h-4 w-4" />
                  认领本文
                </Button>
              </CardContent>
            </Card>
          )}
          {isAuthenticated && claimStatus.data?.mine && (
            <Card className="border-primary/30 bg-primary/5">
              <CardContent className="py-4">
                <p className="text-sm">
                  你已提交认领申请（{claimStatus.data.mine.status === 'pending' ? '待编辑部审核' : claimStatus.data.mine.status === 'approved' ? '已批准' : '未通过'}）。
                </p>
              </CardContent>
            </Card>
          )}

          <AbstractCard text={data.abstract} collapsible={isMobile} />

          <CitationCard resource={data} />

          <FoldCard title="元数据" defaultOpen={!isMobile}>
            <CardContent>
              <MetaItem label="年份" value={String(data.year)} />
              <MetaItem label="出版物" value={data.venue} />
              <MetaItem label="学科" value={data.discipline} />
              <MetaItem label="子学科" value={data.subdiscipline} />
              <MetaItem label="DOI" value={data.doi} />
              <MetaItem
                label="卷/期/页"
                value={
                  [data.volume, data.issue, data.pages]
                    .filter(Boolean)
                    .join(' / ') || null
                }
              />
              <MetaItem label="语言" value={languageLabel(data.language)} />
              {data.keywords && data.keywords.length > 0 && (
                <MetaItem label="关键词" value={data.keywords.join('；')} />
              )}
              <MetaItem label="ISSN" value={data.issn} />
              <MetaItem label="ISBN" value={data.isbn} />
            </CardContent>
          </FoldCard>

          {/* R 指数：只有真实事件才算数；分区样本不足时明确写出来，
              不用一个看着漂亮的字母糊弄读者。 */}
          {/* 质量评分：RQS v3.0 七维明细（口径公开在 /levels） */}
          <FoldCard title="质量评分（RQS v3.0）" defaultOpen={!isMobile}>
            <CardContent>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {(() => {
                  const grade = qualityGrade(data.quality_grade)
                  if (!grade) {
                    return <span className="text-sm text-muted-foreground">尚未评分</span>
                  }
                  return (
                    <>
                      <Badge variant="outline" className={grade.className}>
                        {grade.label}
                      </Badge>
                      <span className="font-serif text-2xl font-semibold tabular-nums">
                        {data.quality_score?.toFixed(1)}
                        <span className="ml-1 text-sm font-normal text-muted-foreground">/ 100</span>
                      </span>
                    </>
                  )
                })()}
              </div>
              {data.quality_comment && (
                <div className="mt-3 rounded-md border bg-muted/40 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">编辑部评价</p>
                  <p className="text-sm leading-relaxed">{data.quality_comment}</p>
                </div>
              )}
              {data.quality_breakdown && (
                <div className="mt-3 space-y-1.5">
                  {Object.entries(data.quality_breakdown)
                    .filter(([key]) => key !== 'comment')
                    .map(([key, dim]) => (
                    <div key={key} className="flex items-center gap-2 text-xs">
                      <span className="w-24 shrink-0 text-muted-foreground">{dim.label}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary/70"
                          style={{ width: `${Math.min(100, (dim.score / Math.max(dim.max, 1)) * 100)}%` }}
                        />
                      </div>
                      <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">
                        {dim.score} / {dim.max}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                评分为七维加权（问题价值 / 论证链 / 方法透明度 / 证据强度 / 创新与定位 /
                学术诚信 / 表达清晰度，按稿件类型另有分档权重，学术诚信 0 分一票否决）；
                口径冻结在评分规范 v3.0，不随月份变化。
              </p>
            </CardContent>
          </FoldCard>

          <FoldCard title="阅读与影响" defaultOpen={false}>
            <CardContent>
              <MetaItem label="R 指数" value={data.r_index != null ? String(data.r_index) : '—'} />
              <MetaItem
                label="学科分区"
                value={data.quartile ?? '样本不足'}
              />
              <MetaItem label="阅读次数" value={String(data.reads ?? 0)} />
              <MetaItem label="下载次数" value={String(data.downloads ?? 0)} />
              <MetaItem label="收藏次数" value={String(data.saves ?? 0)} />
              <MetaItem
                label="荒诞指数"
                value={
                  data.absurdity_index != null
                    ? `${data.absurdity_index.toFixed(1)} / 10 · ${absurdityLevel(data.absurdity_index)?.description ?? ''}`
                    : '未评定'
                }
              />
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                R 指数与荒诞指数均为本刊自设计指标：前者衡量站内注意力，
                后者由编辑部评定内容气质；口径属编辑部内部标准，不等同于影响因子。
              </p>
            </CardContent>
          </FoldCard>

          {data.tags.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">标签</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {data.tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {data.preview && data.preview.trim() !== data.abstract.trim() && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">预览</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-7 whitespace-pre-wrap text-muted-foreground">
                  {data.preview}
                </p>
              </CardContent>
            </Card>
          )}

          <RelatedResources resourceId={id} discipline={data.discipline} />

          <Comments resourceId={id} />
        </div>

        {/* 右侧操作区（移动端隐藏：操作移入底部固定操作栏） */}
        <div className="space-y-4">
          {!isMobile && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">操作</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button asChild className="w-full">
                  <Link
                    to="/reader/$resourceId"
                    params={{ resourceId: String(id) }}
                  >
                    <BookOpen className="h-4 w-4" />
                    在线阅读
                  </Link>
                </Button>
                {data.has_file && (
                  <Button asChild variant="outline" className="w-full">
                    <a href={`/api/catalog/${id}/file`} download>
                      <Download className="h-4 w-4" />
                      原稿 PDF
                    </a>
                  </Button>
                )}
                {data.has_file && (
                  <>
                    <Button asChild variant="outline" className="w-full">
                      <a href={`/api/catalog/${id}/export?format=pdf`} download>
                        <Download className="h-4 w-4" />
                        规范化 PDF
                      </a>
                    </Button>
                    <Button asChild variant="outline" className="w-full">
                      <a href={`/api/catalog/${id}/export?format=docx`} download>
                        <Download className="h-4 w-4" />
                        Word 文档
                      </a>
                    </Button>
                  </>
                )}
                {isAuthenticated ? (
                  <>
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={() => setListOpen(true)}
                    >
                      <Bookmark className="h-4 w-4" />
                      加入阅读列表
                    </Button>
                  </>
                ) : (
                  <p className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                    游客模式：可阅读与下载全部已刊内容，进度保存在本设备。
                    <Link to="/login" search={{ redirect: `/catalog/${id}` }} className="text-primary hover:underline">
                      登录
                    </Link>
                    后可收藏、跨设备同步并参与评论。
                  </p>
                )}
                {data.external_url && (
                  <Button asChild variant="outline" className="w-full">
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
                    >
                      <ExternalLink className="h-4 w-4" />
                      外部链接
                    </a>
                  </Button>
                )}
                {isAdmin && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" className="w-full text-muted-foreground">
                        <MoreVertical className="h-4 w-4" />
                        管理此条
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuItem onClick={() => setEditOpen(true)}>
                        <Pencil className="h-4 w-4" />
                        编辑题录
                      </DropdownMenuItem>
                      {data.publication_status === 'draft' && (
                        <DropdownMenuItem
                          disabled={updateMut.isPending}
                          onClick={() => {
                            // 刊前整理完成 → 刊出（可逆：改回 draft 即可撤回）
                            updateMut.mutate(
                              { id, body: { publication_status: 'published' } },
                              {
                                onSuccess: () =>
                                  toast.success('已刊出：该条目现已进入公开目录'),
                                onError: () => toast.error('刊出失败，请稍后再试'),
                              },
                            )
                          }}
                        >
                          <Send className="h-4 w-4" />
                          刊出（进入公开目录）
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={() => setDeleteOpen(true)}
                      >
                        <Trash2 className="h-4 w-4" />
                        删除资源
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </CardContent>
            </Card>
          )}

          <FoldCard title="引用与分享" defaultOpen={!isMobile}>
            <CardContent className="space-y-2">
              <p className="rounded-md bg-muted/50 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                {data.authors.join('，')}：{data.title}[Z]．Rubbish，{data.year}．
              </p>
              <Button
                variant="outline"
                className="w-full"
                onClick={async () => {
                  const cite = `${data.authors.join('，')}：${data.title}[Z]．Rubbish，${data.year}．`
                  try {
                    await navigator.clipboard.writeText(cite)
                    toast.success('引用格式已复制')
                  } catch {
                    toast.error('复制失败，请手动选择')
                  }
                }}
              >
                <Quote className="h-4 w-4" />
                复制引用格式
              </Button>
              <Button
                variant="outline"
                className="w-full"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(window.location.href)
                    toast.success('链接已复制')
                  } catch {
                    toast.error('复制失败')
                  }
                }}
              >
                <Share2 className="h-4 w-4" />
                复制分享链接
              </Button>
              {/* 引用文件导出：复用公开 /api/export（BibTeX / RIS），
                  供 Zotero / EndNote / Mendeley 直接导入 */}
              <div className="grid grid-cols-2 gap-2">
                <Button asChild variant="ghost" size="sm">
                  <a href={`/api/export?ids=${id}&format=bibtex`} download>
                    <FileDown className="h-3.5 w-3.5" />
                    BibTeX
                  </a>
                </Button>
                <Button asChild variant="ghost" size="sm">
                  <a href={`/api/export?ids=${id}&format=ris`} download>
                    <FileDown className="h-3.5 w-3.5" />
                    RIS
                  </a>
                </Button>
              </div>
            </CardContent>
          </FoldCard>

          {isAuthenticated && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">阅读进度</CardTitle>
            </CardHeader>
            <CardContent>
              {progress.isLoading ? (
                <LoadingSkeleton rows={6} />
              ) : progress.data ? (
                <div className="space-y-1.5 text-sm">
                  <MetaItem
                    label="页码"
                    value={progress.data.page ? String(progress.data.page) : '—'}
                  />
                  <MetaItem
                    label="进度"
                    value={
                      progress.data.progress_percent != null
                        ? `${progress.data.progress_percent}%`
                        : '—'
                    }
                  />
                  <MetaItem
                    label="总时长"
                    value={`${Math.round(progress.data.duration_sec / 60)} 分钟`}
                  />
                  <MetaItem
                    label="访问次数"
                    value={String(progress.data.visit_count)}
                  />
                  <MetaItem
                    label="最近阅读"
                    value={formatDateTime(progress.data.last_read_at)}
                  />
                  {progress.data.completed && (
                    <Badge variant="secondary">已完成</Badge>
                  )}
                </div>
              ) : (
                <EmptyState title="暂无阅读记录" />
              )}
            </CardContent>
          </Card>
          )}

          <FollowCard
            authorName={data.authors[0]}
            discipline={data.discipline}
          />
        </div>
      </div>

      {isMobile && (
        <MobileDetailActions
          resourceId={id}
          isAdmin={isAdmin}
          hasFile={Boolean(data.has_file)}
          externalUrl={data.external_url}
          onEdit={() => setEditOpen(true)}
          onDelete={() => setDeleteOpen(true)}
        />
      )}

      {editOpen && data && (
        <EditDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          initial={data}
          onSubmit={async (body) => {
            try {
              await updateMut.mutateAsync({ id, body })
              toast.success('已更新')
              setEditOpen(false)
            } catch (err) {
              toast.error(extractError(err, '更新失败'))
            }
          }}
        />
      )}

      {isAuthenticated && (
        <AddToListDialog resourceId={id} open={listOpen} onOpenChange={setListOpen} />
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="删除资源"
        description="确认删除该资源？此操作不可撤销。"
        confirmText="删除"
        destructive
        onOpenChange={setDeleteOpen}
        onConfirm={onDelete}
      />

      {/* 认领申请弹窗：说明选填，编辑部审批后文章挂到名下 */}
      <Dialog open={claimOpen} onOpenChange={setClaimOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>认领本文</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              申请提交后编辑部会核实作者身份，批准后文章将挂到你的账号名下。
            </p>
            <Label htmlFor="claim-note">申请说明（选填）</Label>
            <Textarea
              id="claim-note"
              rows={3}
              maxLength={500}
              value={claimNote}
              onChange={(e) => setClaimNote(e.target.value)}
              placeholder="例：本文第一作者，原始投稿邮箱为 …，可提供底稿核对。"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClaimOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void onClaim()} disabled={claimMut.isPending}>
              {claimMut.isPending ? '提交中…' : '提交申请'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// 编辑表单字段精简：title/authors/year/discipline/abstract/tags/preview
interface EditFormState {
  title: string
  authors: string
  year: string
  discipline: string
  abstract: string
  tags: string
  preview: string
  absurdity_index: string
  publication_status: 'published' | 'in_review' | 'draft'
}

function EditDialog({
  open,
  onOpenChange,
  initial,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  initial: {
    title: string
    authors: string[]
    year: number
    discipline: string
    abstract: string
    tags: string[]
    preview: string
    absurdity_index?: number | null
    publication_status: 'published' | 'in_review' | 'draft'
  }
  onSubmit: (body: ResourceUpdate) => Promise<void>
}) {
  const [form, setForm] = useState<EditFormState>({
    title: initial.title,
    authors: initial.authors.join(', '),
    year: String(initial.year),
    discipline: initial.discipline,
    abstract: initial.abstract,
    tags: initial.tags.join(', '),
    preview: initial.preview,
    absurdity_index:
      initial.absurdity_index != null ? String(initial.absurdity_index) : '',
    publication_status: initial.publication_status,
  })

  const onSubmitForm = async (e: React.FormEvent) => {
    e.preventDefault()
    const body: ResourceUpdate = {
      title: form.title,
      authors: parseListField(form.authors),
      year: Number(form.year),
      discipline: form.discipline,
      abstract: form.abstract,
      tags: parseListField(form.tags),
      preview: form.preview,
      absurdity_index:
        form.absurdity_index.trim() === ''
          ? null
          : Number(form.absurdity_index),
      publication_status: form.publication_status,
    }
    await onSubmit(body)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑资源</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmitForm} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-title">标题</Label>
            <Input
              id="edit-title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-authors">作者（逗号分隔）</Label>
            <Input
              id="edit-authors"
              value={form.authors}
              onChange={(e) => setForm({ ...form, authors: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="edit-year">年份</Label>
              <Input
                id="edit-year"
                type="number"
                value={form.year}
                onChange={(e) => setForm({ ...form, year: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-discipline">学科</Label>
              <Input
                id="edit-discipline"
                value={form.discipline}
                onChange={(e) => setForm({ ...form, discipline: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-abstract">摘要</Label>
            <Textarea
              id="edit-abstract"
              value={form.abstract}
              onChange={(e) => setForm({ ...form, abstract: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-tags">标签（逗号分隔）</Label>
            <Input
              id="edit-tags"
              value={form.tags}
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-preview">预览</Label>
            <Textarea
              id="edit-preview"
              value={form.preview}
              onChange={(e) => setForm({ ...form, preview: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="edit-absurdity">荒诞指数（0–10，留空为未评定）</Label>
              <Input
                id="edit-absurdity"
                type="number"
                min={0}
                max={10}
                step={0.1}
                value={form.absurdity_index}
                onChange={(e) => setForm({ ...form, absurdity_index: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-pubstatus">刊出状态</Label>
              <Select
                value={form.publication_status}
                onValueChange={(v) =>
                  setForm({ ...form, publication_status: v as EditFormState['publication_status'] })
                }
              >
                <SelectTrigger id="edit-pubstatus">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="published">已发表（公开可见）</SelectItem>
                  <SelectItem value="in_review">评审中（刊前预览）</SelectItem>
                  <SelectItem value="draft">草稿（仅编辑部可见）</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type="submit">保存</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// 关注作者 + 订阅学科操作卡片。
// 仅在已登录时显示；未登录时整张卡片不渲染（路由层已挡，这里是双保险）。
function FollowCard({
  authorName,
  discipline,
}: {
  authorName: string
  discipline: string
}) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated || !authorName) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">关注</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <FollowAuthorRow authorName={authorName} />
        {discipline && <SubscribeDisciplineRow discipline={discipline} />}
      </CardContent>
    </Card>
  )
}

function FollowAuthorRow({ authorName }: { authorName: string }) {
  const { data } = useAuthorFollowStatus(authorName)
  const followMut = useFollowAuthor()
  const unfollowMut = useUnfollowAuthor()
  const following = data?.following ?? false
  const followersCount = data?.followers_count ?? 0

  const onToggle = async () => {
    const mut = following ? unfollowMut : followMut
    try {
      await mut.mutateAsync(authorName)
      toast.success(following ? `已取消关注 ${authorName}` : `已关注 ${authorName}`)
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="min-w-0">
          <span className="text-muted-foreground">作者</span>
          <p className="truncate font-medium">{authorName}</p>
        </span>
        <Button
          variant={following ? 'outline' : 'default'}
          size="sm"
          onClick={onToggle}
          disabled={followMut.isPending || unfollowMut.isPending}
        >
          <Heart className={following ? 'h-4 w-4 fill-current' : 'h-4 w-4'} />
          {following ? '已关注' : '关注'}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {followersCount} 人关注
      </p>
    </div>
  )
}

function SubscribeDisciplineRow({ discipline }: { discipline: string }) {
  const { data } = useDisciplineSubscriptionStatus(discipline)
  const subMut = useSubscribeDiscipline()
  const unsubMut = useUnsubscribeDiscipline()
  const subscribed = data?.subscribed ?? false
  const subscribersCount = data?.subscribers_count ?? 0

  const onToggle = async () => {
    const mut = subscribed ? unsubMut : subMut
    try {
      await mut.mutateAsync(discipline)
      toast.success(
        subscribed ? `已取消订阅 ${discipline}` : `已订阅 ${discipline}`,
      )
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="min-w-0">
          <span className="text-muted-foreground">学科</span>
          <p className="truncate font-medium">{discipline}</p>
        </span>
        <Button
          variant={subscribed ? 'outline' : 'default'}
          size="sm"
          onClick={onToggle}
          disabled={subMut.isPending || unsubMut.isPending}
        >
          <Bookmark className={subscribed ? 'h-4 w-4 fill-current' : 'h-4 w-4'} />
          {subscribed ? '已订阅' : '订阅'}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {subscribersCount} 人订阅
      </p>
    </div>
  )
}

// 摘要卡：桌面端完整铺开；移动端超过 5 行先截断，点「展开全文」再看。
// 详情页真正的正文在阅读器里，首屏只需要让人判断「要不要点进去」。
function AbstractCard({ text, collapsible }: { text: string; collapsible: boolean }) {
  const [open, setOpen] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const ref = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (!collapsible) return
    const el = ref.current
    if (!el) return
    setOverflowing(el.scrollHeight > el.clientHeight + 4)
  }, [collapsible, text])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">摘要</CardTitle>
      </CardHeader>
      <CardContent>
        <p
          ref={ref}
          className={
            'text-sm leading-7 whitespace-pre-wrap' +
            (collapsible && !open ? ' line-clamp-5' : '')
          }
        >
          {text}
        </p>
        {collapsible && (overflowing || open) && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-2 inline-flex min-h-[36px] items-center text-xs font-medium text-primary hover:underline"
          >
            {open ? '收起' : '展开全文'}
          </button>
        )}
      </CardContent>
    </Card>
  )
}

// 可折叠信息卡：桌面端默认展开（信息完整），移动端默认收起（把首屏
// 让给摘要与正文）。用原生 <details> 而非 Radix Collapsible——不需要
// 额外依赖、键盘与读屏行为天然正确，也避免再引入一个受控状态。
function FoldCard({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  return (
    <details open={defaultOpen} className="group rounded-xl border bg-card text-card-foreground shadow-sm">
      <summary className="flex min-h-[48px] cursor-pointer select-none items-center justify-between gap-2 px-6 py-4 text-base font-semibold [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="pb-6">{children}</div>
    </details>
  )
}

// 移动端底部固定操作栏：在线阅读（主操作）+ 下载 + 更多。
// 仅移动端渲染；桌面端沿用右侧"操作"卡片，互不复用。
//
// 为什么「更多」用底部抽屉而不是 DropdownMenu：触发器贴在屏幕下沿，
// Radix 计算出的可用高度只有 ~10px，点开等于什么都不显示。抽屉从底部
// 整宽展开，天然避开了这个定位问题。
function MobileDetailActions({
  resourceId,
  isAdmin,
  hasFile,
  externalUrl,
  onEdit,
  onDelete,
}: {
  resourceId: number
  isAdmin: boolean
  hasFile: boolean
  externalUrl?: string | null
  onEdit: () => void
  onDelete: () => void
}) {
  const [moreOpen, setMoreOpen] = useState(false)
  return (
    <>
      <div className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-40 flex items-center gap-2 border-t bg-background/95 p-3 backdrop-blur">
        <Button asChild className="flex-1">
          <Link
            to="/reader/$resourceId"
            params={{ resourceId: String(resourceId) }}
          >
            <BookOpen className="h-4 w-4" />
            在线阅读
          </Link>
        </Button>
        {hasFile && (
          <Button asChild variant="outline" className="shrink-0 gap-1 px-3">
            <a href={`/api/catalog/${resourceId}/file`} download aria-label="下载 PDF">
              <Download className="h-4 w-4" />
              下载
            </a>
          </Button>
        )}
        <Button
          variant="outline"
          size="icon"
          aria-label="更多操作"
          onClick={() => setMoreOpen(true)}
        >
          <MoreVertical className="h-5 w-5" />
        </Button>
      </div>

      <BottomSheet open={moreOpen} onClose={() => setMoreOpen(false)} title="更多操作">
        <div className="flex flex-col">
          <button
            type="button"
            onClick={async () => {
              setMoreOpen(false)
              try {
                await navigator.clipboard.writeText(window.location.href)
                toast.success('链接已复制')
              } catch {
                toast.error('复制失败')
              }
            }}
            className="flex min-h-[48px] items-center gap-3 rounded-md px-2 text-left text-sm hover:bg-accent"
          >
            <Share2 className="h-5 w-5 shrink-0 text-muted-foreground" />
            复制分享链接
          </button>
          {externalUrl && (
            <a
              // H1：作者可控外链走协议白名单，javascript: 等一律降级。
              href={safeHref(externalUrl)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setMoreOpen(false)}
              title={
                isSafeExternalUrl(externalUrl)
                  ? externalUrl
                  : '该链接协议不安全，已禁用'
              }
              aria-disabled={!isSafeExternalUrl(externalUrl)}
              className="flex min-h-[48px] items-center gap-3 rounded-md px-2 text-left text-sm hover:bg-accent"
            >
              <ExternalLink className="h-5 w-5 shrink-0 text-muted-foreground" />
              外部链接
            </a>
          )}
          {isAdmin && (
            <>
              <button
                type="button"
                onClick={() => {
                  setMoreOpen(false)
                  onEdit()
                }}
                className="flex min-h-[48px] items-center gap-3 rounded-md px-2 text-left text-sm hover:bg-accent"
              >
                <Pencil className="h-5 w-5 shrink-0 text-muted-foreground" />
                编辑
              </button>
              <button
                type="button"
                onClick={() => {
                  setMoreOpen(false)
                  onDelete()
                }}
                className="flex min-h-[48px] items-center gap-3 rounded-md px-2 text-left text-sm text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-5 w-5 shrink-0" />
                删除
              </button>
            </>
          )}
        </div>
      </BottomSheet>
    </>
  )
}


// 相关文章：同类型的高相关条目（优先同学科），帮助读者从"一篇"到"一批"。
// 用公开目录接口，取 4 条、排除自身；无结果时整块不渲染（不留空壳）。
function RelatedResources({
  resourceId,
  discipline,
}: {
  resourceId: number
  discipline?: string | null
}) {
  const { data: sameDiscipline } = useResources({
    page: 1,
    page_size: 8,
    discipline: discipline ?? undefined,
  })
  const { data: fallback } = useResources({ page: 1, page_size: 8 })
  const pool =
    (sameDiscipline?.data ?? []).filter((r) => r.id !== resourceId).length >= 1
      ? (sameDiscipline?.data ?? [])
      : (fallback?.data ?? [])
  const items = pool.filter((r) => r.id !== resourceId).slice(0, 4)
  if (items.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">相关文章</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.map((r) => (
          <Link
            key={r.id}
            to="/catalog/$resourceId"
            params={{ resourceId: String(r.id) }}
            className="group block rounded-md border-b pb-2 last:border-0 last:pb-0"
          >
            <p className="line-clamp-2 text-sm font-medium leading-snug transition-colors group-hover:text-primary">
              {r.title}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {r.authors.slice(0, 2).join('、')}
              {r.authors.length > 2 ? ' 等' : ''} · {r.year}
              {r.absurdity_index != null && r.absurdity_index >= 7.5 ? ' · 离谱' : ''}
            </p>
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}

/**
 * 「引用本文」卡：GB/T 7714-2015 顺序编码制 + BibTeX 双格式一键复制。
 * 为什么放详情页顶部而不是藏在导出菜单：引用是读者拿到一篇论文后的
 * 第一个动作（写综述、挂参考文献），藏在下拉里等于没有。
 */
function CitationCard({ resource }: { resource: ResourceResponse }) {
  const firstAuthor = resource.authors[0] ?? '佚名'
  const authorPart =
    resource.authors.length > 3
      ? `${firstAuthor}, 等`
      : resource.authors.join(', ')
  const pagesPart = resource.pages ? `: ${resource.pages}` : ''
  const venuePart = resource.venue || 'Rubbish'
  const gbt7714 =
    `${authorPart}. ${resource.title}[J]. ${venuePart}, ${resource.year}` +
    `${resource.volume ? `, ${resource.volume}` : ''}${resource.issue ? `(${resource.issue})` : ''}${pagesPart}.`
  const bibtex = [
    `@article{rubbish${resource.id}${resource.year},`,
    `  title  = {${resource.title}},`,
    `  author = {${resource.authors.join(' and ')}},`,
    `  journal= {${venuePart}},`,
    `  year   = {${resource.year}},`,
    resource.volume ? `  volume = {${resource.volume}},` : null,
    resource.issue ? `  number = {${resource.issue}},` : null,
    resource.pages ? `  pages  = {${resource.pages}},` : null,
    resource.doi ? `  doi    = {${resource.doi}},` : null,
    `}`,
  ]
    .filter(Boolean)
    .join('\n')

  const [copied, setCopied] = useState<'gbt' | 'bib' | null>(null)
  const copy = async (kind: 'gbt' | 'bib') => {
    const text = kind === 'gbt' ? gbt7714 : bibtex
    try {
      await navigator.clipboard.writeText(text)
      setCopied(kind)
      toast.success(kind === 'gbt' ? '已复制 GB/T 7714 引用' : '已复制 BibTeX')
      window.setTimeout(() => setCopied(null), 1600)
    } catch {
      toast.error('复制失败，请手动选择文本')
    }
  }

  return (
    <FoldCard title="引用本文" defaultOpen={false}>
      <CardContent className="space-y-3">
        <div>
          <p className="mb-1 text-[11px] font-medium text-muted-foreground">
            GB/T 7714-2015（顺序编码制）
          </p>
          <div className="rounded-md border bg-muted/40 px-3 py-2 font-serif text-[13px] leading-relaxed">
            {gbt7714}
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => copy('gbt')}>
            <Quote className="h-3.5 w-3.5" />
            {copied === 'gbt' ? '已复制' : '复制 GB/T 7714'}
          </Button>
          <Button size="sm" variant="outline" onClick={() => copy('bib')}>
            {copied === 'bib' ? '已复制 BibTeX' : '复制 BibTeX'}
          </Button>
        </div>
      </CardContent>
    </FoldCard>
  )
}
