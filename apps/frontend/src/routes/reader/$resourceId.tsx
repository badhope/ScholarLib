import { useEffect, useRef, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight, Download, FileText, ListTree, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { typeLabel } from '@/lib/resource-labels'
import { ReadingProgressBar } from '@/components/common/reading-progress-bar'
import { formatDateTime } from '@/lib/utils'
import { useAuth } from '@/hooks/use-auth'
import { useIsMobile } from '@/hooks/use-is-mobile'
import {
  useReadingProgress,
  useRemoveFromHistory,
  useResource,
  useUpdateProgress,
} from '@/hooks/api/use-modules'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import PdfViewer from '@/components/pdf-viewer'
import { ManuscriptView, TOC_OPEN_EVENT } from '@/components/common/manuscript-view'
import { isSafeExternalUrl } from '@/lib/url-safety'

// Restrict reader iframe to http(s) scheme so data:/blob:/javascript:
// URLs cannot execute content inside the PDF viewer frame.
// 白名单实现在 src/lib/url-safety.ts（isSafeExternalUrl），此处复用；
// http: 放行是为了同源部署（如本地 /uploads 托管的稿件文件）。
// 游客本地进度：登录用户进度走服务端同步；未登录时进度保存在本设备
// localStorage，同设备同浏览器下次打开续读。键随资源 id 隔离。
function guestProgressKey(resourceId: number): string {
  return `rubbish.reader.progress.${resourceId}`
}

interface GuestProgress {
  page: number
  progress_percent: number
  completed: boolean
}

function readGuestProgress(resourceId: number): GuestProgress | null {
  try {
    const raw = localStorage.getItem(guestProgressKey(resourceId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<GuestProgress>
    if (typeof parsed.page !== 'number') return null
    return {
      page: parsed.page,
      progress_percent: typeof parsed.progress_percent === 'number' ? parsed.progress_percent : 0,
      completed: Boolean(parsed.completed),
    }
  } catch {
    return null
  }
}

function writeGuestProgress(resourceId: number, value: GuestProgress): void {
  try {
    localStorage.setItem(guestProgressKey(resourceId), JSON.stringify(value))
  } catch {
    // 隐私模式等场景 localStorage 不可用：静默放弃，不影响阅读
  }
}

export const Route = createFileRoute('/reader/$resourceId')({
  // 公开阅读：已发表论文的文件端点对匿名开放（服务端仍对未刊稿 404/401），
  // 路由不再挡登录；阅读进度同步按登录态降级（见 isAuthenticated 分支）。
  component: ReaderPage,
})

function ReaderPage() {
  const { resourceId } = Route.useParams()
  const id = Number(resourceId)
  const navigate = useNavigate()

  const { data, isLoading, isError, refetch } = useResource(id)
  const { isAuthenticated } = useAuth()
  const progress = useReadingProgress(id, { enabled: isAuthenticated })
  const updateMut = useUpdateProgress()
  const removeMut = useRemoveFromHistory()

  // 阅读模式：有在线稿件（Markdown）默认富文本，否则 PDF；可手动切换。
  const [modeOverride, setModeOverride] = useState<'md' | 'pdf' | null>(null)
  const mode: 'md' | 'pdf' = modeOverride ?? (data?.has_markdown ? 'md' : 'pdf')

  // 游客：挂载时读一次本地进度作为初值（登录用户随后会被服务端进度覆盖）
  const guestInitial = isAuthenticated ? null : readGuestProgress(id)
  const [page, setPage] = useState(() => guestInitial?.page ?? 1)
  const [totalPages, setTotalPages] = useState<number | null>(null)
  const [progressPercent, setProgressPercent] = useState(
    () => guestInitial?.progress_percent ?? 0,
  )
  const [completed, setCompleted] = useState(() => guestInitial?.completed ?? false)
  // 本地累加器：仅跟踪本次会话新增的秒数，flush 后清零
  const [localDuration, setLocalDuration] = useState(0)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [tocCount, setTocCount] = useState(0)
  const isMobile = useIsMobile()

  // 标记是否已从服务端同步过进度。
  // React StrictMode 在 dev 下会 mount→unmount→mount：第一次 unmount 时
  // stateRef 还是初始值（page=1, progress=0），如果此时 flush 会把 server
  // 端的真实进度覆盖成 1/0。加这个 guard 避免首次同步前上报。
  const hasSyncedRef = useRef(false)

  // 从服务端进度初始化本地状态（仅首次加载时）。
  // 用 isFetched 而非 isLoading 判断 query 完成：React Query v5 中 isLoading
  // 在 query pending 时为 true，但对于 404 + retry=1 的场景，retry 期间 isLoading
  // 仍是 true。如果用户在 retry 期间点击保存进度，hasSyncedRef 还没设为 true，
  // flush 会 early-return，PUT 永远不发。isFetched 在 query 第一次
  // 完成（无论成功失败）后变 true 且不会被 retry 重置，更稳健。
  // 新用户在服务端没有 history，GET /progress 返回 404，progress.data 为
  // undefined，但 hasSynced 仍需设为 true，否则用户的输入永远无法上报。
  // hasSynced 同时作为"已初始化"标志：PUT 成功后 onSuccess 会更新
  // progress.data，但此时不应再用 server 数据覆盖本地 state。
  const [hasSynced, setHasSynced] = useState(false)
  // 同步 ref 以便 flush 闭包读取
  if (hasSynced) {
    // eslint-disable-next-line react-hooks/refs
    hasSyncedRef.current = true
  }
  // render-time 初始化：服务端数据到达后同步到本地状态，非 effect
  if (progress.isFetched && !hasSynced) {
    setHasSynced(true)
    if (progress.data) {
      setPage(progress.data.page ?? 1)
      setProgressPercent(progress.data.progress_percent ?? 0)
      setCompleted(progress.data.completed)
    }
  }

  // 用 ref 持有最新值，让 setInterval 回调读取时不被闭包冻结
  const stateRef = useRef({ page, progressPercent, completed, localDuration })

  const flush = async () => {
    // 首次 mount 未同步完成前不 flush，避免 StrictMode 双挂载时
    // 用初始值覆盖服务端的真实进度。
    if (!hasSyncedRef.current || !isAuthenticated) return
    const s = stateRef.current
    // 先把时长取出来并立刻清零，再 await 上报。若清零发生在 await 之后，
    // 30s ticker / 手动保存 / unmount 三个 flush 并发时会读到同一份
    // localDuration，把时长重复报给后端。
    const duration = s.localDuration
    if (duration > 0) setLocalDuration(0)
    // 即使 localDuration=0 也可能 page/progress/completed 已变更，
    // 所以无条件上报（duration=0 后端 no-op）。
    try {
      await updateMut.mutateAsync({
        resourceId: id,
        body: {
          page: s.page,
          progress_percent: s.progressPercent,
          duration_sec: duration,
          completed: s.completed,
        },
      })
    } catch {
      // flush 失败静默，下个周期会重试
    }
  }

  const flushRef = useRef(flush)

  // 在 effect 中同步 ref，避免 render 阶段直接修改 ref
  useEffect(() => {
    stateRef.current = { page, progressPercent, completed, localDuration }
    flushRef.current = flush
  })
  // 游客本地持久化：任一进度相关状态变化即写 localStorage
  useEffect(() => {
    if (isAuthenticated) return
    writeGuestProgress(id, { page, progress_percent: progressPercent, completed })
  }, [id, isAuthenticated, page, progressPercent, completed])

  useEffect(() => {
    const ticker = setInterval(() => {
      setLocalDuration((s) => s + 1)
    }, 1000)
    const flusher = setInterval(() => {
      void flushRef.current()
    }, 30_000)
    return () => {
      clearInterval(ticker)
      clearInterval(flusher)
      // unmount 时立即上报最后一次累积的进度，避免丢失最多 29s
      void flushRef.current()
    }
  }, [])

  // 翻页：页码钳制 + 按真实页数自动折算进度，到末页自动勾选“已读完”（仍可手动覆盖）
  const goToPage = (newPage: number) => {
 const clamped = Math.min(totalPages ?? Infinity, Math.max(1, newPage))
    setPage(clamped)
    if (totalPages && totalPages > 0) {
      setProgressPercent(Math.min(100, Math.round((clamped / totalPages) * 100)))
      if (clamped >= totalPages) setCompleted(true)
    }
  }

  // PdfViewer 回调：文档加载完成时同步总页数，把过期页码/进度拉回真实范围
  const handleLoaded = (n: number) => {
    setTotalPages(n)
    const clamped = Math.min(Math.max(1, page), n)
    setPage(clamped)
    setProgressPercent(Math.min(100, Math.round((clamped / n) * 100)))
  }

  const onManualUpdate = async () => {
    // 未登录访客没有进度可存；按钮对访客隐藏，这里兜底提示。
    if (!isAuthenticated) {
      toast.info('登录后才能同步阅读进度')
      return
    }
    // 用户手动点击"保存进度"：绕过 flush 的 hasSyncedRef guard。
    // 原因：GET /progress 在新用户上返回 404 + retry=1，整个 query 完成需要
    // ~1.5s。如果用户在这期间点击保存进度，hasSyncedRef.current 还是 false，
    // flush 会 early-return，PUT 永远不发，进度丢失。手动点击是显式用户意图，
    // 应该立即上报当前 stateRef 的值。
    const s = stateRef.current
    try {
      await updateMut.mutateAsync({
        resourceId: id,
        body: {
          page: s.page,
          progress_percent: s.progressPercent,
          duration_sec: s.localDuration,
          completed: s.completed,
        },
      })
      setLocalDuration(0)
      // 手动 PUT 成功后，把 hasSyncedRef 设为 true：后续 unmount 时的 flush
      // 可以正常工作（不会再 early-return）。如果 useEffect 在 query 完成
      // 后已经设过，这里是无害的赋值。
      hasSyncedRef.current = true
      toast.success('进度已保存')
    } catch {
      toast.error('保存失败')
    }
  }

  const onRemove = async () => {
    if (!isAuthenticated) {
      toast.info('登录后才能管理阅读历史')
      return
    }
    try {
      await removeMut.mutateAsync(id)
      toast.success('已从阅读历史移除')
      void navigate({ to: '/catalog' })
    } catch {
      toast.error('移除失败')
    }
  }

  if (isLoading) return <Loading />
  if (isError || !data) {
    return <ErrorState message="加载资源失败" onRetry={() => refetch()} />
  }

  const totalDuration = (progress.data?.duration_sec ?? 0) + localDuration

  const windowScroll = isMobile && mode === 'md'
  return (
    <div
      className={
        'flex flex-col ' +
        (windowScroll ? 'min-h-[calc(100dvh-3.5rem)]' : 'h-[calc(100vh-3.5rem)]')
      }
    >
      <ReadingProgressBar />
      {!isAuthenticated && (
        <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-4 py-1 text-[11px] text-muted-foreground">
          {/* 移动端只留一句，把纵向空间还给正文 */}
          <span className="truncate">
            <span className="hidden sm:inline">游客模式：阅读进度保存在本设备，登录后可跨设备同步并参与评论。</span>
            <span className="sm:hidden">游客模式 · 进度存在本设备</span>
          </span>
          <Link to="/login" search={{ redirect: `/reader/${id}` }} className="shrink-0 text-primary hover:underline">
            登录
          </Link>
        </div>
      )}
      {/* 顶部标题栏 */}
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5 sm:gap-3 sm:px-4 sm:py-2">
        <Link
          to="/catalog/$resourceId"
          params={{ resourceId: String(id) }}
          className="inline-flex min-h-[36px] shrink-0 items-center text-sm text-muted-foreground hover:text-primary"
        >
          <ChevronLeft className="mr-1 h-4 w-4" />
          返回详情
        </Link>
        <span className="min-w-0 flex-1 text-sm font-medium line-clamp-1">{data.title}</span>
        {data.type && <Badge variant="secondary">{typeLabel(data.type)}</Badge>}
        {data.has_markdown && data.download_url && (
          <button
            onClick={() => setModeOverride(mode === 'pdf' ? 'md' : 'pdf')}
            className="inline-flex min-h-[28px] shrink-0 items-center rounded-full border px-2.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-primary"
          >
            {mode === 'pdf' ? '阅读版' : '原稿 PDF'}
          </button>
        )}
      </div>

      <div
        data-reader-scroll
        className={
          'flex flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden' +
          (isMobile ? ' pb-44' : '')
        }
      >
        {/* 主体：Markdown 在线阅读（0.6.2 起）或 pdf.js 视图（兜底） */}
        <div
          className={
            'flex flex-col lg:h-full ' +
            (windowScroll ? '' : 'h-[calc(100dvh-14rem)] min-h-[26rem] md:h-[calc(100dvh-11rem)]')
          }
        >
          {mode === 'md' && data.has_markdown ? (
            <ManuscriptView
              resourceId={id}
              useWindowScroll={windowScroll}
              initialPercent={progressPercent}
              onTocChange={setTocCount}
              onProgress={(p, done) => {
                setProgressPercent(p)
                if (done) setCompleted(true)
              }}
            />
) : isAuthenticated && !hasSynced ? (
 <Loading />
 ) : data.download_url && isSafeExternalUrl(data.download_url) ? (
 <PdfViewer
              url={data.download_url}
              initialPage={page}
              onLoaded={handleLoaded}
              onPageChange={(p) => goToPage(p)}
              showPager={!isMobile}
            />
          ) : (
            <EmptyState
              title="暂无可阅读文件"
              description={
                data.download_url
                  ? '该资源下载链接协议不安全，已阻止加载。'
                  : '该资源未提供下载链接。'
              }
            />
          )}
        </div>

        {/* 右侧进度栏：桌面端固定侧栏。移动端整块折叠——手机上它会把正文
            挤到只剩一屏，而其中的控件（页码、进度、保存）已由底部操作栏
            与「进度」抽屉覆盖，重复展示只会遮挡正文。 */}
        <aside className="hidden w-full shrink-0 overflow-y-auto border-t p-4 lg:block lg:w-72 lg:border-l lg:border-t-0">
          <Card className="mb-4">
            <CardHeader>
              <CardTitle className="text-base">阅读进度</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* 读屏：当前页码变化实时播报（视觉隐藏，仅读屏可见） */}
              <p className="sr-only" aria-live="polite">
                当前第 {page} 页
              </p>
              <div className="space-y-1.5">
                {mode === 'md' ? (
                  <p className="rounded-md bg-muted/60 px-2 py-1.5 text-xs text-muted-foreground">
                    富文本视图：滚动即记录进度，无需翻页。
                  </p>
                ) : (
                <>
                <Label htmlFor="page">页码</Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="page"
                    type="number"
                    min={1}
                    value={page}
                    onChange={(e) =>
                      // 清空输入框时 Number('') === 0，会让 30s 后把 page:0
                      // 原样上报；这里兜底到第 1 页。
                      goToPage(Math.max(1, Number(e.target.value) ||1))
                    }
                    className="h-8 w-20"
                  />
                  {/* 移动端：翻页由底部固定操作栏独占，这里仅桌面端显示，避免控件重复 */}
                  <Button
                    size="sm"
                    variant="outline"
                    className="max-md:hidden"
                    onClick={() => goToPage(page - 1)}
                  >
                    上一页
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="max-md:hidden"
                    onClick={() => goToPage(page + 1)}
                  >
                    下一页
                  </Button>
                </div>
                </>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="progress">
                  进度：{progressPercent}%
                </Label>
                <input
                  id="progress"
                  type="range"
                  min={0}
                  max={100}
                  value={progressPercent}
                  onChange={(e) => setProgressPercent(Number(e.target.value))}
                  aria-valuetext={`阅读进度 ${progressPercent}%`}
                  className="w-full"
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="completed"
                  type="checkbox"
                  checked={completed}
                  onChange={(e) => setCompleted(e.target.checked)}
                />
                <Label htmlFor="completed" className="cursor-pointer">
                  已读完
                </Label>
              </div>

              <div className="space-y-1 border-t pt-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">总时长</span>
                  <span>{Math.round(totalDuration / 60)} 分钟</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">最近阅读</span>
                  <span>{formatDateTime(progress.data?.last_read_at)}</span>
                </div>
              </div>

              {/* 移动端：保存进度由底部固定操作栏独占，这里仅桌面端显示 */}
              {isAuthenticated ? (
                <Button
                  className="w-full max-md:hidden"
                  size="sm"
                  onClick={onManualUpdate}
                  disabled={updateMut.isPending}
                >
                  {updateMut.isPending ? '保存中…' : '保存进度'}
                </Button>
              ) : (
                <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground max-md:hidden">
                  游客进度自动保存在本设备；{' '}
                  <Link
                    to="/login"
                    search={{ redirect: `/reader/${id}` }}
                    className="text-primary hover:underline"
                  >
                    登录
                  </Link>{' '}
                  后可跨设备同步。
                </p>
              )}
            </CardContent>
          </Card>

          {isAuthenticated && (
            <Button
              variant="outline"
              className="w-full text-destructive"
              onClick={() => setRemoveOpen(true)}
            >
              <Trash2 className="h-4 w-4" />
              移除阅读历史
            </Button>
          )}
        </aside>
      </div>

      {/* 移动端底部阅读操作栏：PDF 翻页 + 下载 + 保存进度。
          刻意不用整宽登录按钮：它会占掉一整行高度、把正文尾部压住，
          而游客提示已经在页面顶部出现过一次。 */}
      {isMobile && (
        <div
          role="toolbar"
          aria-label="阅读操作栏"
          className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-40 flex items-center gap-2 border-t bg-background/95 p-2 backdrop-blur"
        >
          {mode === 'pdf' && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="h-9 px-2"
                onClick={() => goToPage(page - 1)}
                aria-label="上一页"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {page}
                {totalPages ? `/${totalPages}` : ''}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="h-9 px-2"
                onClick={() => goToPage(page + 1)}
                aria-label="下一页"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </>
          )}
          {mode === 'md' && tocCount > 2 && (
            // 目录入口放在操作栏里，而不是正文右侧常驻悬浮按钮——
            // 后者会一直压住两三个字。
            <Button
              variant="outline"
              size="sm"
              className="h-9 shrink-0 gap-1 px-2"
              onClick={() => window.dispatchEvent(new Event(TOC_OPEN_EVENT))}
              aria-label="打开目录"
            >
              <ListTree className="h-4 w-4" />
              <span className="text-xs">目录</span>
            </Button>
          )}
          {data.has_file && (
            <Button asChild variant="outline" size="sm" className="h-9 shrink-0 gap-1 px-2">
              <a href={`/api/catalog/${id}/file`} download aria-label="下载原稿 PDF">
                <Download className="h-4 w-4" />
                <span className="text-xs">PDF</span>
              </a>
            </Button>
          )}
          {data.has_markdown && (
            <Button asChild variant="outline" size="sm" className="h-9 shrink-0 gap-1 px-2">
              <a
                href={`/api/catalog/${id}/export?format=docx`}
                aria-label="下载规范版 Word"
              >
                <FileText className="h-4 w-4" />
                <span className="text-xs">Word</span>
              </a>
            </Button>
          )}
          {isAuthenticated ? (
            <Button
              size="sm"
              className="h-9 flex-1"
              onClick={onManualUpdate}
              disabled={updateMut.isPending}
            >
              {updateMut.isPending ? '保存中…' : `保存进度 · ${progressPercent}%`}
            </Button>
          ) : (
            <Button asChild variant="outline" size="sm" className="h-9 flex-1">
              <Link to="/login" search={{ redirect: `/reader/${id}` }}>
                登录以同步进度
              </Link>
            </Button>
          )}
        </div>
      )}

      <ConfirmDialog
        open={removeOpen}
        title="移除阅读历史"
        description="确认移除该资源的阅读历史？此操作不可撤销。"
        confirmText="移除"
        destructive
        onOpenChange={setRemoveOpen}
        onConfirm={onRemove}
      />
    </div>
  )
}
