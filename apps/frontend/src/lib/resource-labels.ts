// 展示层的中英映射：后端存的是 ISO/内部枚举，界面不该把 `en`、`paper`
// 这类机器值直接丢给读者。

const LANGUAGE_LABELS: Record<string, string> = {
  zh: '中文',
  'zh-cn': '中文',
  'zh-hans': '中文',
  en: '英文',
  'en-us': '英文',
  'en-gb': '英文',
  ja: '日文',
  ko: '韩文',
  de: '德文',
  fr: '法文',
  ru: '俄文',
  es: '西班牙文',
}

export function languageLabel(code: string | null | undefined): string {
  if (!code) return '—'
  return LANGUAGE_LABELS[code.toLowerCase()] ?? code
}

const TYPE_LABELS: Record<string, string> = {
  paper: '论文',
  book: '图书',
  dataset: '数据集',
  tutorial: '教程',
}

export function typeLabel(type: string | null | undefined): string {
  if (!type) return '—'
  return TYPE_LABELS[type] ?? type
}

// 赛道标签已随赛道下线移除（后端 core/tracks.py）：文章气质由下面的
// 荒诞指数（absurdityLevel）表达，不再按正经/荒诞分组展示。

const STATUS_LABELS: Record<string, string> = {
  published: '已发表',
  in_review: '评审中',
  draft: '草稿',
}

export function statusLabel(status: string | null | undefined): string {
  if (!status) return '—'
  return STATUS_LABELS[status] ?? status
}

/**
 * 把推荐引擎的 reason 翻成读者能看懂的一句话。
 *
 * 引擎输出的是 `matches 2 tags: ['x']` / `discipline 'y'` /
 * `no reading history; showing latest` 这类内部诊断串，直接展示等于把
 * 开发日志漏到界面上。
 */
export function recommendationReason(reason: string | null | undefined): string {
  if (!reason) return '为你推荐'
  if (reason.includes('no reading history')) return '最新收录'
  if (reason.includes('you have read everything')) return '你已读完现有全部文章'
  const tags = reason.match(/matches (\d+) tags?: \[(.*)\]/)
  if (tags) {
    const names = tags[2]
      .split(',')
      .map((t) => t.trim().replace(/^['"]|['"]$/g, ''))
      .filter(Boolean)
    return names.length > 0 ? `匹配标签：${names.join('、')}` : `匹配 ${tags[1]} 个标签`
  }
  const discipline = reason.match(/discipline '([^']+)'/)
  if (discipline) return `学科匹配：${discipline[1]}`
  const subdiscipline = reason.match(/subdiscipline '([^']+)'/)
  if (subdiscipline) return `子学科匹配：${subdiscipline[1]}`
  if (reason.includes('no direct match')) return '相关领域新作'
  return reason
}

// ---------------------------------------------------------------------------
// 荒诞指数（编辑部评定，0–10）：界面只呈现等级与数值，不呈现评定口径。
// ---------------------------------------------------------------------------

export interface AbsurdityLevel {
  label: string
  description: string
  variant: 'default' | 'secondary' | 'destructive' | 'outline'
}

export function absurdityLevel(index: number | null | undefined): AbsurdityLevel | null {
  if (index == null) return null
  if (index < 2.5)
    return { label: '正经', description: '严肃研究', variant: 'outline' }
  if (index < 5)
    return { label: '轻诞', description: '略带荒诞色彩', variant: 'secondary' }
  if (index < 7.5)
    return { label: '荒诞', description: '明显的荒诞研究', variant: 'default' }
  return { label: '离谱', description: '编辑部认证的离谱研究', variant: 'destructive' }
}

export function absurdityLabel(index: number | null | undefined): string {
  return absurdityLevel(index)?.label ?? '—'
}

// ---------------------------------------------------------------------------
// 质量评分（RQS v3.0）：等级徽章的展示映射。数值口径见 /api/quality/rubric。
// v3.0 是 14 档带加减号的严厉客观制：A+（95–100）是典范水准、刻意极少
// 达到，多数稿子落在 C/D；F（40–54）= 合格、仍可发表；只有总分 <40 才
// 不合格（不予发表）。
// ---------------------------------------------------------------------------

export interface QualityGrade {
  label: string
  description: string
  className: string
}

const QUALITY_GRADES: Record<string, QualityGrade> = {
  'A+': {
    label: 'A+ 极佳',
    description: '典范水准（95–100），编辑部范例级，极少达到',
    className: 'bg-amber-300 text-amber-950 border-amber-400/70',
  },
  A: {
    label: 'A 极佳',
    description: '极佳水准（90–94），可直接发表',
    className: 'bg-amber-200/80 text-amber-950 border-amber-300/60',
  },
  'A-': {
    label: 'A- 优秀',
    description: '优秀（85–89），小修即可',
    className: 'bg-amber-100 text-amber-900 border-amber-200',
  },
  'B+': {
    label: 'B+ 良好',
    description: '良好（82–84），有发表价值',
    className: 'bg-primary/15 text-primary border-primary/30',
  },
  B: {
    label: 'B 良好',
    description: '良好（78–81），个别维度有可修正的缺口',
    className: 'bg-primary/10 text-primary border-primary/20',
  },
  'B-': {
    label: 'B- 良好',
    description: '良好偏弱（75–77），建议小修',
    className: 'bg-primary/10 text-primary border-primary/20',
  },
  'C+': {
    label: 'C+ 中等',
    description: '中等（72–74），内容成立但需编辑加工',
    className: 'bg-muted text-foreground border-border',
  },
  C: {
    label: 'C 中等',
    description: '中等（68–71），引用或表达需要编辑加工',
    className: 'bg-muted text-foreground border-border',
  },
  'C-': {
    label: 'C- 中等',
    description: '中等偏弱（65–67），多处需修订',
    className: 'bg-muted text-foreground border-border',
  },
  'D+': {
    label: 'D+ 较弱',
    description: '较弱（62–64），结构或论证有明显缺口',
    className: 'bg-muted text-muted-foreground border-border',
  },
  D: {
    label: 'D 较弱',
    description: '较弱（58–61），仍可发表但需较大修改',
    className: 'bg-muted text-muted-foreground border-border',
  },
  'D-': {
    label: 'D- 较弱（边缘）',
    description: '边缘稿（55–57）：可发表，编辑部处理时请谨慎',
    className: 'bg-muted text-muted-foreground border-border',
  },
  F: {
    label: 'F 合格',
    description: '合格（40–54）：可以阅读，仍可发表',
    className: 'bg-muted text-foreground border-border',
  },
}

// 兜底：未知/历史档位（含 <40 的"不合格"记录，字母仍记为 F）不崩徽章——
// 显示原始代号 + 中性样式，绝不让 switch/字典缺键变成空白或报错。
const GRADE_FALLBACK: QualityGrade = {
  label: '',
  description: '',
  className: 'bg-muted text-foreground border-border',
}

export function qualityGrade(grade: string | null | undefined): QualityGrade | null {
  if (!grade) return null
  const known = QUALITY_GRADES[grade]
  if (known) return known
  return { ...GRADE_FALLBACK, label: grade, description: `评级 ${grade}` }
}
