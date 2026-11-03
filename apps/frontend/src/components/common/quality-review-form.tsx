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

/** 把一个维度内的答案折算成 0–5 建议分（与后端同一公式）。 */
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
  if (totalWeight === 0) return 3
  return Math.round((5 * earned) / totalWeight * 10) / 10
}

interface Props {
  articleType?: string
  /** 提交评分：交给父组件落库（目前审稿报告走 review 端点） */
  onSubmit?: (result: { dimensions: DimensionScoreInput[]; total: number; grade: string }) => void
  readOnly?: boolean
}

/**
 * 审稿评分表（RQS v2.0）。
 *
 * 交互设计刻意是「先勾事实、再给判断」：审稿人先把每个维度下的检查项
 * 逐条答「是/部分/否/不适用」，系统折算建议分；审稿人可以覆盖建议分，
 * 但必须写理由。这样两个审稿人对同一篇稿子的分歧会落在"哪条事实判断
 * 不同"，而不是"我感觉这稿子值 3 分还是 4 分"——后者无法仲裁。
 */
export function QualityReviewForm({ articleType = 'research', onSubmit, readOnly }: Props) {
  const formQ = useQualityForm()
  const scoreMut = useComputeQualityScore()
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
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
      reason: reasons[d.key]?.trim() || `按检查项折算建议分 ${suggested[d.key]} 分`,
    }))
    const result = await scoreMut.mutateAsync({ article_type: articleType, dimensions: payload })
    onSubmit?.({ dimensions: payload, total: result.score, grade: result.grade })
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <ClipboardCheck className="h-4 w-4" />
            审稿评分表（RQS v2.0）
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
                <span className="font-semibold tabular-nums">{finalScore(dim.key)}/5</span>
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
                      max={5}
                      step={0.5}
                      disabled={readOnly}
                      value={finalScore(dim.key)}
                      onChange={(e) =>
                        setOverrides((p) => ({ ...p, [dim.key]: Number(e.target.value) }))
                      }
                      className="flex-1"
                      aria-label={`${dim.label} 覆盖建议分`}
                    />
                    <span className="w-8 text-right text-xs tabular-nums">
                      {finalScore(dim.key)}
                    </span>
                  </div>
                  <Textarea
                    placeholder="给这个分的理由（必填，引用正文具体位置）"
                    value={reasons[dim.key] ?? ''}
                    disabled={readOnly}
                    onChange={(e) => setReasons((p) => ({ ...p, [dim.key]: e.target.value }))}
                    rows={2}
                    className="text-xs"
                  />
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
            学术诚信维度为 0 分时全篇直接判 D（一票否决）。D 级不会直接拒稿，
            而是打回：编辑部会要求你补审或说明理由，同时把修改要求发给作者。
          </p>
          {scoreMut.data && (
            <p className="text-sm">
              合计 <strong className="tabular-nums">{scoreMut.data.score}</strong> 分 ·{' '}
              {scoreMut.data.grade} {scoreMut.data.grade_label}
              {scoreMut.data.requires_rework && (
                <span className="ml-2 text-destructive">（D 级将被打回）</span>
              )}
            </p>
          )}
          <Button
            className="w-full"
            disabled={readOnly || scoreMut.isPending || answeredCount < totalItems}
            onClick={submit}
          >
            {scoreMut.isPending
              ? '计算中…'
              : answeredCount < totalItems
                ? `请完成全部检查项（${answeredCount}/${totalItems}）`
                : '生成评分'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
