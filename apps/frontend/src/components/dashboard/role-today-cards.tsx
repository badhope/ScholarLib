import { Link } from '@tanstack/react-router'
import { ArrowRight, ClipboardList, FilePenLine, Inbox } from 'lucide-react'
import { useAuth } from '@/hooks/use-auth'
import {
  useEditorWorkbench,
  useMySubmissions,
  useTriageQueue,
} from '@/hooks/api/use-modules'
import { Card } from '@/components/ui/card'

/** 作者 Today：只提示“要改的、在外审的、刚投的”，不重复投稿列表。 */
function AuthorTodayCard() {
  const { user, isAdmin } = useAuth()
  const roles = user?.roles ?? []
  const canAuthor =
    isAdmin ||
    roles.some((role) =>
      ['author', 'editor', 'section_editor', 'editor_in_chief'].includes(role),
    )
  const mine = useMySubmissions(undefined, 1, 50, { enabled: canAuthor })
  if (!canAuthor) return null

  const rows = mine.data?.data ?? []
  const revisionCount = rows.filter((row) =>
    ['major_revision', 'minor_revision', 'rework_requested'].includes(row.status),
  ).length
  const inReviewCount = rows.filter((row) =>
    ['pending', 'under_review', 'resubmitted'].includes(row.status),
  ).length
  const latest = rows[0]

  return (
    <Card className="px-4 py-3" data-testid="author-today">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
            <FilePenLine className="h-5 w-5" aria-hidden />
          </div>
          <div>
            <p className="text-sm font-medium">今天要改的稿</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {mine.isLoading
                ? '正在读取我的投稿…'
                : revisionCount > 0
                  ? `${revisionCount} 篇待修改 · ${inReviewCount} 篇在审/待处理`
                  : inReviewCount > 0
                    ? `${inReviewCount} 篇在审/待处理，暂无待修改`
                    : '暂无待修改稿件，保持这个节奏。'}
            </p>
          </div>
        </div>
        <Link
          to="/submissions"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          我的投稿 <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Link
          to="/submissions"
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="text-xs text-muted-foreground">待修改</span>
          <span className="font-semibold tabular-nums">{revisionCount}</span>
        </Link>
        <Link
          to="/submissions"
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="text-xs text-muted-foreground">在审/待处理</span>
          <span className="font-semibold tabular-nums">{inReviewCount}</span>
        </Link>
      </div>
      {latest ? (
        <p className="mt-2 truncate text-xs text-muted-foreground">
          最近投稿：{latest.title}
        </p>
      ) : null}
    </Card>
  )
}

/** 编辑 Today：把初筛、待指派、待裁决三件事压成一张卡。 */
function EditorTodayCard() {
  const { user, isAdmin } = useAuth()
  const roles = user?.roles ?? []
  const canEdit =
    isAdmin ||
    roles.some((role) =>
      ['editor', 'section_editor', 'editor_in_chief'].includes(role),
    )
  const triage = useTriageQueue(1, 1, { enabled: canEdit })
  const workbench = useEditorWorkbench({ enabled: canEdit })
  if (!canEdit) return null

  const columns = workbench.data?.columns
  const triageCount = triage.data?.meta.total ?? 0
  const toAssign = columns?.to_assign.count ?? 0
  const toDecide = columns?.to_decide.count ?? 0

  return (
    <Card className="px-4 py-3" data-testid="editor-today">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300">
            <ClipboardList className="h-5 w-5" aria-hidden />
          </div>
          <div>
            <p className="text-sm font-medium">今天要处理的稿</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              初筛 {triageCount} 篇 · 待指派 {toAssign} 篇 · 待裁决 {toDecide} 篇
            </p>
          </div>
        </div>
        <Link
          to="/editor/workbench"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          编辑台 <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Link
          to="/editor/triage"
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="text-xs text-muted-foreground">待初筛</span>
          <span className="font-semibold tabular-nums">{triageCount}</span>
        </Link>
        <Link
          to="/editor/workbench"
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="text-xs text-muted-foreground">待指派</span>
          <span className="font-semibold tabular-nums">{toAssign}</span>
        </Link>
        <Link
          to="/editor/workbench"
          className="flex items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Inbox className="h-3.5 w-3.5" aria-hidden />
            待裁决
          </span>
          <span className="font-semibold tabular-nums">{toDecide}</span>
        </Link>
      </div>
    </Card>
  )
}

export function RoleTodayCards() {
  return (
    <div className="mt-3 grid gap-3 lg:grid-cols-2">
      <AuthorTodayCard />
      <EditorTodayCard />
    </div>
  )
}
