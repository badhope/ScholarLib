import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  FileWarning,
  RefreshCw,
  Rocket,
  ShieldCheck,
} from 'lucide-react'
import { requireAdminGuard } from '@/lib/route-guards'
import {
  useCheckRelease,
  usePublishRelease,
  useReleaseIssues,
  useReleaseManifests,
} from '@/hooks/api/use-modules'
import type { ReleaseCheck, ReleaseManifest } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export const Route = createFileRoute('/admin/releases')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminReleasesPage,
})

const STATE_LABEL: Record<string, string> = {
  draft: '有草稿',
  live: '已上线',
  scheduled: '已排期',
  empty: '空期',
}

const LEVEL_STYLE: Record<ReleaseCheck['level'], string> = {
  error: 'border-destructive/30 bg-destructive/5 text-destructive',
  warning: 'border-amber-500/30 bg-amber-500/5 text-amber-700',
  info: 'border-border bg-muted/40 text-muted-foreground',
}

function detailMessage(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response
  const detail = response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const value = detail as { message?: string; code?: string; errors?: number }
    return [value.message, value.code ? `(${value.code})` : '', value.errors ? `错误 ${value.errors} 项` : '']
      .filter(Boolean)
      .join(' ')
  }
  return '请求失败，请查看网络或后端日志。'
}

function StatusPill({ manifest }: { manifest: ReleaseManifest }) {
  const config = {
    ready: ['可通过', 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30'],
    blocked: ['已阻塞', 'bg-destructive/10 text-destructive border-destructive/30'],
    scheduled: ['已排期', 'bg-sky-500/10 text-sky-700 border-sky-500/30'],
    published: ['已发布', 'bg-emerald-600 text-white border-emerald-600'],
    superseded: ['已失效', 'bg-muted text-muted-foreground border-border'],
  } as const
  const [label, cls] = config[manifest.status]
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}>{label}</span>
}

function AdminReleasesPage() {
  const { data, isLoading, isError, refetch } = useReleaseIssues()
  const [volume, setVolume] = useState('')
  const [issue, setIssue] = useState('')
  const [checked, setChecked] = useState<ReleaseManifest | null>(null)
  const [scheduleAt, setScheduleAt] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const issues = useMemo(() => data?.items ?? [], [data])
  const volumes = useMemo(
    () => Array.from(new Set(issues.map((item) => item.volume)).values()).sort((a, b) => b.localeCompare(a)),
    [issues],
  )
  const selectedIssues = useMemo(
    () => issues.filter((item) => item.volume === volume),
    [issues, volume],
  )
  const selected = useMemo(
    () => selectedIssues.find((item) => item.issue === issue) ?? null,
    [selectedIssues, issue],
  )

  const history = useReleaseManifests(volume, issue, Boolean(volume && issue))
  const latest = checked ?? history.data?.items[0] ?? null
  const check = useCheckRelease()
  const publish = usePublishRelease()

  const chooseVolume = (next: string) => {
    setVolume(next)
    setIssue('')
    setChecked(null)
    setNotice(null)
  }
  const chooseIssue = (next: string) => {
    setIssue(next)
    setChecked(null)
    setNotice(null)
  }

  const runCheck = async () => {
    setNotice(null)
    try {
      const manifest = await check.mutateAsync({ volume, issue })
      setChecked(manifest)
      setNotice(manifest.status === 'ready' ? '门禁通过，可以发布。' : `门禁未通过：${manifest.error_count} 个错误。`)
    } catch (error) {
      setNotice(detailMessage(error))
    }
  }

  const doPublish = async () => {
    if (!latest) return
    setNotice(null)
    try {
      const manifest = await publish.mutateAsync({
        volume,
        issue,
        manifestId: latest.id,
        publishAt: scheduleAt ? new Date(scheduleAt).toISOString() : null,
      })
      setChecked(manifest)
      setNotice(manifest.status === 'scheduled' ? `已排期到 ${manifest.publish_at}。` : '已发布，公开页立即生效。')
    } catch (error) {
      setNotice(detailMessage(error))
    }
  }

  if (isLoading) return <Loading />
  if (isError) return <ErrorState message="发布门禁加载失败" onRetry={() => void refetch()} />

  const checks = latest?.payload?.checks ?? []
  const resources = latest?.payload?.resources ?? []

  return (
    <div className="w-full max-w-6xl space-y-6">
      <PageHeader
        title="发布门禁"
        description="每次发布先生成不可变 Manifest：检查期内容、文件哈希与草稿混入，再允许发布或排期。"
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新期列表
          </Button>
        }
      />

      {!volume ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">选择要发布的期</CardTitle>
          </CardHeader>
          <CardContent>
            {issues.length === 0 ? (
              <EmptyState title="还没有可发布的期" description="先到卷管理/期管理建立卷期并导入文章。" />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {volumes.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => chooseVolume(item)}
                    className="rounded-xl border bg-card p-4 text-left shadow-sm transition-shadow hover:shadow-md"
                  >
                    <p className="text-sm font-medium">Vol. {item}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {issues.filter((i) => i.volume === item).length} 期 ·{' '}
                      {issues.filter((i) => i.volume === item).reduce((sum, i) => sum + i.total, 0)} 篇
                    </p>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-end">
              <div className="w-full sm:w-40">
                <label className="mb-1 block text-xs font-medium text-muted-foreground">卷</label>
                <select
                  value={volume}
                  onChange={(event) => chooseVolume(event.target.value)}
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                >
                  {volumes.map((item) => (
                    <option key={item} value={item}>
                      Vol. {item}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-full sm:w-40">
                <label className="mb-1 block text-xs font-medium text-muted-foreground">期</label>
                <select
                  value={issue}
                  onChange={(event) => chooseIssue(event.target.value)}
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                >
                  <option value="">选择期号</option>
                  {selectedIssues.map((item) => (
                    <option key={item.issue} value={item.issue}>
                      Issue {item.issue} · {STATE_LABEL[item.state]} · {item.total} 篇
                    </option>
                  ))}
                </select>
              </div>
              {selected ? (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">{selected.total} 篇</Badge>
                  <Badge variant="outline">{selected.published} 已上线</Badge>
                  {selected.scheduled > 0 ? <Badge variant="outline">{selected.scheduled} 已排期</Badge> : null}
                  {selected.draft > 0 ? <Badge variant="destructive">{selected.draft} 草稿</Badge> : null}
                </div>
              ) : null}
              <div className="sm:ml-auto">
                <Button onClick={() => void runCheck()} disabled={!issue || check.isPending}>
                  <ShieldCheck className="mr-1.5 h-4 w-4" />
                  {check.isPending ? '检查中…' : '运行发布门禁'}
                </Button>
              </div>
            </CardContent>
          </Card>

          {notice ? (
            <div className="rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">{notice}</div>
          ) : null}

          {!issue ? (
            <EmptyState title="选择一个期号" description="先运行门禁，再发布或排期。" />
          ) : !latest ? (
            <EmptyState
              title="这一期还没有 Manifest"
              description="点击「运行发布门禁」生成第一份不可变发布快照。"
              action={
                <Button variant="outline" size="sm" onClick={() => void runCheck()}>
                  <ShieldCheck className="mr-1 h-4 w-4" />
                  立即检查
                </Button>
              }
            />
          ) : (
            <>
              <Card>
                <CardHeader className="flex flex-row items-start justify-between gap-4 pb-2">
                  <div>
                    <CardTitle className="text-base">
                      Vol. {latest.volume} · Issue {latest.issue}
                    </CardTitle>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Manifest #{latest.id} · {latest.payload.gate_version} · 哈希 {latest.content_hash.slice(0, 12)}… · {latest.resource_count} 篇
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill manifest={latest} />
                    {latest.error_count > 0 ? (
                      <Badge variant="destructive">{latest.error_count} 错误</Badge>
                    ) : (
                      <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700" variant="outline">
                        {latest.warning_count} 警告
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {latest.error_count > 0 ? (
                    <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <div>
                        <p className="font-medium">门禁未通过，发布按钮已锁。</p>
                        <p className="mt-1 text-destructive/80">先处理下面所有 error 项，再重新运行检查。修改后旧 Manifest 会自动失效。</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm text-emerald-800">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                      <div>
                        <p className="font-medium">门禁通过。</p>
                        <p className="mt-1 text-emerald-800/80">发布前会再次核对内容哈希；如果这期间有人改了标题或文件，发布会拒绝并提示重新检查。</p>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <div className="w-full sm:w-64">
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">排期时间（留空即立即发布）</label>
                      <Input
                        type="datetime-local"
                        value={scheduleAt}
                        onChange={(event) => setScheduleAt(event.target.value)}
                      />
                    </div>
                    <Button
                      onClick={() => void doPublish()}
                      disabled={latest.status !== 'ready' || publish.isPending}
                    >
                      {scheduleAt ? <Clock3 className="mr-1.5 h-4 w-4" /> : <Rocket className="mr-1.5 h-4 w-4" />}
                      {publish.isPending ? '提交中…' : scheduleAt ? '排期发布' : '立即发布'}
                    </Button>
                    <p className="text-xs text-muted-foreground sm:pb-2">
                      只对 <code>published</code> 资源写入 publish_at，不动草稿。
                    </p>
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">检查项</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {checks.length === 0 ? (
                      <p className="text-sm text-muted-foreground">没有检查项。</p>
                    ) : (
                      checks.map((item, index) => (
                        <div
                          key={`${item.code}-${item.resource_id ?? 'issue'}-${index}`}
                          className={`rounded-lg border px-3 py-2 text-xs ${LEVEL_STYLE[item.level]}`}
                        >
                          <div className="flex items-center gap-2 font-medium">
                            {item.level === 'error' ? <FileWarning className="h-3.5 w-3.5" /> : null}
                            {item.level === 'warning' ? <AlertTriangle className="h-3.5 w-3.5" /> : null}
                            {item.level === 'info' ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
                            <span>{item.code}</span>
                            {item.resource_id ? <span className="opacity-70">#{item.resource_id}</span> : null}
                          </div>
                          <p className="mt-1 opacity-90">{item.message}</p>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">资源与文件</CardTitle>
                  </CardHeader>
                  <CardContent className="max-h-[520px] overflow-auto p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>#</TableHead>
                          <TableHead>标题</TableHead>
                          <TableHead>PDF</TableHead>
                          <TableHead>状态</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {resources.map((item) => (
                          <TableRow key={item.id}>
                            <TableCell className="text-xs text-muted-foreground">{item.id}</TableCell>
                            <TableCell className="max-w-56">
                              <p className="truncate text-xs font-medium">{item.title}</p>
                              <p className="truncate text-[11px] text-muted-foreground">{item.slug ?? '—'}</p>
                            </TableCell>
                            <TableCell>
                              {item.pdf.exists ? (
                                <Badge variant="outline" className="border-emerald-500/30 text-emerald-700">
                                  {(item.pdf.size / 1024).toFixed(0)}K
                                </Badge>
                              ) : item.markdown.exists ? (
                                <Badge variant="outline" className="border-sky-500/30 text-sky-700">
                                  MD
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-muted-foreground">
                                  无源
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell className="text-xs">{item.publication_status}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </div>

              {history.data?.items?.length ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Manifest 历史</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>#</TableHead>
                          <TableHead>状态</TableHead>
                          <TableHead>资源</TableHead>
                          <TableHead>错误</TableHead>
                          <TableHead>时间</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {history.data.items.map((item) => (
                          <TableRow key={item.id}>
                            <TableCell className="text-xs">{item.id}</TableCell>
                            <TableCell className="text-xs">{item.status}</TableCell>
                            <TableCell className="text-xs">{item.resource_count}</TableCell>
                            <TableCell className="text-xs">{item.error_count}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              ) : null}
            </>
          )}
        </>
      )}

      <Button asChild variant="ghost" size="sm">
        <Link to="/admin/issues">
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回期管理
        </Link>
      </Button>
    </div>
  )
}
