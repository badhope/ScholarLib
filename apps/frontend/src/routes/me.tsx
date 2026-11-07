import { createFileRoute, redirect } from '@tanstack/react-router'
import { useState } from 'react'
import { Award, Shield, Flame } from 'lucide-react'
import { getAuthState } from '@/lib/auth'
import { PageHeader } from '@/components/common/page-header'
import { ErrorState, Loading } from '@/components/common/state'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useMePoints, useMeProfile, type MeIdentityLevel } from '@/hooks/api/use-modules'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/me')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: MePage,
})

const IDENTITY_TABS = [
  { key: 'author', label: '作者' },
  { key: 'reviewer', label: '审稿人' },
  { key: 'editor', label: '编辑' },
] as const

const PERMISSION_BADGE: Record<string, string> = {
  user: 'bg-muted text-muted-foreground',
  reviewer: 'bg-sky-500/15 text-sky-600',
  editor: 'bg-amber-500/15 text-amber-600',
  editor_in_chief: 'bg-primary text-primary-foreground',
}

function LevelCard({ level }: { level: MeIdentityLevel }) {
  const pct = Math.max(0, Math.min(1, level.progress))
  return (
    <div className="rounded-xl border bg-muted/30 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 items-center rounded-full bg-primary/15 px-3 text-sm font-semibold tabular-nums text-primary">
            {level.level_label}
          </span>
          <span className="text-sm font-medium">{level.identity_name}等级</span>
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">
          {level.points} 分
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {level.next_threshold === null
          ? `已达${level.identity_name}最高等级`
          : `距下一级还差 ${level.to_next} 分（${level.next_threshold} 分升级）`}
      </p>
    </div>
  )
}

function MePage() {
  const { data, isLoading, isError, refetch } = useMeProfile()

  if (isLoading) return <Loading />
  if (isError || !data) return <ErrorState message="加载个人中心失败" onRetry={() => refetch()} />

  const owned = data.identities.filter((i) => i in data.levels)
  const multi = owned.length > 1

  return (
    <div className="space-y-6">
      <PageHeader
        title="我的"
        description="身份（权限轴）与身份内等级（激励轴）分轨展示，不同身份数值互不混排。"
      />

      {/* 当前身份（权限轴） */}
      <Card className="overflow-hidden">
        <div className="bg-gradient-to-br from-primary/[0.08] to-transparent p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={cn(
                'inline-flex h-9 items-center rounded-full px-3 text-sm font-semibold',
                PERMISSION_BADGE[data.permission_role],
              )}
            >
              <Shield className="mr-1.5 h-4 w-4" />
              {data.permission_label}
            </span>
            <h2 className="text-xl font-semibold">{data.username}</h2>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">当前权限：</p>
          <ul className="mt-1 grid gap-1 text-sm text-muted-foreground sm:grid-cols-2">
            {data.permissions.slice(0, 8).map((p) => (
              <li key={p} className="flex items-center gap-1.5">
                <span className="h-1 w-1 rounded-full bg-primary" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </Card>

      {/* 身份内等级（激励轴）：单身份直接展示，多身份用 Tab；无轨则给空态 */}
      {owned.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {data.permission_role === 'editor_in_chief' ? (
              <>
                <p className="font-medium text-foreground">主编（不设等级）</p>
                <p className="mt-1">主编为最高权限档，不参与 L/R/E 等级轨，也不与其他身份并列。</p>
              </>
            ) : (
              <>
                <p>暂无等级轨。</p>
                <p className="mt-1">投稿或文章被认领后，作者等级轨将在此展示。</p>
              </>
            )}
          </CardContent>
        </Card>
      ) : multi ? (
        <MultiIdentityTabbed owned={owned} levels={data.levels} />
      ) : (
        <div className="space-y-4">
          <LevelCard level={data.levels[owned[0]]} />
          <Ledger identity={owned[0]} />
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        等级只在同一身份内比较，不跨身份、不换权限；积分是荣誉与晋升信号。
      </p>
    </div>
  )
}

function MultiIdentityTabbed({
  owned,
  levels,
}: {
  owned: string[]
  levels: NonNullable<ReturnType<typeof useMeProfile>['data']>['levels']
}) {
  const visible = IDENTITY_TABS.map((t) => t.key).filter((k) => owned.includes(k))
  const [active, setActive] = useState(visible[0])
  const { data, isLoading } = useMePoints(active)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {visible.map((k) => {
          const t = IDENTITY_TABS.find((x) => x.key === k)!
          return (
            <button
              key={k}
              type="button"
              onClick={() => setActive(k)}
              className={cn(
                'inline-flex h-8 items-center rounded-full px-3 text-sm font-medium transition-colors',
                k === active
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/70',
              )}
            >
              {t.label}
              <span className="ml-1.5 tabular-nums">{levels[k]?.level_label}</span>
            </button>
          )
        })}
      </div>
      <LevelCard level={levels[active]} />
      {isLoading ? <Loading /> : data ? <LedgerList events={data.events} /> : null}
    </div>
  )
}

function Ledger({ identity }: { identity: string }) {
  const { data, isLoading } = useMePoints(identity)
  if (isLoading) return <Loading />
  if (!data) return null
  return <LedgerList events={data.events} />
}

function LedgerList({
  events,
}: {
  events: NonNullable<ReturnType<typeof useMePoints>['data']>['events']
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Flame className="h-4 w-4" /> 积分流水
        </CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            暂无积分记录。正式论文录用、完成审稿、认领通过后会累计。
          </p>
        ) : (
          <ul className="divide-y text-sm">
            {events.map((e, i) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate">
                  <Award className="mr-1.5 inline h-3.5 w-3.5 text-muted-foreground" />
                  {e.label}
                  {e.note ? (
                    <span className="text-muted-foreground"> · {e.note}</span>
                  ) : null}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {e.delta > 0 ? `+${e.delta}` : e.delta}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
