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
// 风格光谱（荒诞指数 0–10）：这是「类别光谱」不是等级——用于告诉读者
// 这篇内容的风格位置（学术/娱乐/吐槽），同一光谱内才参与同类比对。
// ---------------------------------------------------------------------------

export interface AbsurdityLevel {
  label: string
  description: string
  variant: 'default' | 'secondary' | 'destructive' | 'outline'
}

export function absurdityLevel(index: number | null | undefined): AbsurdityLevel | null {
  if (index == null) return null
  if (index < 2.5)
    return { label: '学术', description: '严肃研究', variant: 'outline' }
  if (index < 5)
    return { label: '轻娱乐', description: '略带娱乐色彩的研究', variant: 'secondary' }
  if (index < 7.5)
    return { label: '娱乐', description: '娱乐向研究', variant: 'default' }
  return { label: '吐槽', description: '吐槽向内容', variant: 'destructive' }
}

export function absurdityLabel(index: number | null | undefined): string {
  return absurdityLevel(index)?.label ?? '—'
}

// ---------------------------------------------------------------------------
// 质量评分（RQS v4.0）：等级徽章的展示映射。数值口径见 /api/quality/rubric。
// v4.0 是 16 档 ABCDEF 全字母制：A+（97–100）对标顶刊、刻意稀缺；
// F（40–49）= 及格可发表；<40 = 不合格（打回）。等级仅作为评审信息
// 呈现，不构成内容的公开分层。
// ---------------------------------------------------------------------------

export interface QualityGrade {
  label: string
  description: string
  className: string
}

const QUALITY_GRADES: Record<string, QualityGrade> = {
  // RQS v4.0 十六档口径（与 /api/quality/rubric 一致）。等级属于评审
  // 信息元数据，不属于内容分层：界面只在评审区呈现，不进列表排序。
  'A+': { label: 'A+ 典范', description: '97–100，领域范本，编辑部极少量授予', className: 'bg-amber-300 text-amber-950 border-amber-400/70' },
  'A': { label: 'A 顶尖', description: '93–96，可直接发表', className: 'bg-amber-200/80 text-amber-950 border-amber-300/60' },
  'A-': { label: 'A- 优秀', description: '90–92，小修即可', className: 'bg-amber-100 text-amber-900 border-amber-200' },
  'B+': { label: 'B+ 良好', description: '87–89，有发表价值', className: 'bg-primary/15 text-primary border-primary/30' },
  'B': { label: 'B 良好', description: '83–86，个别维度有可修正缺口', className: 'bg-primary/10 text-primary border-primary/20' },
  'B-': { label: 'B- 良好', description: '80–82，建议小修', className: 'bg-primary/10 text-primary border-primary/20' },
  'C+': { label: 'C+ 中等', description: '77–79，内容成立但需编辑加工', className: 'bg-muted text-foreground border-border' },
  'C': { label: 'C 中等', description: '73–76，引用或表达需编辑加工', className: 'bg-muted text-foreground border-border' },
  'C-': { label: 'C- 中等', description: '70–72，多处需修订', className: 'bg-muted text-foreground border-border' },
  'D+': { label: 'D+ 达标', description: '67–69，达标线以上，明显修订', className: 'bg-muted text-foreground border-border' },
  'D': { label: 'D 达标', description: '63–66，达标线以上，需大幅修订', className: 'bg-muted text-foreground border-border' },
  'D-': { label: 'D- 达标', description: '60–62，borderline，可发表但需逐条修回', className: 'bg-muted text-foreground border-border' },
  'E+': { label: 'E+ 基础', description: '57–59，基础层级，建议撤回重组', className: 'bg-muted text-muted-foreground border-border' },
  'E': { label: 'E 基础', description: '53–56，基础层级', className: 'bg-muted text-muted-foreground border-border' },
  'E-': { label: 'E- 基础', description: '50–52，borderline 基础', className: 'bg-muted text-muted-foreground border-border' },
  'F': { label: 'F 及格', description: '40–49，及格可发表，按意见修订', className: 'bg-muted text-muted-foreground border-border' },
}

const GRADE_FALLBACK: QualityGrade = {
  label: '—',
  description: '未评级',
  className: 'bg-muted text-muted-foreground border-border',
}

export function qualityGrade(grade: string | null | undefined): QualityGrade | null {
  if (!grade) return null
  const known = QUALITY_GRADES[grade]
  if (known) return known
  return { ...GRADE_FALLBACK, label: grade, description: `评级 ${grade}` }
}

// ---------------------------------------------------------------------------
// 内容类别（v1.11）：academic / fun / rant——类别不是等级，是编辑部
// 评定的一等公民属性；目录筛选、排行分域都按类别走。
// ---------------------------------------------------------------------------
const CATEGORY_LABELS: Record<string, string> = {
  academic: '学术研究',
  fun: '娱乐向',
  rant: '吐槽向',
}

export function contentCategoryLabel(category: string | null | undefined): string {
  return (category && CATEGORY_LABELS[category]) || ''
}

