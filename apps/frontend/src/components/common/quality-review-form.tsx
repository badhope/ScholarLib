import { useMemo, useState } from 'react'
import { ClipboardCheck, Info } from 'lucide-react'
import { useQualityForm, useComputeQualityScore } from '@/hooks/api/use-modules'
import type { DimensionScoreInput, QualityForm } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Loading, ErrorState } from '@/components/common/state'
import { cn } from '@/lib/utils'

const ANSWER_OPTIONS = [
  { value: 'yes', label: '是' },
  { value: 'partial', label: '部分' },
  { value: 'no', label: '否' },
  { value: 'na', label: '不适用' },
] as const

const ANSWER_POINTS: Record<string, number> = { yes: 1, partial: 0.5, no: 0, na: 0 }

/** 把一个维度内的答案折算成 0–100 建议分（v4.0，与后端同一公式）。 */
function suggestScore(form: QualityForm, dimensionKey: string, answers: Record<string, string>) {
  const dim = form.dimensions.find((d) => d.key === dimensionKey)
  if (!dim) return 0
  let earned = 0
  let totalWeight = 0
  for (const item of dim.items) {
    const ans = answers[item.key]
    if (ans === undefined) {
      totalWeight += item.weight
      continue
    }
    if (ans === 'na') continue
    totalWeight += item.weight
    earned += item.weight * (ANSWER_POINTS[ans] ?? 0)
  }
  if (totalWeight === 0) return 60
  return Math.round((100 * earned) / totalWeight * 10) / 10
}

interface Props {
  articleType?: string
  /** 提交评分：交给父组件落库（目前审稿报告走 review 端点） */
  onSubmit?: (result: { dimensions: DimensionScoreInput[]; total: number; grade: string }) => void
  readOnly?: boolean
}

/**
 * 审稿评分表（评审质量分，七维百分制 + ABCDEF 全字母制）。
 *
 * 交互设计刻意是「先勾事实、再给判断」：审稿人先把每个维度下的检查项
 * 逐条答「是/部分/否/不适用」，系统折算建议分；审稿人可以覆盖建议分，
 * 但必须写理由。这样两个审稿人对同一篇稿子的分歧会落在"哪条事实判断
 * 不同"，而不是"我感觉这稿子值 3 分还是 4 分"——后者无法仲裁。
 */
export function QualityReviewForm({ articleType = 'research', onSubmit, readOnly }: Props) {
  const [track, setTrack] = useState<'academic' | 'absurd'>('academic')
  const formQ = useQualityForm(track)
  const scoreMut = useComputeQualityScore()
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [evidences, setEvidences] = useState<Record<string, string>>({})
  const [activeDim, setActiveDim] = useState<string | null>(null)

  const form = formQ.data
  const dimensions = form?.dimensions ?? []

  const suggested = useMemo(() => {
    if (!form) return {} as Record<string, number>
    const out: Record<string, number> = {}
    for (const d of form.dimensions) out[d.key] = suggestScore(form, d.key, answers)
    return out
  }, [form, answers])

  if (formQ.isLoading) return <Loading />
  if (formQ.isError || !form) {
    return <ErrorState message="加载评分表失败" onRetry={() => formQ.refetch()} />
  }

  const finalScore = (key: string) => overrides[key] ?? suggested[key] ?? 0
  const answeredCount = Object.keys(answers).length
  const totalItems = dimensions.reduce((n, d) => n + d.items.length, 0)

  const submit = async () => {
    const payload: DimensionScoreInput[] = dimensions.map((d) => ({
      key: d.key,
      score: Math.round(finalScore(d.key)),
      reason: reasons[d.key]?.trim() ?? '',
      evidence: evidences[d.key]?.trim() ?? '',
    }))
    const result = await scoreMut.mutateAsync({ track, article_type: articleType, dimensions: payload })
    onSubmit?.({ dimensions: payload, total: result.score, grade: result.grade })
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <ClipboardCheck className="h-4 w-4" />
            审稿评分表（评审质量分）
            <Badge variant="outline" className="ml-auto text-[10px]">
              已作答 {answeredCount}/{totalItems}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          先逐条回答事实性检查项，系统据此给出建议分；你可以覆盖建议分，但必须写理由。
          覆盖的理由会作为修改指引发给作者。
        </CardContent>
      </Card>

      <div className="flex gap-1.5 rounded-lg border bg-muted/30 p-1.5">
        {(['academic', 'absurd'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => {
              setTrack(t)
              setAnswers({})
              setOverrides({})
              setReasons({})
              setEvidences({})
            }}
            className={cn(
              'flex-1 rounded-md px-2 py-1.5 text-xs transition-colors',
              track === t ? 'bg-primary text-primary-foreground' : 'hover:bg-background',
            )}
          >
            {t === 'academic' ? '学术赛道' : '荒诞赛道'}
          </button>
        ))}
      </div>

      {dimensions.map((dim) => {
        const open = activeDim === dim.key
        const ans = answers
        const answered = dim.items.filter((i) => ans[i.key] !== undefined).length
        return (
          <Card key={dim.key} className={cn(open && 'ring-1 ring-primary/30')}>
            <button
              type="button"
              className="flex w-full items-center justify-between px-5 py-3 text-left"
              onClick={() => setActiveDim(open ? null : dim.key)}
            >
              <span>
                <span className="text-sm font-medium">{dim.label}</span>
                <span className="ml-2 text-[11px] text-muted-foreground">{dim.hint}</span>
              </span>
              <span className="flex items-center gap-2 text-xs">
                <Badge variant="secondary" className="tabular-nums">
                  {answered}/{dim.items.length}
                </Badge>
                <span className="font-semibold tabular-nums">{finalScore(dim.key)}/100</span>
              </span>
            </button>
            {open && (
              <CardContent className="space-y-3 border-t pt-3">
                {dim.items.map((item) => (
                  <div key={item.key} className="space-y-1.5">
                    <p className="text-[13px] leading-relaxed">
                      {item.question}
                      {item.weight > 1 && (
                        <Badge variant="outline" className="ml-1.5 text-[9px]">
                          关键
                        </Badge>
                      )}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {ANSWER_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          disabled={readOnly}
                          aria-pressed={ans[item.key] === opt.value}
                          onClick={() =>
                            setAnswers((prev) => ({ ...prev, [item.key]: opt.value }))
                          }
                          className={cn(
                            'rounded-full border px-3 py-1 text-xs transition-colors',
                            ans[item.key] === opt.value
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-input hover:bg-muted',
                          )}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="space-y-1.5 border-t pt-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">覆盖建议分</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={1}
                      disabled={readOnly}
                      value={finalScore(dim.key)}
                      onChange={(e) =>
                        setOverrides((p) => ({ ...p, [dim.key]: Number(e.target.value) }))
                      }
                      className="flex-1"
                      aria-label={`${dim.label} 覆盖建议分`}
                    />
                    <span className="w-10 text-right text-xs tabular-nums">
                      {finalScore(dim.key)}
                    </span>
                  </div>
                  <Textarea
                    placeholder="为什么给这个分（必填，至少 4 字）"
                    value={reasons[dim.key] ?? ''}
                    disabled={readOnly}
                    onChange={(e) => setReasons((p) => ({ ...p, [dim.key]: e.target.value }))}
                    rows={2}
                    className="text-xs"
                    aria-label={`${dim.label} 评分理由`}
                  />
                  <Textarea
                    placeholder="正文证据（必填，至少 8 字）：章节/段落/图号/表号/引用编号/链接"
                    value={evidences[dim.key] ?? ''}
                    disabled={readOnly}
                    onChange={(e) => setEvidences((p) => ({ ...p, [dim.key]: e.target.value }))}
                    rows={2}
                    className="text-xs"
                    aria-label={`${dim.label} 正文证据`}
                  />
                  {(reasons[dim.key]?.trim().length ?? 0) < 4 ||
                  (evidences[dim.key]?.trim().length ?? 0) < 8 ? (
                    <p className="text-[11px] text-amber-700 dark:text-amber-300">
                      该维度需同时补齐理由（≥4 字）与正文证据（≥8 字）才能计分。
                    </p>
                  ) : null}
                </div>
              </CardContent>
            )}
          </Card>
        )
      })}

      <Card>
        <CardContent className="space-y-2 py-4">
          <p className="flex items-start gap-2 text-[11px] text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            学术赛道诚信维度为 0 分时总分归零（一票否决）。总分低于 50 分为退稿、
            不入区；任一维度低于 60 分会封顶 79，低于 50 分会封顶 59。没有理由或
            没有正文证据的维度不计分，也不允许用平均分抬档。
          </p>
          {scoreMut.data && (
            <p className="text-sm">
              合计 <strong className="tabular-nums">{scoreMut.data.score}</strong> 分 ·{' '}
              {scoreMut.data.grade} {scoreMut.data.grade_label}
              {scoreMut.data.requires_rework && (
                <span className="ml-2 text-destructive">（不合格，将被打回）</span>
              )}
              {scoreMut.data.borderline && (
                <span className="ml-2 text-muted-foreground">（边缘稿，编辑将谨慎处理）</span>
              )}
            </p>
          )}
          <Button
            className="w-full"
            disabled={
              readOnly ||
              scoreMut.isPending ||
              answeredCount < totalItems ||
              dimensions.some(
                (d) =>
                  (reasons[d.key]?.trim().length ?? 0) < 4 ||
                  (evidences[d.key]?.trim().length ?? 0) < 8,
              )
            }
            onClick={submit}
          >
            {scoreMut.isPending
              ? '计算中…'
              : answeredCount < totalItems
                ? `请完成全部检查项（${answeredCount}/${totalItems}）`
                : dimensions.some(
                      (d) =>
                        (reasons[d.key]?.trim().length ?? 0) < 4 ||
                        (evidences[d.key]?.trim().length ?? 0) < 8,
                    )
                  ? '请补齐每维理由与证据'
                  : '生成评分'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
