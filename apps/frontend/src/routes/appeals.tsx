import { createFileRoute } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import {
  useAppeals,
  useDecideAppeal,
  useMyAppeals,
  useMySubmissions,
  useSubmitAppeal,
  type AppealRow,
} from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, Loading } from '@/components/common/state'
import { MarkdownField } from '@/components/common/markdown-field'
import { extractError } from '@/lib/utils'
import { HelpTip } from '@/components/common/help-tip'

export const Route = createFileRoute('/appeals')({
  component: AppealsPage,
})

const KIND_LABEL: Record<string, string> = {
  withdraw: '撤回作品',
  rescore: '申请重审分数',
  rescore_zone: '申请重审分区',
}
const STATUS_LABEL: Record<string, string> = {
  pending: '待编辑部处理',
  accepted: '已受理',
  rejected: '未通过',
}

function AppealsPage() {
  const { user, isAdmin } = useAuth()
  const isEditor = isAdmin || (user?.roles ?? []).some((r) => ['editor', 'section_editor', 'board_editor', 'deputy_editor', 'chief_editor', 'editor_in_chief'].includes(r))
  const mine = useMyAppeals()
  const subs = useMySubmissions(undefined, 1, 100)
  const inbox = useAppeals(isEditor ? 'pending' : undefined)
  const submit = useSubmitAppeal()
  const decide = useDecideAppeal()
  const [resourceId, setResourceId] = useState('')
  const [kind, setKind] = useState('rescore')
  const [reason, setReason] = useState('')
  const [decideTarget, setDecideTarget] = useState<{ row: AppealRow; status: 'accepted' | 'rejected' } | null>(null)
  const [decisionNote, setDecisionNote] = useState('')
  const works = useMemo(() => (subs.data?.data ?? []).filter((s) => s.resource_id), [subs.data])
  const pending = inbox.data?.data ?? []

  const onSubmit = async () => {
    if (!resourceId) return toast.error('请选择要申诉的作品')
    if (reason.trim().length < 100) return toast.error('理由至少 100 字：请写清争议点、依据与希望编辑部采取的处理')
    try {
      await submit.mutateAsync({ resourceId: Number(resourceId), kind, reason: reason.trim() })
      setReason('')
      toast.success('申诉已提交，编辑部会逐条审核并回复')
    } catch (e) { toast.error(extractError(e, '提交失败')) }
  }

  const onDecide = (row: AppealRow, status: 'accepted' | 'rejected') => {
    setDecisionNote('')
    setDecideTarget({ row, status })
  }

  const confirmDecide = async () => {
    if (!decideTarget) return
    if (decisionNote.trim().length < 20) {
      toast.error('处置说明至少 20 字：作者需要知道依据与下一步')
      return
    }
    try {
      await decide.mutateAsync({
        id: decideTarget.row.id,
        status: decideTarget.status,
        editorNote: decisionNote.trim(),
      })
      toast.success(decideTarget.status === 'accepted' ? '已受理' : '已驳回')
      setDecideTarget(null)
      setDecisionNote('')
    } catch (e) { toast.error(extractError(e, '操作失败')) }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="作者申诉"
        description="对评审结论、分数或分区有异议，可在这里提交完整理由。撤回申请经编辑部批准后作品会下架；分数/分区重审由编辑记录处置结论。"
      />
      <p className="flex items-center gap-1 text-xs text-muted-foreground">
        <HelpTip text="理由需 100–3000 字；撤回不可逆，受理后作品下架；分数/分区重审由编辑给出处置说明。" />
        申诉类型与后果
      </p>
      <Card>
        <CardHeader><CardTitle className="text-base">提交申诉</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground">
            <p className="font-medium text-foreground">写之前先确认三件事</p>
            <p>① 先选对作品和类型：撤回不可逆，分数/分区重审不改作品状态。</p>
            <p>② 只写可核对的事实：哪一条结论、哪一段证据、哪个数字有异议；不要只写“我不服”。</p>
            <p>③ 写清你希望编辑部做什么：重算、补审、回避某位审稿人，还是撤回。</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span>选择作品</span>
              <select className="w-full rounded-md border bg-background px-3 py-2" value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
                <option value="">请选择</option>
                {works.map((s) => <option key={s.id} value={String(s.resource_id)}>{s.title}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span>申诉类型</span>
              <select className="w-full rounded-md border bg-background px-3 py-2" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="withdraw">撤回作品</option>
                <option value="rescore">重审分数</option>
                <option value="rescore_zone">重审分区</option>
              </select>
            </label>
          </div>
          <p className="text-[11px] leading-5 text-muted-foreground">
            当前选择：{kind === 'withdraw' ? '撤回作品——受理后作品下架，不可逆。' : kind === 'rescore' ? '重审分数——只复核分数，不改变发表状态。' : '重审分区——只复核分区，不改变分数。'}
          </p>
          <MarkdownField
            id="appeal-reason"
            label="完整理由（至少 100 字）"
            description="按「争议结论 → 核对依据 → 希望的处理方式」写。引用的数据、页码、审稿意见请写到可定位；需要回避某位审稿人时，只写理由，不要求提供身份。"
            value={reason}
            onChange={setReason}
            minRecommended={100}
            maxLength={3000}
            rows={8}
            template={`**争议的具体结论**\n\n……\n\n**我掌握的核对依据**\n\n- 原文第……页/第……节：……\n- 数据/引用：……\n\n**希望编辑部如何处理**\n\n……\n\n**是否需要回避审稿人**\n\n……（只写理由，不必写姓名）`}
            placeholder="写清：争议的具体结论、你掌握的核对依据、希望编辑部如何处理，以及是否需要回避某位审稿人。"
            disabled={submit.isPending}
          />
          <Button onClick={onSubmit} disabled={submit.isPending}>{submit.isPending ? '提交中…' : '提交编辑部审核'}</Button>
          <p className="text-xs text-muted-foreground">提示：同一作品同一类型只能有一条待处理申诉；收到处置后会出现在通知里。</p>
        </CardContent>
      </Card>

      <section>
        <h2 className="mb-3 text-lg font-semibold">我的申诉</h2>
        {mine.isLoading && <Loading />}
        {mine.data?.data.length === 0 && <EmptyState title="还没有申诉" description="如果你的稿件被撤回、分数或分区存在明显争议，可按上方表单提交。" />}
        <div className="space-y-3">
          {mine.data?.data.map((a) => (
            <Card key={a.id}>
              <CardContent className="space-y-2 pt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{KIND_LABEL[a.kind] ?? a.kind}</Badge>
                  <Badge variant={a.status === 'pending' ? 'secondary' : a.status === 'accepted' ? 'default' : 'destructive'}>{STATUS_LABEL[a.status] ?? a.status}</Badge>
                  <span className="text-sm text-muted-foreground">{a.resource_title}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm">{a.reason}</p>
                {a.editor_note && <p className="rounded bg-muted px-3 py-2 text-sm">编辑部回复：{a.editor_note}</p>}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {isEditor && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">编辑部待办（{pending.length}）</h2>
          {inbox.isLoading && <Loading />}
          {pending.length === 0 && <EmptyState title="没有待处理申诉" description="作者提交后会在这里出现，受理或驳回都要写处置说明。" />}
          <div className="space-y-3">
            {pending.map((a) => (
              <Card key={a.id}>
                <CardContent className="space-y-2 pt-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{KIND_LABEL[a.kind] ?? a.kind}</Badge>
                    <span className="text-sm font-medium">{a.resource_title}</span>
                    <span className="text-xs text-muted-foreground">申请人：{a.username}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{a.reason}</p>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => onDecide(a, 'accepted')} disabled={decide.isPending}>受理</Button>
                    <Button size="sm" variant="outline" onClick={() => onDecide(a, 'rejected')} disabled={decide.isPending}>驳回</Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <Dialog open={decideTarget !== null} onOpenChange={(open) => !open && setDecideTarget(null)}>
        <DialogContent className="max-h-[86vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{decideTarget?.status === 'accepted' ? '受理申诉' : '驳回申诉'}</DialogTitle>
            <DialogDescription className="space-y-1">
              <span className="block line-clamp-1">{decideTarget?.row.resource_title}</span>
              <span className="block text-xs">
                处置说明会原样发给作者：写清依据（哪条规则、哪段证据）和下一步，不要只写“维持原判”。
              </span>
            </DialogDescription>
          </DialogHeader>
          <MarkdownField
            id="appeal-decision-note"
            label={decideTarget?.status === 'accepted' ? '受理说明（作者可见）' : '驳回说明（作者可见）'}
            description="至少 20 字。受理时写清接下来会做什么、预计多久；驳回时写清依据和作者还能补充什么。"
            value={decisionNote}
            onChange={setDecisionNote}
            minRecommended={20}
            maxLength={1000}
            rows={6}
            template={`**依据**\n\n……\n\n**处理结果**\n\n……\n\n**下一步**\n\n……`}
            disabled={decide.isPending}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDecideTarget(null)}>取消</Button>
            <Button onClick={() => void confirmDecide()} disabled={decide.isPending}>
              {decide.isPending ? '提交中…' : decideTarget?.status === 'accepted' ? '确认受理' : '确认驳回'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
