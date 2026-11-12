import { useMemo } from 'react'
import { AlertTriangle, CheckCircle2, FileSearch, Info } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export type ReviewTrack = 'academic' | 'absurd'

export interface DimensionReview {
  score: number | null
  reason: string
  evidence: string
}

export type DimensionReviews = Record<string, DimensionReview>

interface DimensionMeta {
  key: string
  label: string
  hint: string
  weight: number
  watch: string
}

export const ACADEMIC_REVIEW_DIMENSIONS: DimensionMeta[] = [
  {
    key: 'question',
    label: '选题与真问题',
    hint: '问题真实、具体、未被回答；创新增量说得清',
    weight: 20,
    watch: '它回答的是不是一个能被证伪的问题？增量相对哪一篇、补了哪一块？找不到对标文献，这一维最多 60。',
  },
  {
    key: 'argument',
    label: '论证与自洽',
    hint: '前提→结论无跳跃、无循环；反面解释被处理',
    weight: 25,
    watch: '逐节问：这个结论的前提在哪？有没有从 A 跳到 C？有没有处理相反解释？论证断链时总分直接封顶 59。',
  },
  {
    key: 'method',
    label: '方法与可复现',
    hint: '数据、样本、参数、失败案例交代到别人能照着做',
    weight: 20,
    watch: '换一个人拿这份方法，能不能复现？数据来源、样本量、筛选标准、关键参数、失败案例，缺一项就写进证据里。',
  },
  {
    key: 'evidence',
    label: '证据与结论',
    hint: '证据强度匹配结论强度；相关不被写成因果',
    weight: 20,
    watch: '样本 3 例却下普适结论、相关性写成因果、没有不确定性，都只能给弱证据分。',
  },
  {
    key: 'integrity',
    label: '规范与诚信',
    hint: '引用可核、数据可追、声明完整（0 分一票否决）',
    weight: 15,
    watch: '抽查 2–3 条引用能否定位原文；数据/代码声明是否可执行；作者贡献与利益冲突是否齐全。发现造假给 0。',
  },
]

export const ABSURD_REVIEW_DIMENSIONS: DimensionMeta[] = [
  {
    key: 'concept',
    label: '荒诞设定与原创',
    hint: '设定真荒诞、新鲜、有记忆点，不是普通吐槽换皮',
    weight: 25,
    watch: '把核心设定用一句话讲给没看过的人听；他会不会想继续听？只是“离谱”但没有新规则，这一维不高。',
  },
  {
    key: 'coherence',
    label: '内部自洽',
    hint: '设定内规则自洽，前后不打架',
    weight: 20,
    watch: '允许无中生有，但不允许人物、时间、数字、规则互相打架。自洽低于 50，总分封顶 59。',
  },
  {
    key: 'execution',
    label: '一本正经的执行',
    hint: '用完整结构把荒诞当正事推进，不是段子拼贴',
    weight: 20,
    watch: '摘要/方法/结果或叙事推进是否完整？作者有没有自己跳出来解释“这很好笑”？执行低于 50，总分封顶 69。',
  },
  {
    key: 'material',
    label: '材料与梗的可核查',
    hint: '梗、案例、数据有出处，或自造规则被明确交代',
    weight: 20,
    watch: '引用的台词、论文、事件能不能核到？自造数据有没有标注“自造”？张冠李戴直接扣到底。',
  },
  {
    key: 'voice',
    label: '文风与节奏',
    hint: '有节奏、有包袱、不啰嗦，荒诞感靠写法立住',
    weight: 15,
    watch: '读出声来，哪里会笑、哪里会拖？靠括号解释笑点、靠重复词凑字数，都写进证据。',
  },
]

export const TRACK_DIMENSIONS: Record<ReviewTrack, DimensionMeta[]> = {
  academic: ACADEMIC_REVIEW_DIMENSIONS,
  absurd: ABSURD_REVIEW_DIMENSIONS,
}

export const TRACK_LABELS: Record<ReviewTrack, string> = {
  academic: '学术赛道',
  absurd: '荒诞赛道',
}

const ANCHORS: Record<ReviewTrack, { min: number; text: string }[]> = {
  academic: [
    { min: 95, text: '顶刊范本：可直接作为同领域写作范例，几乎没有需要实质修改的地方。' },
    { min: 90, text: '顶刊门槛：完成度与判断力达到顶刊同领域论文水准，只剩编辑性问题。' },
    { min: 80, text: '一区：五个判断面都站得住，有清晰增量，短板只在局部。' },
    { min: 70, text: '二区：问题与论证成立，方法或证据有一处实质不足，修回后可成立。' },
    { min: 60, text: '三区：能自圆其说，但方法透明度或证据链有明显缺口，需大修。' },
    { min: 50, text: '四区：核心环节勉强成立，结论可靠性存疑，只能作边缘稿。' },
    { min: 0, text: '退稿：该维度缺失、方法性错误，或存在学术不端。' },
  ],
  absurd: [
    { min: 95, text: '荒诞范本：设定、执行、文风合一，读完想转给别人。' },
    { min: 90, text: '顶刊级荒诞：设定极新，规则严丝合缝，一本正经到忘记它在胡说。' },
    { min: 80, text: '一区：荒诞点清楚，结构完整，梗有出处或规则自洽。' },
    { min: 70, text: '二区：设定成立，执行基本完整，但局部靠硬凑梗。' },
    { min: 60, text: '三区：有荒诞点，但内部规则开始打架，或后半程写不下去。' },
    { min: 50, text: '四区：只有零散段子，缺少完整设定与推进。' },
    { min: 0, text: '退稿：设定平庸或前后矛盾，通篇堆梗。' },
  ],
}

export function anchorFor(track: ReviewTrack, score: number | null): string {
  if (score === null) return '尚未给分'
  return ANCHORS[track].find((a) => score >= a.min)?.text ?? ANCHORS[track][ANCHORS[track].length - 1].text
}

export function emptyDimensionReviews(track: ReviewTrack): DimensionReviews {
  return Object.fromEntries(
    TRACK_DIMENSIONS[track].map((d) => [d.key, { score: null, reason: '', evidence: '' }]),
  )
}

export function dimensionIssue(_dim: DimensionMeta, value: DimensionReview | undefined): string | null {
  if (!value || value.score === null) return '未给分'
  const score = value.score
  // 与服务端同一条门槛：90+ 顶刊级要 40 字理由 + 60 字可定位证据，
  // 80+ 一区要 15/20 字，其余至少 4/10 字。前端先拦，避免提交后 422。
  const [reasonMin, evidenceMin] = score >= 90 ? [40, 60] : score >= 80 ? [15, 20] : [4, 10]
  const reason = value.reason.trim()
  const evidence = value.evidence.trim()
  if (reason.length < reasonMin) return `理由至少 ${reasonMin} 字（当前 ${reason.length}）`
  if (evidence.length < evidenceMin) return `正文证据至少 ${evidenceMin} 字（当前 ${evidence.length}）`
  if (!['第', '§', '图', '表', '页', '段', '节', '引用', '文献', '附录', 'http'].some((t) => evidence.includes(t))) {
    return '证据要定位到正文（§/段/图/表/引用编号）'
  }
  return null
}

export function scoreReviewTotal(track: ReviewTrack, reviews: DimensionReviews): {
  total: number
  uncapped: number
  cap: number | null
  capNotes: string[]
  grade: string
  gradeLabel: string
  complete: boolean
  incomplete: string[]
} {
  const dims = TRACK_DIMENSIONS[track]
  let uncapped = 0
  for (const d of dims) {
    const score = reviews[d.key]?.score ?? 0
    uncapped += (d.weight * score) / 100
  }
  uncapped = Math.round(uncapped * 10) / 10
  const caps: number[] = []
  let capNotes: string[] = []
  const entries = dims.map((d) => ({ key: d.key, score: reviews[d.key]?.score ?? 0 }))
  if (track === 'academic' && reviews.integrity?.score === 0) {
    caps.push(0)
    capNotes.push('诚信维度 0 分：总分归零')
  }
  const low = entries.filter((e) => e.score < 50)
  if (low.length >= 2) {
    caps.push(49)
    capNotes.push('两项及以上维度低于 50 分：总分封顶 49（退稿）')
  } else if (low.length === 1) {
    caps.push(59)
    capNotes.push('有维度低于 50 分：总分封顶 59（不进三区及以上）')
  }
  const mid = entries.filter((e) => e.score >= 50 && e.score < 60)
  if (mid.length && !low.length) {
    caps.push(79)
    capNotes.push('有维度低于 60 分：总分封顶 79（不进一区/顶刊）')
  }
  if (track === 'academic' && (reviews.argument?.score ?? 0) < 50) {
    caps.push(59)
    capNotes.push('论证低于 50 分：总分封顶 59')
  }
  if (track === 'absurd' && (reviews.coherence?.score ?? 0) < 50) {
    caps.push(59)
    capNotes.push('自洽低于 50 分：总分封顶 59')
  }
  if (track === 'absurd' && (reviews.execution?.score ?? 0) < 50) {
    caps.push(69)
    capNotes.push('执行低于 50 分：总分封顶 69')
  }
  const cap = caps.length ? Math.min(...caps) : null
  const ratedTotal = cap !== null && uncapped > cap ? cap : uncapped
  const incomplete = entries.filter((e) => e.score < 50).map((e) => e.key)
  const complete = incomplete.length === 0
  // 不完整稿不评级，也不封顶诊断分：封顶只对完整稿的等级有意义。
  if (!complete) {
    capNotes = track === 'academic' && reviews.integrity?.score === 0
      ? ['诚信维度 0 分：总分归零，不进入编辑部补全']
      : ['任一维低于 50 分：暂不评级；编辑部按原思路补全后直接评级，不打回作者']
  }
  const total = complete ? ratedTotal : uncapped
  const grade = complete
    ? total >= 95 ? 'T1+' : total >= 90 ? 'T1' : total >= 80 ? 'Q1' : total >= 70 ? 'Q2' : total >= 60 ? 'Q3' : total >= 50 ? 'Q4' : 'R'
    : 'NA'
  const gradeLabel = complete
    ? grade === 'T1+' ? '顶刊范本' : grade === 'T1' ? '顶刊级' : grade === 'Q1' ? '一区' : grade === 'Q2' ? '二区' : grade === 'Q3' ? '三区' : grade === 'Q4' ? '四区' : '退稿'
    : '待编辑部补全，暂不评级'
  return { total, uncapped, cap, capNotes, grade, gradeLabel, complete, incomplete }
}

export function RubricScoreFields({
  track,
  reviews,
  onChange,
  disabled,
}: {
  track: ReviewTrack
  reviews: DimensionReviews
  onChange: (next: DimensionReviews) => void
  disabled?: boolean
}) {
  const dims = TRACK_DIMENSIONS[track]
  const summary = useMemo(() => scoreReviewTotal(track, reviews), [track, reviews])
  const completed = dims.filter((d) => !dimensionIssue(d, reviews[d.key])).length

  const update = (key: string, patch: Partial<DimensionReview>) => {
    const base = reviews[key] ?? { score: null, reason: '', evidence: '' }
    onChange({ ...reviews, [key]: { ...base, ...patch } })
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>评分（百分制 0–100）· 五维逐项审批</Label>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {completed}/{dims.length} 维完整
        </span>
      </div>
      <p className="text-[11px] leading-5 text-muted-foreground">
        每个维度必须同时有 <strong>分数 + 理由 + 正文证据</strong>。证据写到章节/段落/图号/表号/引用编号，只写“整体不错”不算。
        90 分以上按顶刊级取证：理由至少 40 字、证据至少 60 字；80 分以上也要能定位到正文。三项任一缺失，服务端会拒绝整份报告。
      </p>

      {dims.map((dim) => {
        const value = reviews[dim.key] ?? { score: null, reason: '', evidence: '' }
        const issue = dimensionIssue(dim, value)
        return (
          <div key={dim.key} className={cn('rounded-lg border bg-card p-3', issue && 'border-dashed')}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  {dim.label}
                  <Badge variant="outline" className="text-[9px] tabular-nums">
                    权重 {dim.weight}%
                  </Badge>
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{dim.hint}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={value.score ?? ''}
                  placeholder="—"
                  disabled={disabled}
                  onChange={(e) => {
                    const raw = e.target.value
                    update(dim.key, { score: raw === '' ? null : Math.max(0, Math.min(100, Math.round(Number(raw)))) })
                  }}
                  aria-label={`${dim.label}分数（0–100）`}
                  className="h-9 w-20 px-2 text-center text-sm tabular-nums"
                />
                <span className="text-[10px] text-muted-foreground">分</span>
              </div>
            </div>
            <p className="mt-1.5 rounded bg-muted/40 px-2 py-1.5 text-[11px] leading-5 text-muted-foreground">
              {anchorFor(track, value.score)}
            </p>
            <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground">{dim.watch}</p>
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              <div className="space-y-1">
                <p className="flex items-center gap-1 text-[11px] font-medium">
                  <FileSearch className="h-3.5 w-3.5" /> 为什么给这个分
                </p>
                <Textarea
                  value={value.reason}
                  disabled={disabled}
                  onChange={(e) => update(dim.key, { reason: e.target.value })}
                  placeholder="例：问题成立，但增量只对比了 1 篇 2019 年的旧文，没覆盖 2023 年后的同类工作。"
                  rows={3}
                  className="text-xs"
                  aria-label={`${dim.label}评分理由`}
                />
              </div>
              <div className="space-y-1">
                <p className="flex items-center gap-1 text-[11px] font-medium">
                  <FileSearch className="h-3.5 w-3.5" /> 正文证据（必填）
                </p>
                <Textarea
                  value={value.evidence}
                  disabled={disabled}
                  onChange={(e) => update(dim.key, { evidence: e.target.value })}
                  placeholder="例：§1 第 3 段“已有研究仅覆盖……”；参考文献[7] 2019；§4 表 2 仅 3 个样本。"
                  rows={3}
                  className="text-xs"
                  aria-label={`${dim.label}正文证据`}
                />
              </div>
            </div>
            <div className="mt-1.5 flex items-center justify-between text-[10px]">
              <span className={cn('text-muted-foreground', issue && 'text-amber-700 dark:text-amber-300')}>
                {issue ? `待补：${issue}` : '本维度已可提交'}
              </span>
              <span className="text-muted-foreground tabular-nums">
                理由 {value.reason.trim().length} 字 · 证据 {value.evidence.trim().length} 字
              </span>
            </div>
          </div>
        )
      })}

      <div className="rounded-lg border border-primary/25 bg-primary/[0.06] p-3 dark:border-primary/25 dark:bg-primary/10">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-medium">
            {summary.grade === 'R' || summary.grade === 'NA' ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            {summary.complete ? `当前合计 ${summary.total} 分 · ${summary.grade} ${summary.gradeLabel}` : `当前诊断 ${summary.uncapped} 分 · ${summary.gradeLabel}；补全后直接评级，不打回作者`}
          </p>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            未封顶 {summary.uncapped} · {completed}/{dims.length} 维
          </span>
        </div>
        {summary.cap !== null && (
          <div className="mt-1.5 space-y-0.5 text-[11px] leading-5 text-amber-800 dark:text-amber-200">
            {summary.capNotes.map((n) => (
              <p key={n}>· {n}</p>
            ))}
          </div>
        )}
        <p className="mt-1.5 flex items-start gap-1.5 text-[10px] leading-4 text-muted-foreground">
          <Info className="mt-0.5 h-3 w-3 shrink-0" />
          90+ 顶刊级，80/70/60/50 分别为一/二/三/四区。完整稿才评级；任一维低于 50 进编辑部补全，暂不评级，补全后按实际内容重评。
        </p>
      </div>
    </div>
  )
}

export function reviewAverage(track: ReviewTrack, reviews: DimensionReviews): string {
  const dims = TRACK_DIMENSIONS[track]
  const scored = dims.filter((d) => reviews[d.key]?.score !== null && reviews[d.key]?.score !== undefined)
  if (!scored.length) return '—'
  const sum = scored.reduce((n, d) => n + (reviews[d.key]?.score ?? 0), 0)
  return (sum / scored.length).toFixed(1)
}

export function dimensionLabel(track: ReviewTrack, key: string): string {
  return TRACK_DIMENSIONS[track].find((d) => d.key === key)?.label ?? key
}
