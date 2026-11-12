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

// 赛道标签已随赛道下线移除（后端 core/tracks.py）：不再按正经/玩梗分组展示。

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
// 质量评分（评审质量分）：等级徽章的展示映射。数值口径见 /api/quality/rubric。
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
  // RQS v5.0 分区口径（与 /api/quality/rubric 一致）。学术与荒诞共用
  // 同一套分段，但锚点措辞不同；等级只在评审区出现，不进内容分层。
  'T1+': { label: 'T1+ 顶刊范本', description: '95–100，同领域写作范本，极少授予', className: 'bg-amber-300 text-amber-950 border-amber-400/70' },
  'T1': { label: 'T1 顶刊级', description: '90–94，达到顶刊同领域已发表水准', className: 'bg-amber-200/80 text-amber-950 border-amber-300/60' },
  'Q1': { label: 'Q1 一区', description: '80–89，五个判断面都站得住', className: 'bg-primary/15 text-primary border-primary/30' },
  'Q2': { label: 'Q2 二区', description: '70–79，有一处实质短板，修回后可成立', className: 'bg-primary/10 text-primary border-primary/20' },
  'Q3': { label: 'Q3 三区', description: '60–69，能自圆其说，但方法或证据链有明显缺口', className: 'bg-muted text-foreground border-border' },
  'Q4': { label: 'Q4 四区', description: '50–59，核心环节勉强成立，结论可靠性存疑', className: 'bg-muted text-muted-foreground border-border' },
  'R': { label: 'R 退稿', description: '0–49，未达发表门槛，不入区', className: 'bg-destructive/10 text-destructive border-destructive/30' },
}

const LEGACY_GRADE_MAP: Record<string, string> = {
  'A+': 'T1+', A: 'T1', 'A-': 'T1',
  'B+': 'Q1', B: 'Q1', 'B-': 'Q1',
  'C+': 'Q2', C: 'Q2', 'C-': 'Q2',
  'D+': 'Q3', D: 'Q3', 'D-': 'Q3',
  'E+': 'Q4', E: 'Q4', 'E-': 'Q4',
  F: 'R',
}

function bandForScore(score: number): string {
  if (score >= 95) return 'T1+'
  if (score >= 90) return 'T1'
  if (score >= 80) return 'Q1'
  if (score >= 70) return 'Q2'
  if (score >= 60) return 'Q3'
  if (score >= 50) return 'Q4'
  return 'R'
}

const GRADE_FALLBACK: QualityGrade = {
  label: '—',
  description: '未评级',
  className: 'bg-muted text-muted-foreground border-border',
}

export function qualityGrade(
  grade: string | null | undefined,
  score?: number | null,
): QualityGrade | null {
  if (score != null && Number.isFinite(score)) {
    const byScore = QUALITY_GRADES[bandForScore(score)]
    if (byScore) return byScore
  }
  if (!grade) return null
  const normalized = LEGACY_GRADE_MAP[grade] ?? grade
  const known = QUALITY_GRADES[normalized]
  if (known) return known
  return { ...GRADE_FALLBACK, label: grade, description: `评级 ${grade}` }
}

// ---------------------------------------------------------------------------
// 内容类别（v1.11）：academic / fun / rant——类别不是等级，是编辑部
// 评定的一等公民属性；目录筛选、排行分域都按类别走。
// ---------------------------------------------------------------------------
const CATEGORY_LABELS: Record<string, string> = {
  academic: '学术研究',
  fun: '副刊',
  rant: '吐槽',
}

export function contentCategoryLabel(category: string | null | undefined): string {
  return (category && CATEGORY_LABELS[category]) || ''
}

// ---------------------------------------------------------------------------
// 学术 vs 娱乐：content_category 为 fun/rant，或后端给出 content_track=essay
// 时，这篇是娱乐稿——全站不渲染任何学术评分元素（R 因子/分区、
// RQS、quality_grade）。阅读量/收藏/评论等内容侧数据照常保留。
// ---------------------------------------------------------------------------
export function isScholarlyContent(
  contentCategory: string | null | undefined,
  contentTrack?: string | null,
): boolean {
  // 轨道优先：content_track 是唯一权威口径（历史稿件 category 可能未同步）。
  if (contentTrack === 'paper') return true
  if (contentTrack === 'essay') return false
  if (contentCategory === 'fun' || contentCategory === 'rant') return false
  return true
}

// 类型 chip：学术稿按资源类型显示（论文/图书/…）；娱乐稿直接显示赛道名，
// 不再把娱乐稿标成"论文"。
export function displayTypeLabel(
  type: string | null | undefined,
  contentCategory?: string | null,
  contentTrack?: string | null,
  paperKind?: string | null,
): string {
  if (contentTrack === 'essay') return contentCategory === 'rant' ? '吐槽' : '副刊'
  if (contentTrack === 'paper') {
    if (paperKind === 'absurd') return '荒诞论文'
    if (paperKind === 'serious') return '学术论文'
    return TYPE_LABELS[type ?? ''] ?? '论文'
  }
  if (contentCategory === 'fun') return '副刊'
  if (contentCategory === 'rant') return '吐槽'
  return typeLabel(type)
}

// ---------------------------------------------------------------------------
// 四轨呈现（v3 规范表）：决定详情页渲染哪些块。
// - paper    学术论文：摘要/关键词/CLC/参考文献/四项声明/评分/DOI 全有
// - sci_pop  科普：导语 + 正文 + 延伸阅读；无摘要/关键词/CLC/评分/DOI
// - fun      娱乐：正文 + 标签 + 可选参考资料；无学术块
// - rant     吐槽：正文 + 标签；无学术块
// - plain    未知：只渲染正文，不渲染任何学术块（兜底）
//
// 判定以 content_category 为准（后续会批量改分类）；content_track 仅作
// essay 兜底。后续新增科普类值（science/science_pop/popular/科普）在此加。
// ---------------------------------------------------------------------------
export type ContentKind = 'paper' | 'sci_pop' | 'fun' | 'rant' | 'plain'

export function contentTrackKind(
  contentCategory: string | null | undefined,
  contentTrack?: string | null,
): ContentKind {
  const cat = (contentCategory ?? '').toLowerCase()
  if (cat === 'fun') return 'fun'
  if (cat === 'rant') return 'rant'
  if (cat === 'science' || cat === 'science_pop' || cat === 'popular' || cat === 'scipop' || cat === '科普') {
    return 'sci_pop'
  }
  if (cat === 'academic' || cat === 'paper') return 'paper'
  // content_track=essay 但 category 不是 fun/rant：归 plain（只渲染正文）
  if (contentTrack === 'essay') return 'plain'
  // 缺省：保守按 paper 处理（本刊默认是学术刊）
  return 'paper'
}
