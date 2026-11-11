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
  scores: Record<string, number>
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

export const SCORE_DIMENSIONS: {
  key: string
  label: string
  hint: string
  watch: string
}[] = [
  {
    key: 'problem',
    label: '问题价值',
    hint: '研究问题是否真实、具体、值得回答',
    watch: '看它有没有被写成可回答的问题，而不是只给一个主题；再看“为什么这个问题还没被回答”。',
  },
  {
    key: 'argument',
    label: '论证链',
    hint: '从前提走到结论有无跳跃与循环论证',
    watch: '逐段问：这个结论的前提在哪？有没有从 A 直接跳到 C，或用结论反过来证明前提？',
  },
  {
    key: 'method',
    label: '方法透明度',
    hint: '他人能否照此复现',
    watch: '数据来源、样本、筛选标准、关键参数、失败案例是否交代到别人能照着做。',
  },
  {
    key: 'evidence',
    label: '证据强度',
    hint: '结论是否被证据支撑',
    watch: '弱证据有没有被写成强结论；相关性有没有被说成因果；样本量够不够。',
  },
  {
    key: 'novelty',
    label: '创新与定位',
    hint: '相对已有工作补了哪一块',
    watch: '增量是否在正文里兑现，而不是只在摘要或引言里宣称；有没有说清与最近工作的差别。',
  },
  {
    key: 'integrity',
    label: '学术诚信',
    hint: '引用真实可核、数据可追、声明完整',
    watch: '抽查引用能否定位原文；数据/代码可用性、作者贡献、利益冲突、伦理审批是否齐全。0 分一票否决。',
  },
  {
    key: 'presentation',
    label: '表达与结构',
    hint: '结构、图表与语言是否让读者读得下去',
    watch: '按顺序读一遍：每一节是否回答上一节留下的问题；图表是否自解释；语言是否需要反复重读。',
  },
]

const SCORE_ANCHORS: { min: number; text: string }[] = [
  { min: 90, text: '范本级：核心环节完整，可作为同类稿件范本。' },
  { min: 80, text: '优秀：结构完整，只有少量需要打磨。' },
  { min: 70, text: '良好：达到本刊要求，仍有可见改进空间。' },
  { min: 60, text: '合格：能站住，但证据或论证有明确短板。' },
  { min: 50, text: '边缘：可以补救，必须实质修改后再看。' },
  { min: 40, text: '及格线附近：核心环节有明显缺口。' },
  { min: 0, text: '不合格：核心环节缺失，需要重做或换问题。' },
]

function scoreAnchor(score: number): string {
  return SCORE_ANCHORS.find((band) => score >= band.min)?.text ?? SCORE_ANCHORS[SCORE_ANCHORS.length - 1].text
}

export const EMPTY_REVIEW_FORM: ReviewFormValue = {
  recommendation: 'minor_revision',
  scores: {
    problem: 70,
    argument: 70,
    method: 70,
    evidence: 70,
    novelty: 70,
    integrity: 100,
    presentation: 70,
  },
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

function reviewFieldLabel(key: string): string {
  return SCORE_DIMENSIONS.find((d) => d.key === key)?.label ?? key
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
  const average = useMemo(() => {
    const nums = SCORE_DIMENSIONS.map((d) => value.scores[d.key] ?? 70)
    return (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1)
  }, [value.scores])
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
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Label>评分（百分制 0–100）· 七个学术价值维度</Label>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            当前均分 {average} / 100
          </span>
        </div>
        <p className="text-[11px] leading-5 text-muted-foreground">
          评分不是印象分：每个维度按「看什么」逐项检查，再给 0–100 的整数。后端按权重合成总分（research / review / essay / note 四套权重）。
          学术诚信 0 分一票否决；发现引用造假或数据不可追，请给 0 分并在给编辑的意见里写清。
        </p>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {SCORE_DIMENSIONS.map((dim) => {
            const score = value.scores[dim.key] ?? 70
            const setScore = (n: number) =>
              onChange({
                ...value,
                scores: { ...value.scores, [dim.key]: Math.max(0, Math.min(100, Math.round(n))) },
              })
            return (
              <div key={dim.key} className="rounded-lg border bg-card p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium">{dim.label}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{dim.hint}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={score}
                      disabled={disabled}
                      onChange={(e) => setScore(Number(e.target.value))}
                      aria-label={`${dim.label}分数（0–100）`}
                      className="h-8 w-16 px-2 text-center text-xs tabular-nums"
                    />
                    <span className="text-[10px] text-muted-foreground">分</span>
                  </div>
                </div>
                <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">{dim.watch}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {[50, 60, 70, 80, 90, 100].map((n) => (
                    <Button
                      key={n}
                      type="button"
                      size="sm"
                      variant={score === n ? 'default' : 'outline'}
                      className="h-7 px-2 text-xs tabular-nums"
                      onClick={() => setScore(n)}
                      disabled={disabled}
                    >
                      {n}
                    </Button>
                  ))}
                </div>
                <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">
                  {scoreAnchor(score)}
                </p>
              </div>
            )
          })}
        </div>
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
              <span className="text-xs text-muted-foreground">平均分 {average} / 100</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {SCORE_DIMENSIONS.map((d) => (
                <div key={d.key} className="rounded border px-2 py-1.5 text-xs">
                  <span className="text-muted-foreground">{d.label}</span>
                  <span className="ml-1 font-medium tabular-nums">{value.scores[d.key] ?? 70}</span>
                </div>
              ))}
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

export function reviewFormAverage(scores: Record<string, number>): string {
  const nums = SCORE_DIMENSIONS.map((d) => scores[d.key] ?? 70)
  return (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1)
}

export function reviewScoreLabel(key: string): string {
  return reviewFieldLabel(key)
}
