import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Eye,
  Info,
  Pencil,
} from 'lucide-react'
import type { Recommendation } from '@/lib/types'
import {
  RubricScoreFields,
  TRACK_DIMENSIONS,
  TRACK_LABELS,
  dimensionLabel,
  emptyDimensionReviews,
  reviewAverage,
  scoreReviewTotal,
  type DimensionReviews,
  type ReviewTrack,
} from '@/components/review/rubric-score-fields'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'

export interface ReviewFormValue {
  recommendation: Recommendation
  track: ReviewTrack
  dimensions: DimensionReviews
  comments_to_editor: string
  comments_to_author: string
  special_issue: boolean
  special_issue_reason: string
}

export const RECOMMENDATION_OPTIONS: {
  value: Recommendation
  label: string
  short: string
  when: string
}[] = [
  {
    value: 'accept',
    label: '接收（Accept）',
    short: '可直接发表',
    when: '论证与证据完整，剩余问题只是编辑性修改；你愿意为这篇的结论背书。',
  },
  {
    value: 'minor_revision',
    label: '小修（Minor Revision）',
    short: '小改后发表',
    when: '结论成立，但有个别数据、引用或表述需要澄清；修改可在一次轮回内完成。',
  },
  {
    value: 'major_revision',
    label: '大修（Major Revision）',
    short: '实质补强后再审',
    when: '问题可以补，但需要新增证据、重做分析或重构论证；改完必须回看。',
  },
  {
    value: 'reject',
    label: '拒稿（Reject）',
    short: '不适合本刊或无法补救',
    when: '核心问题不成立、存在伦理/诚信硬伤，或与本刊范围不符且修改也无法解决。',
  },
]

export const EMPTY_REVIEW_FORM: ReviewFormValue = {
  recommendation: 'minor_revision',
  track: 'academic',
  dimensions: emptyDimensionReviews('academic'),
  comments_to_editor: '',
  comments_to_author: '',
  special_issue: false,
  special_issue_reason: '',
}

const AUTHOR_TEMPLATE = `**总体判断**
这篇稿子试图回答的问题是：……；我认为它目前处于……水平。

**主要问题（按重要性排序）**
1. ……
2. ……
3. ……

**可执行的修改建议**
- 针对问题 1：……
- 针对问题 2：……

**哪些部分做得好**
……

**修改后需要重点复核的地方**
……`

const EDITOR_TEMPLATE = `**给编辑的判断**
- 推荐决定及理由：……
- 这篇稿子最适合/最不适合本刊的地方：……
- 是否存在伦理、引用或数据可信度疑点：……
- 修改后需要编辑部重点核对：……`

function reviewFieldLabel(key: string, track: ReviewTrack = 'academic'): string {
  return dimensionLabel(track, key)
}

function MarkdownPreview({ value, empty }: { value: string; empty: string }) {
  if (!value.trim()) {
    return <p className="text-sm text-muted-foreground">{empty}</p>
  }
  return (
    <div className="markdown-body text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
    </div>
  )
}

function ReviewTextField({
  id,
  label,
  description,
  value,
  onChange,
  placeholder,
  template,
  minRecommended = 0,
  disabled,
}: {
  id: string
  label: string
  description: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  template: string
  minRecommended?: number
  disabled?: boolean
}) {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')
  const count = value.trim().length
  const tooShort = minRecommended > 0 && count > 0 && count < minRecommended

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Label htmlFor={id}>{label}</Label>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{description}</p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onChange(value.trim() ? `${value.trim()}\n\n${template}` : template)}
            disabled={disabled}
          >
            <ClipboardList className="h-3.5 w-3.5" />
            插入模板
          </Button>
          <Button
            type="button"
            variant={mode === 'preview' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => setMode((m) => (m === 'edit' ? 'preview' : 'edit'))}
          >
            {mode === 'edit' ? <Eye className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
            {mode === 'edit' ? '预览' : '继续编辑'}
          </Button>
        </div>
      </div>
      {mode === 'edit' ? (
        <Textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={7}
          disabled={disabled}
        />
      ) : (
        <div className="min-h-[9rem] rounded-md border bg-muted/20 px-3 py-2.5">
          <MarkdownPreview value={value} empty="还没有填写，切换到「继续编辑」开始写。" />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
        <span className={cn('text-muted-foreground', tooShort && 'text-amber-700 dark:text-amber-300')}>
          已写 {count} 字{minRecommended > 0 ? ` · 建议不少于 ${minRecommended} 字` : ''}
        </span>
        <span className="text-muted-foreground">支持 Markdown；预览只在本机显示，不会提前提交。</span>
      </div>
    </div>
  )
}

export function ReviewReportFields({
  value,
  onChange,
  disabled,
}: {
  value: ReviewFormValue
  onChange: (value: ReviewFormValue) => void
  disabled?: boolean
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const average = useMemo(() => reviewAverage(value.track, value.dimensions), [value.track, value.dimensions])
  const summary = useMemo(() => scoreReviewTotal(value.track, value.dimensions), [value.track, value.dimensions])
  const dims = TRACK_DIMENSIONS[value.track]
  const selectedRecommendation =
    RECOMMENDATION_OPTIONS.find((o) => o.value === value.recommendation) ?? RECOMMENDATION_OPTIONS[1]

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-primary/25 bg-primary/[0.06] p-3 text-xs leading-5 text-foreground dark:border-primary/25 dark:bg-primary/10">
        <p className="flex items-center gap-1.5 font-medium">
          <Info className="h-3.5 w-3.5" /> 填写前先过一遍这四问
        </p>
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
          <li>这篇稿子到底回答了什么可回答的问题？</li>
          <li>结论的前提和证据在哪？有没有跳跃或把相关当因果？</li>
          <li>别人能不能照着方法复现？不能的话，缺哪一项？</li>
          <li>有没有伦理、引用真实性或数据可信度的硬伤？</li>
        </ul>
        <p className="mt-1.5 text-[11px] text-sky-800/80 dark:text-sky-200/70">
          单盲：作者看不到你的身份；但「给作者的意见」会原文展示，请只写可以公开的评语。
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="recommendation">推荐决定</Label>
        <Select
          value={value.recommendation}
          onValueChange={(v) => onChange({ ...value, recommendation: v as Recommendation })}
          disabled={disabled}
        >
          <SelectTrigger id="recommendation" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RECOMMENDATION_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="rounded-md bg-muted/40 px-2.5 py-2 text-[11px] leading-5 text-muted-foreground">
          <span className="font-medium text-foreground">{selectedRecommendation.short}：</span>
          {selectedRecommendation.when}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label>评分赛道</Label>
          <span className="text-[11px] text-muted-foreground">两套维度，不共用一把尺子</span>
        </div>
        <div className="grid grid-cols-2 gap-1.5 rounded-lg border bg-muted/30 p-1.5">
          {(['academic', 'absurd'] as ReviewTrack[]).map((t) => (
            <button
              key={t}
              type="button"
              disabled={disabled}
              onClick={() => onChange({ ...value, track: t, dimensions: emptyDimensionReviews(t) })}
              className={cn(
                'rounded-md px-2 py-1.5 text-xs transition-colors',
                value.track === t ? 'bg-primary text-primary-foreground' : 'hover:bg-background',
              )}
            >
              {TRACK_LABELS[t]}
            </button>
          ))}
        </div>
        <p className="text-[11px] leading-5 text-muted-foreground">
          {value.track === 'academic'
            ? '学术赛道：选题、论证、方法、证据、诚信。90+ 才是顶刊级；缺方法/证据会封顶，不允许用平均分抬进一区。'
            : '荒诞赛道：审设定、自洽、执行、材料、文风。允许无中生有，不按样本量与伦理审批扣分；但前后打架、堆梗不成篇会封顶。'}
        </p>
        <RubricScoreFields
          track={value.track}
          reviews={value.dimensions}
          onChange={(dimensions) => onChange({ ...value, dimensions })}
          disabled={disabled}
        />
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-3 dark:border-amber-500/20 dark:bg-amber-950/20">
        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 accent-amber-600"
            checked={value.special_issue}
            onChange={(e) => onChange({ ...value, special_issue: e.target.checked })}
            disabled={disabled}
          />
          <span>
            <strong>特别篇（篇幅特许）</strong>
            <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
              仅当稿件因内容完整性必须超过篇幅上限时勾选。通过后阅读端会显示「特别篇」标签，并记录本次特许理由；
              不要用它绕过正常删减。
            </span>
          </span>
        </label>
        {value.special_issue ? (
          <div className="mt-2 space-y-1.5">
            <Textarea
              className="bg-background"
              value={value.special_issue_reason}
              onChange={(e) => onChange({ ...value, special_issue_reason: e.target.value })}
              placeholder="必填（不少于 10 字）：说明为什么这篇必须超篇幅，例如首次给出完整机制模型、附录不可拆分、数据表本身是论证的一部分。"
              rows={2}
              maxLength={500}
              disabled={disabled}
            />
            <p
              className={cn(
                'text-[11px]',
                value.special_issue_reason.trim().length < 10
                  ? 'text-amber-700 dark:text-amber-300'
                  : 'text-muted-foreground',
              )}
            >
              已写 {value.special_issue_reason.trim().length} 字 · 至少 10 字才能提交
            </p>
          </div>
        ) : null}
      </div>

      <ReviewTextField
        id="comments_to_author"
        label="给作者的意见（作者可见）"
        description="按「总体判断 → 主要问题排序 → 可执行修改 → 做得好的地方 → 修改后复核点」写。不要写身份线索、不要只写“建议拒稿”而不给理由。"
        value={value.comments_to_author}
        onChange={(v) => onChange({ ...value, comments_to_author: v })}
        placeholder="作者会原文看到这段。请写具体到段落/图表/论点的意见，并给出可执行的下一步。"
        template={AUTHOR_TEMPLATE}
        minRecommended={200}
        disabled={disabled}
      />

      <ReviewFieldDivider />

      <ReviewTextField
        id="comments_to_editor"
        label="给编辑的保密意见（可选，作者不可见）"
        description="只写不适合让作者看到的内容：推荐决定背后的权衡、伦理/引用疑点、是否需要额外审稿人、与本刊范围的匹配度。"
        value={value.comments_to_editor}
        onChange={(v) => onChange({ ...value, comments_to_editor: v })}
        placeholder="例如：方法部分有一处样本量未交代，建议作者补数据；另有一位审稿人可能更合适。"
        template={EDITOR_TEMPLATE}
        minRecommended={80}
        disabled={disabled}
      />

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed bg-muted/20 px-3 py-2.5">
        <p className="text-[11px] leading-5 text-muted-foreground">
          提交前建议先看一遍：作者视角只展示「给作者的意见」，编辑视角还会看到评分与保密意见。
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => setPreviewOpen(true)}>
          <Eye className="h-4 w-4" />
          预览完整报告
        </Button>
      </div>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-h-[86vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>审稿报告预览</DialogTitle>
            <DialogDescription>
              提交前的本地预览，不会写入数据库。作者实际只看到「给作者的意见」；评分和保密意见只给编辑。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{selectedRecommendation.label}</Badge>
              <Badge variant="outline">{TRACK_LABELS[value.track]}</Badge>
              <span className="text-xs text-muted-foreground">
                合计 {summary.total} 分 · {summary.grade} {summary.gradeLabel}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {dims.map((d) => (
                <div key={d.key} className="rounded border px-2 py-1.5 text-xs">
                  <span className="text-muted-foreground">{d.label}</span>
                  <span className="ml-1 font-medium tabular-nums">
                    {value.dimensions[d.key]?.score ?? '未评'}
                  </span>
                </div>
              ))}
            </div>
            <div className="space-y-1.5">
              {dims.map((d) => {
                const item = value.dimensions[d.key]
                return (
                  <div key={d.key} className="rounded border bg-muted/20 px-2 py-1.5 text-xs">
                    <p className="font-medium">
                      {d.label}：{item?.score ?? '未评'} 分
                    </p>
                    <p className="text-muted-foreground">理由：{item?.reason || '（未填）'}</p>
                    <p className="text-muted-foreground">证据：{item?.evidence || '（未填）'}</p>
                  </div>
                )
              })}
            </div>
            <div>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> 作者可见
              </p>
              <div className="rounded-md border bg-card px-3 py-2">
                <MarkdownPreview value={value.comments_to_author} empty="尚未填写给作者的意见。" />
              </div>
            </div>
            {value.comments_to_editor.trim() ? (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-300">
                  <AlertTriangle className="h-3.5 w-3.5" /> 仅编辑可见
                </p>
                <div className="rounded-md border border-amber-200 bg-amber-50/50 px-3 py-2 dark:border-amber-500/20 dark:bg-amber-950/20">
                  <MarkdownPreview value={value.comments_to_editor} empty="" />
                </div>
              </div>
            ) : null}
            {value.special_issue ? (
              <p className="rounded-md bg-muted/40 px-2.5 py-2 text-xs text-muted-foreground">
                特别篇理由：{value.special_issue_reason || '（未填写）'}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" onClick={() => setPreviewOpen(false)}>
              回到编辑
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ReviewFieldDivider() {
  return <div className="h-px bg-border" />
}

export function reviewFormAverage(track: ReviewTrack, dimensions: DimensionReviews): string {
  return reviewAverage(track, dimensions)
}

export function reviewScoreLabel(key: string, track: ReviewTrack = 'academic'): string {
  return reviewFieldLabel(key, track)
}
