import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createFileRoute,
  redirect,
 useNavigate,
  useRouterState,
  useSearch,
} from '@tanstack/react-router'
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Save,
  Upload,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import { HelpTip } from '@/components/common/help-tip'
import { useCapabilities } from '@/hooks/use-capabilities'
import {
  useCreateSubmission,
  useSaveSubmissionMarkdown,
  useSubmission,
  useSubmissionMarkdown,
  useUpdateSubmission,
  useUploadSubmissionFile,
  useConvertSubmissionPreview,
  previewUploadedSourcePages,
} from '@/hooks/api/use-modules'
import { MarkdownEditor } from '@/components/common/markdown-editor'
import { ArticlePreview } from '@/components/common/article-preview'
import SourcePreviewPng from '@/components/source-preview-png'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type {
  IngestResource,
  SubmissionCreate,
  SubmissionResponse,
  SubmissionType,
} from '@/lib/types'
import { DISCIPLINES } from '@/lib/disciplines'
import { ARTICLE_SECTION_OPTIONS } from '@/lib/article-sections'
import { extractError, parseListField } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

// ---------------------------------------------------------------------------
// 路由：/submissions/new?edit=<id>
//   新建投稿四步向导。edit 存在时为「修改稿件」模式（复用同一套表单）。
// ---------------------------------------------------------------------------

export const Route = createFileRoute('/submissions/new')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: SubmissionWizardPage,
})

interface WizardSearch {
  edit?: number
  section?: string
}

// Nature 式栏目 / 分部选项与后台新建资源共用 lib/article-sections.ts。

// 官方字段尽量给可选项，减少作者去站外搜索：
// - 中图分类号给常用大类/高频细类，仍允许手填完整号码；
// - 期次分部给最近六期，仍允许编辑补主题名；
// - 年份给前后两年，避免手打错。
const CLC_SUGGESTIONS = [
  { value: 'TP18', label: 'TP18 人工智能理论' },
  { value: 'TP311', label: 'TP311 程序设计、软件工程' },
  { value: 'TP391', label: 'TP391 信息处理（含自然语言处理）' },
  { value: 'G250', label: 'G250 图书馆学、情报学' },
  { value: 'G350', label: 'G350 情报工作' },
  { value: 'G40', label: 'G40 教育学' },
  { value: 'B84', label: 'B84 心理学' },
  { value: 'C93', label: 'C93 管理学' },
  { value: 'F27', label: 'F27 企业经济' },
  { value: 'F83', label: 'F83 金融' },
  { value: 'D90', label: 'D90 法学理论' },
  { value: 'I207', label: 'I207 中国文学评论' },
  { value: 'J60', label: 'J60 音乐理论' },
  { value: 'K89', label: 'K89 民俗学' },
  { value: 'N02', label: 'N02 自然科学哲学' },
  { value: 'O1', label: 'O1 数学' },
  { value: 'Q1', label: 'Q1 生物学' },
  { value: 'R1', label: 'R1 预防医学、卫生学' },
  { value: 'X2', label: 'X2 环境科学' },
  { value: 'Z1', label: 'Z1 丛书、文集' },
]

const YEAR_OPTIONS = Array.from({ length: 5 }, (_, i) =>
  String(new Date().getFullYear() - 2 + i),
)

const ISSUE_PART_OPTIONS = [
  '01 期',
  '02 期',
  '03 期',
  '04 期',
  '05 期',
  '06 期 · 游戏、语言与身体',
]

// ---------------------------------------------------------------------------
// 表单状态：字段命名贴近向导语义，提交时再拍平成 SubmissionCreate。
//   clc  → jel_codes（后端只有这个分类号数组字段，前端按「中图分类号」暴露）
//   type → 'paper'（论文）/ 'tutorial'（娱乐/轻松）
// ---------------------------------------------------------------------------
interface WizardForm {
  title: string
  type: SubmissionType
  /** 论文子类型：学术/荒诞；副刊不发送 */
  paperKind: 'serious' | 'absurd'
  year: string
  discipline: string
  subdiscipline: string
  articleSection: string
  issuePart: string
  abstract: string
  preview: string
  keywords: string
  clc: string
  authors: string
  correspondingAuthorEmail: string
  body: string
  file: File | null
  venue: string
  doi: string
  externalUrl: string
  downloadUrl: string
  // 声明（纯前端勾选，提交时随 body 一起发出——后端 SubmissionCreate 无对应字段，
  // 但勾选本身是作者的承诺动作；编辑部在详情/审稿环节可读到对应承诺）。
  declOriginal: boolean
  declConfidential: boolean
  declCopyright: boolean
}

const EMPTY_FORM: WizardForm = {
  title: '',
  type: 'paper',
  paperKind: 'serious',
  year: String(new Date().getFullYear()),
  discipline: '',
  subdiscipline: '',
  articleSection: '',
  issuePart: '',
  abstract: '',
  preview: '',
  keywords: '',
  clc: '',
  authors: '',
  correspondingAuthorEmail: '',
  body: '',
  file: null,
  venue: '',
  doi: '',
  externalUrl: '',
  downloadUrl: '',
  declOriginal: false,
  declConfidential: false,
  declCopyright: false,
}

function submissionToForm(s: SubmissionResponse, body: string): WizardForm {
  const validTypes: SubmissionType[] = ['paper', 'book', 'dataset', 'tutorial']
  const type = validTypes.includes(s.type as SubmissionType)
    ? (s.type as SubmissionType)
    : 'paper'
  return {
    ...EMPTY_FORM,
    title: s.title,
    // 编辑旧稿件时若 type 是 book/dataset，向导只暴露 论文/娱乐 两档，
    // 但不把旧值清掉——提交时原样回写，避免数据被静默改成 paper。
    type,
    year: String(s.year),
    discipline: s.discipline,
    subdiscipline: s.subdiscipline ?? '',
    articleSection: s.article_section ?? '',
    issuePart: s.issue_part ?? '',
    abstract: s.abstract,
    preview: s.preview,
    keywords: s.keywords.join(', '),
    clc: s.jel_codes.join(', '),
    authors: s.authors.join(', '),
    correspondingAuthorEmail: s.corresponding_author_email ?? '',
    body,
    venue: s.venue ?? '',
    doi: s.doi ?? '',
    externalUrl: s.external_url ?? '',
    downloadUrl: s.download_url ?? '',
  }
}

// ingest 页 "提交到目录" 经 router state 传预填数据：收敛到向导表单。
function presetToForm(p: IngestResource): WizardForm {
  const validTypes: SubmissionType[] = ['paper', 'book', 'dataset', 'tutorial']
  const type = validTypes.includes(p.type as SubmissionType)
    ? (p.type as SubmissionType)
    : 'paper'
  return {
    ...EMPTY_FORM,
    title: p.title,
    type,
    authors: p.authors
      .map((a) => {
        const parts = a.split(',').map((s) => s.trim()).filter(Boolean)
        return parts.length >= 2 ? `${parts.slice(1).join(' ')} ${parts[0]}` : a
      })
      .join(', '),
    year: p.year ? String(p.year) : EMPTY_FORM.year,
    discipline: p.discipline,
    subdiscipline: p.subdiscipline ?? '',
    abstract: p.abstract,
    preview: p.abstract,
    keywords: p.tags.join(', '),
    venue: p.venue ?? '',
    doi: p.doi ?? '',
  }
}

// 注册 router state 预设字段（与列表页保持一致的声明合并）
declare module '@tanstack/history' {
  interface HistoryState {
    preset?: IngestResource
  }
}

// ---------------------------------------------------------------------------
// 硬门槛：摘要 / 关键词 / 中图分类号 / 参考文献（外加标题、作者、三项声明）。
//   参考文献：正文 Markdown 出现「参考文献/References」标题，或已选择上传文件
//   （上传后由后端 format_report 复核，前端只能做启发式判定）。
// ---------------------------------------------------------------------------
const RE_REFS_HEADING = /^#{1,6}\s*(参考文献|参考资料|References|Bibliography)\s*$/m

// 上传文件识别后的轻量元数据：只做“能填就填”，解析不出来不阻塞。
// 正文仍以 Markdown 为准；标题/摘要/关键词只是给作者省手工录入。
function extractMarkdownMeta(markdown: string): {
  title?: string
  abstract?: string
  keywords?: string
} {
  const lines = markdown.split(/\r?\n/)
  const titleLine = lines.find((line) => {
    const trimmed = line.trim()
    if (!/^#\s+\S/.test(trimmed)) return false
    const heading = trimmed.replace(/^#\s+/, '').trim()
    return !/^(摘\s*要|关键词|关键字|Abstract|Keywords?|参考文献|References?|中图分类号|CLC)$/i.test(heading)
  })
  const title = titleLine?.replace(/^#\s+/, '').trim()
  const section = (names: string) => {
    const re = new RegExp(`^#{1,6}\\s*(?:${names})\\s*$`, 'i')
    const start = lines.findIndex((line) => re.test(line.trim()))
    if (start < 0) return ''
    const out: string[] = []
    for (let i = start + 1; i < lines.length; i++) {
      if (/^#{1,6}\s+/.test(lines[i].trim())) break
      out.push(lines[i])
    }
    return out.join('\n').trim()
  }
  // DOCX/PDF 转换器常把标题、作者、摘要压成一个 **...** 前置块；
  // 没有 # 标题时从首个加粗短语兜底识别标题。
  const firstNonEmpty = lines.find((line) => line.trim())?.trim() ?? ''
  const boldLead = firstNonEmpty.match(/^\*\*([^*]{2,120})\*\*/)?.[1]?.trim()
  let abstract = section('摘\\s*要|Abstract')
  if (!abstract) {
    const inline = markdown.match(/\*\*摘\s*要[：:]\*\*\s*([\s\S]*?)(?=\*\*关键词|\*\*关键字|\n#{1,6}\s|$)/i)
    abstract = inline?.[1]?.trim() ?? ''
  }
  let keywordsRaw = section('关键词|关键字|Keywords?')
  if (!keywordsRaw) {
    keywordsRaw = markdown.match(/\*\*关键词[：:]\*\*\s*([^\n]+)/i)?.[1]?.trim() ?? ''
  }
  const keywords = keywordsRaw
    .split(/[；;，,、]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join(', ')
  return {
    title: title || boldLead || undefined,
    abstract: abstract || undefined,
    keywords: keywords || undefined,
  }
}

interface GateResult {
  key: string
  label: string
  step: number // 所属步骤 0..3
  ok: boolean
}

function computeGates(f: WizardForm): GateResult[] {
  const hasRefsHeading = RE_REFS_HEADING.test(f.body)
  const hasFile = f.file !== null
  return [
    { key: 'title', label: '标题', step: 0, ok: f.title.trim().length > 0 },
    { key: 'abstract', label: '摘要', step: 0, ok: f.abstract.trim().length > 0 },
    {
      key: 'keywords',
      label: '关键词',
      step: 0,
      ok: parseListField(f.keywords).length > 0,
    },
    {
      key: 'clc',
      label: '中图分类号',
      step: 0,
      ok: parseListField(f.clc).length > 0,
    },
    {
      key: 'discipline',
      label: '学科',
      step: 0,
      ok: f.discipline.trim().length > 0,
    },
    {
      key: 'references',
      label: '参考文献',
      step: 1,
      ok: hasRefsHeading || hasFile,
    },
    {
      key: 'authors',
      label: '作者',
      step: 2,
      ok: parseListField(f.authors).length > 0,
    },
    {
      key: 'declOriginal',
      label: '原创性声明',
      step: 2,
      ok: f.declOriginal,
    },
    {
      key: 'declConfidential',
      label: '保密声明',
      step: 2,
      ok: f.declConfidential,
    },
    {
      key: 'declCopyright',
      label: '版权许可确认',
      step: 2,
      ok: f.declCopyright,
    },
  ]
}

const STEPS = [
  { id: 0, title: '题录', hint: '标题、摘要、关键词、分类号、栏目' },
  { id: 1, title: '正文与上传', hint: '在线正文或上传稿件文件' },
  { id: 2, title: '作者与声明', hint: '作者顺序、通讯作者、三项承诺' },
  { id: 3, title: '预览并提交', hint: '通读一遍，确认后提交' },
]

const DRAFT_KEY = 'submission-wizard-draft-v1'

function SubmissionWizardPage() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as WizardSearch
  const editId = typeof search.edit === 'number' ? search.edit : undefined

  const caps = useCapabilities()
  const uploadMaxMb = Math.round(
    (caps.data?.upload_max_bytes ?? 50 * 1024 * 1024) / 1024 / 1024,
  )
  const maxUploadBytes = caps.data?.upload_max_bytes ?? 50 * 1024 * 1024
  const acceptAttr = (
    caps.data?.upload_extensions ?? ['.docx', '.doc', '.pdf', '.txt', '.zip']
  ).join(',')

  const [step, setStep] = useState(0)
  // 用户已访问过的步骤：进入过 / 点过「上一步/下一步」的步骤才显示红框，
  // 避免刚打开页面就满屏红字。
  const [visited, setVisited] = useState<boolean[]>([true, false, false, false])
  const [form, setForm] = useState<WizardForm>(() => ({
    ...EMPTY_FORM,
    articleSection: typeof search.section === 'string' ? search.section : '',
  }))
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [draftLoaded, setDraftLoaded] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ingest 页跳转过来的预填数据（router state）
  const preset = useRouterState({
    select: (s) => s.location.state?.preset,
  })
  const presetHandled = useRef(false)
  useEffect(() => {
    if (!preset || presetHandled.current || editId !== undefined) return
    presetHandled.current = true
    setForm(presetToForm(preset))
    // 消费完清空 state，避免后退/前进再次触发
    void navigate({ to: '/submissions/new', state: {}, replace: true })
  }, [preset, navigate, editId])

  // --- 编辑模式：拉取已有稿件回填 ---
  const editSubQ = useSubmission(editId ?? 0)
  const editBodyQ = useSubmissionMarkdown(editId ?? 0, editId !== undefined)
  const editLoadedRef = useRef<number | null>(null)
  useEffect(() => {
    if (!editId) return
    if (editSubQ.data && editLoadedRef.current !== editId) {
      editLoadedRef.current = editId
      setForm(submissionToForm(editSubQ.data, editBodyQ.data?.content ?? ''))
    }
  }, [editId, editSubQ.data, editBodyQ.data?.content])

  // --- 新建模式：从 localStorage 恢复草稿 ---
  useEffect(() => {
    if (editId || draftLoaded) return
    try {
      const raw = localStorage.getItem(DRAFT_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as WizardForm & { _savedAt?: number }
        setForm({
          ...EMPTY_FORM,
          ...parsed,
          ...(typeof search.section === 'string' && search.section
            ? { articleSection: search.section }
            : {}),
        })
        if (parsed._savedAt) setSavedAt(new Date(parsed._savedAt))
      }
    } catch {
      // 草稿损坏时静默忽略，不阻塞投稿
    }
    setDraftLoaded(true)
  }, [editId, draftLoaded])

  // --- 草稿自动保存（防抖 600ms）；编辑模式不写草稿 ---
  useEffect(() => {
    if (editId || !draftLoaded) return
    // 完全空白时不写，避免刚打开就落下一条空草稿
    const isBlank =
      !form.title &&
      !form.abstract &&
      !form.keywords &&
      !form.authors &&
      !form.body &&
      !form.file
    if (isBlank) return
    const t = setTimeout(() => {
      try {
        const payload = { ...form, _savedAt: Date.now() }
        localStorage.setItem(DRAFT_KEY, JSON.stringify(payload))
        setSavedAt(new Date())
      } catch {
        // 存储满或隐私模式：不打断用户
      }
    }, 600)
    return () => clearTimeout(t)
  }, [form, editId, draftLoaded])

  // --- mutations ---
  const createMut = useCreateSubmission()
  const updateMut = useUpdateSubmission()
  const saveBodyMut = useSaveSubmissionMarkdown()
  const uploadMut = useUploadSubmissionFile()
  const convertMut = useConvertSubmissionPreview()
  const [converting, setConverting] = useState(false)

  const gates = useMemo(() => computeGates(form), [form])
  const missing = gates.filter((g) => !g.ok)
  const missingCount = missing.length

  // 每个步骤的红/绿状态：当前步骤只在 visited 后才标红
  const stepGateState = useMemo(() => {
    return STEPS.map((s) => {
      const stepGates = gates.filter((g) => g.step === s.id)
      const failed = stepGates.filter((g) => !g.ok)
      return {
        id: s.id,
        failedCount: failed.length,
        // 已完成：本步骤所有门槛都过了
        done: failed.length === 0,
      }
    })
  }, [gates])

  const set = <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const goTo = (next: number) => {
    setVisited((prev) => {
      const copy = [...prev]
      for (let i = 0; i <= next; i++) copy[i] = true
      return copy
    })
    setStep(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // 「下一步」门槛：当前步骤的硬门槛必须全部通过（已 visited 才提示）。
  // 未 visited 的步骤自动放行——用户可以从左侧步骤条直接跳。
  const canProceed = stepGateState[step].failedCount === 0

  const onPickFile = (f: File) => {
    if (f.size > maxUploadBytes) {
      toast.error(
        `文件 ${(f.size / 1024 / 1024).toFixed(1)} MB 超过 ${uploadMaxMb} MB 上限，请改用网盘或仓库链接`,
      )
      return
    }
    set('file', f)
    // 选文件当下先识别一次，把 Markdown 回填到编辑器；正式提交时后端
    // 还会用同一条转换管线再跑一次并落库，编辑器内容由作者确认后提交。
    const ext = f.name.split('.').pop()?.toLowerCase()
    if (!['docx', 'doc', 'pdf', 'txt', 'md', 'markdown'].includes(ext ?? '')) {
      return
    }
    void (async () => {
      setConverting(true)
      try {
        const result = await convertMut.mutateAsync(f)
        if (!result.markdown) {
          toast.error(result.reason || '未能从文件中识别出正文，请另存为 .docx 后重试')
          return
        }
        if (form.body.trim() && !window.confirm('当前正文已有内容，是否用识别结果替换？')) {
          toast.info('已保留当前正文；文件仍会随稿件上传')
          return
        }
        set('body', result.markdown)
        const meta = extractMarkdownMeta(result.markdown)
        if (!form.title.trim() && meta.title) set('title', meta.title)
        if (!form.abstract.trim() && meta.abstract) set('abstract', meta.abstract)
        if (!form.keywords.trim() && meta.keywords) set('keywords', meta.keywords)
        if (result.warnings.length > 0) toast.warning(result.warnings.join('；'))
        toast.success(`已识别 ${result.markdown.replace(/\s/g, '').length} 字，正文已填入编辑器`)
      } catch (err) {
        toast.error(extractError(err, '文件识别失败，可先提交文件，服务器会在上传后再解析'))
      } finally {
        setConverting(false)
      }
    })()
  }

  const onSubmit = async () => {
    if (missingCount > 0) {
      // 把所有步骤都 visited，让红框一次性全部亮出来
      setVisited([true, true, true, true])
      toast.error(`还有 ${missingCount} 项未完成：${missing.map((m) => m.label).join('、')}`)
      return
    }
    const body: SubmissionCreate = {
      title: form.title.trim(),
      type: form.type,
      track: form.type === 'paper' ? form.paperKind : undefined,
      authors: parseListField(form.authors),
      year: Number(form.year) || new Date().getFullYear(),
      discipline: form.discipline.trim(),
      subdiscipline: form.subdiscipline.trim() || undefined,
      article_section: form.articleSection.trim() || undefined,
      issue_part: form.issuePart.trim() || undefined,
      abstract: form.abstract.trim(),
      preview: form.preview.trim() || form.abstract.trim().slice(0, 500),
      tags: [],
      keywords: parseListField(form.keywords),
      jel_codes: parseListField(form.clc),
      corresponding_author_email: form.correspondingAuthorEmail.trim() || undefined,
      venue: form.venue.trim() || undefined,
      doi: form.doi.trim() || undefined,
      download_url: form.downloadUrl.trim() || undefined,
      external_url: form.externalUrl.trim() || undefined,
    }

    try {
      let created: SubmissionResponse
      if (editId !== undefined) {
        created = await updateMut.mutateAsync({ id: editId, body })
        // 上传会重新转换并写 markdown_path；必须先把文件传完，再保存编辑器
        // 正文，否则作者在预览里改过的正文会被上传转换结果覆盖（旧顺序
        // 正是 create→saveBody→upload，下载件/网页与编辑器可能分叉）。
        if (form.file) {
          try {
            await uploadMut.mutateAsync({ id: editId, file: form.file })
          } catch (err) {
            toast.warning(extractError(err, '文件上传失败，已保留在线正文'))
          }
        }
        if (form.body.trim() !== '') {
          await saveBodyMut.mutateAsync({ id: editId, content: form.body })
        }
        toast.success('稿件已更新')
      } else {
        created = await createMut.mutateAsync(body)
        if (form.file) {
          try {
            await uploadMut.mutateAsync({ id: created.id, file: form.file })
          } catch (err) {
            // 文件上传失败不阻塞主流程：元数据已提交，作者可在详情页补传
            toast.warning(extractError(err, '文件上传失败，可稍后在详情页补传'))
          }
        }
        if (form.body.trim() !== '') {
          await saveBodyMut.mutateAsync({ id: created.id, content: form.body })
        }
        // 草稿已落地为正式投稿，清掉本地草稿
        try {
          localStorage.removeItem(DRAFT_KEY)
        } catch {
          // ignore
        }
        toast.success('已提交，等待编辑处理')
      }
      // 回到列表页；列表会自动 invalidate，新提交出现在第一行
      void navigate({ to: '/submissions' })
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail as { code?: string } | string | undefined
      const code =
        typeof detail === 'object' && detail !== null ? detail.code : undefined
      if (code === 'rules_ack_required') {
        toast.error('投稿前需要先阅读并确认《投稿与编辑规范》', {
          description: '正在为你打开确认页…',
          duration: 6000,
        })
        void navigate({ to: '/authors' })
        return
      }
      toast.error(extractError(err, editId !== undefined ? '更新失败' : '提交失败'))
    }
  }

  const fieldError = (key: string): boolean => {
    if (!visited[step]) return false
    return gates.find((g) => g.key === key)?.ok === false
  }

  // -----------------------------------------------------------------------
  // 渲染
  // -----------------------------------------------------------------------
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 pb-24 sm:pb-10">
      {/* 顶部：标题 + 草稿状态 */}
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">
            {editId !== undefined ? '修改稿件' : '新建投稿'}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            分四步完成：题录 → 正文 → 作者与声明 → 预览提交。草稿会自动保存在本机。
            <HelpTip className="ml-1" text="论文轨进入同行评审并按严格细则计分；副刊轨独立成刊，不走论文评审、不计分，只做编辑格式审读。" />
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {savedAt && editId === undefined && (
            <span className="inline-flex items-center gap-1">
              <Save className="h-3.5 w-3.5" />
              已保存 · {savedAt.toLocaleTimeString()}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={() => navigate({ to: '/submissions' })}>
            <ChevronLeft className="h-4 w-4" />
            返回列表
          </Button>
        </div>
      </div>

      <div className="mb-4 rounded-md border border-dashed bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
        <span className="mr-2 font-medium text-foreground">投稿前先看规格与版式：</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-submission-template.docx" download>
          Word 模板（推荐）
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-submission-template-word.md" download>
          Word 排版要求
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/templates/rubbish-editorial-standards.md" download>
          编辑规范
        </a>
        <span className="mx-2">·</span>
        <a className="font-medium text-primary hover:underline" href="/authors">
          投稿指南
        </a>
        <div className="mt-1">推荐提交 Word（.docx）：系统识别、排版和送审最稳；PDF 也可上传，下载时会自动转成 Word。</div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        {/* 左侧：步骤导航（桌面纵向；移动横向可滑动） */}
        <nav
          aria-label="投稿步骤"
          className="grid grid-cols-4 gap-1.5 pb-2 lg:flex lg:flex-col lg:gap-2 lg:pb-0"
        >
          {STEPS.map((s) => {
            const state = stepGateState[s.id]
            const isActive = step === s.id
            const showRed = visited[s.id] && state.failedCount > 0
            const showDone = visited[s.id] && state.done && !isActive
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => goTo(s.id)}
                className={[
                  'flex min-w-0 flex-col items-center gap-1 rounded-lg border px-1 py-2 text-center transition-colors lg:w-full lg:flex-row lg:items-center lg:gap-3 lg:px-3 lg:py-2.5 lg:text-left',
                  isActive
                    ? 'border-primary bg-primary/5'
                    : showRed
                      ? 'border-destructive/50 bg-destructive/5'
                      : 'border-border bg-card hover:bg-muted/40',
                ].join(' ')}
              >
                <span
                  className={[
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium',
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : showDone
                        ? 'bg-emerald-500 text-white'
                        : showRed
                          ? 'bg-destructive text-white'
                          : 'bg-muted text-muted-foreground',
                  ].join(' ')}
                >
                  {showDone ? <Check className="h-4 w-4" /> : s.id + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[11px] font-medium leading-tight lg:truncate lg:text-sm">
                    {s.title}
                    {showRed && (
                      <span className="ml-1 hidden text-xs text-destructive lg:inline">
                        · {state.failedCount} 项待补
                      </span>
                    )}
                  </span>
                  <span className="hidden truncate text-xs text-muted-foreground lg:block">
                    {s.hint}
                  </span>
                </span>
              </button>
            )
          })}
        </nav>

        {/* 右侧：当前步骤 */}
        <div className="min-w-0">
          <div className="rounded-lg border bg-card p-5 sm:p-6">
            {step === 0 && <StepBibliography form={form} set={set} fieldError={fieldError} />}
            {step === 1 && (
              <StepUpload
                form={form}
                set={set}
                fieldError={fieldError}
                acceptAttr={acceptAttr}
                uploadMaxMb={uploadMaxMb}
                fileInputRef={fileInputRef}
                onPickFile={onPickFile}
                converting={converting}
              />
            )}
            {step === 2 && <StepAuthors form={form} set={set} fieldError={fieldError} />}
            {step === 3 && (
              <StepReview form={form} missing={missing} uploadMaxMb={uploadMaxMb} />
            )}

            {/* 底部按钮区 */}
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
              <div className="text-xs text-muted-foreground">
                {step > 0 ? (
                  <Button variant="ghost" size="sm" onClick={() => goTo(step - 1)}>
                    <ChevronLeft className="h-4 w-4" />
                    上一步
                  </Button>
                ) : (
                  <span />
                )}
              </div>
              <div className="flex items-center gap-2">
                {missingCount > 0 && step === 3 && (
                  <span className="inline-flex items-center gap-1 text-xs text-destructive">
                    <AlertCircle className="h-3.5 w-3.5" />
                    还差 {missingCount} 项：{missing.map((m) => m.label).join('、')}
                  </span>
                )}
                {step < 3 ? (
                  <Button onClick={() => goTo(step + 1)} disabled={!canProceed && visited[step]}>
                    下一步
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button
                    onClick={onSubmit}
                    disabled={
                      missingCount > 0 ||
                      createMut.isPending ||
                      updateMut.isPending ||
                      uploadMut.isPending
                    }
                  >
                    {(createMut.isPending || updateMut.isPending) && (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    )}
                    {editId !== undefined
                      ? updateMut.isPending
                        ? '保存中…'
                        : '保存修改'
                      : createMut.isPending
                        ? '提交中…'
                        : missingCount > 0
                          ? `还差 ${missingCount} 项`
                          : '确认提交'}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 子步骤组件
// ---------------------------------------------------------------------------

function StepBibliography({
  form,
  set,
  fieldError,
}: {
  form: WizardForm
  set: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  fieldError: (key: string) => boolean
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">题录信息</h2>
        <p className="text-sm text-muted-foreground">
          这一步写清「这是什么文章」。摘要、关键词、中图分类号是检索与评审的硬门槛。
        </p>
      </div>

      {/* 稿件类型：学术论文 / 荒诞论文 / 副刊 */}
      <div className="space-y-2">
        <Label>稿件类型</Label>
        <div className="grid max-w-2xl grid-cols-1 gap-2 sm:grid-cols-3">
          <button
            type="button"
            onClick={() => { set('type', 'paper'); set('paperKind', 'serious') }}
            className={[
              'rounded-lg border px-4 py-3 text-left text-sm transition-colors',
              form.type === 'paper' && form.paperKind === 'serious'
                ? 'border-primary bg-primary/5 font-medium'
                : 'border-border bg-card hover:bg-muted/40',
            ].join(' ')}
          >
            学术论文
            <span className="mt-0.5 block text-xs text-muted-foreground">
              真实问题、可核查材料、正经论证
            </span>
          </button>
          <button
            type="button"
            onClick={() => { set('type', 'paper'); set('paperKind', 'absurd') }}
            className={[
              'rounded-lg border px-4 py-3 text-left text-sm transition-colors',
              form.type === 'paper' && form.paperKind === 'absurd'
                ? 'border-primary bg-primary/5 font-medium'
                : 'border-border bg-card hover:bg-muted/40',
            ].join(' ')}
          >
            荒诞论文
            <span className="mt-0.5 block text-xs text-muted-foreground">
              严格论文格式，一本正经论证荒诞命题
            </span>
          </button>
          <button
            type="button"
            onClick={() => set('type', 'tutorial')}
            className={[
              'rounded-lg border px-4 py-3 text-left text-sm transition-colors',
              form.type === 'tutorial'
                ? 'border-primary bg-primary/5 font-medium'
                : 'border-border bg-card hover:bg-muted/40',
            ].join(' ')}
          >
            副刊
            <span className="mt-0.5 block text-xs text-muted-foreground">
              小说、随笔、评论、指南、吐槽；不用论文体
            </span>
          </button>
        </div>
        <p className="text-[11px] leading-5 text-muted-foreground">
          学术论文与荒诞论文都走论文评审、百分制计分；区别只在命题是否荒诞。副刊独立成刊，不走论文评审、不计分。
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="w-title">
          标题 <span className="text-destructive">*</span>
        </Label>
        <Input
          id="w-title"
          value={form.title}
          onChange={(e) => set('title', e.target.value)}
          placeholder="一句话写清研究问题"
          className={fieldError('title') ? 'border-destructive' : ''}
        />
        {fieldError('title') && <FieldError>标题不能为空</FieldError>}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-discipline">
            学科 <span className="text-destructive">*</span>
          </Label>
          <Input
            id="w-discipline"
            list="w-discipline-options"
            value={form.discipline}
            onChange={(e) => set('discipline', e.target.value)}
            placeholder="选择或输入学科"
            className={fieldError('discipline') ? 'border-destructive' : ''}
          />
          <datalist id="w-discipline-options">
            {DISCIPLINES.flatMap((c) => c.items).map((d) => (
              <option key={d.code} value={d.name}>
                {d.name}（{d.code}）
              </option>
            ))}
          </datalist>
          {fieldError('discipline') && <FieldError>请选择或填写学科</FieldError>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-subdiscipline">子学科（选填）</Label>
          <Input
            id="w-subdiscipline"
            list="w-subdiscipline-options"
            value={form.subdiscipline}
            onChange={(e) => set('subdiscipline', e.target.value)}
            placeholder="更细的研究方向"
          />
          <datalist id="w-subdiscipline-options">
            {DISCIPLINES.flatMap((c) => c.items).map((d) => (
              <option key={d.code} value={d.name}>
                {d.name}（{d.code}）
              </option>
            ))}
          </datalist>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-section">栏目 / 分部（选填）</Label>
          <select
            id="w-section"
            value={form.articleSection}
            onChange={(e) => set('articleSection', e.target.value)}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">按学科归入默认栏目，由编辑部调整</option>
            {ARTICLE_SECTION_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            栏目只做阅读分组，不改变论文/副刊轨道；录用后进入目录页对应栏目。
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-issue-part">期次分部（选填）</Label>
          <Input
            id="w-issue-part"
            list="w-issue-part-options"
            value={form.issuePart}
            onChange={(e) => set('issuePart', e.target.value)}
            placeholder="选择期次，或补主题名"
          />
          <datalist id="w-issue-part-options">
            {ISSUE_PART_OPTIONS.map((part) => (
              <option key={part} value={part} />
            ))}
          </datalist>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="w-abstract">
          摘要 <span className="text-destructive">*</span>
        </Label>
        <Textarea
          id="w-abstract"
          rows={6}
          value={form.abstract}
          onChange={(e) => set('abstract', e.target.value)}
          placeholder="研究问题、方法、主要结论（建议 200–400 字）"
          className={fieldError('abstract') ? 'border-destructive' : ''}
        />
        {fieldError('abstract') && <FieldError>摘要不能为空</FieldError>}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-keywords">
            关键词（逗号分隔） <span className="text-destructive">*</span>
          </Label>
          <Input
            id="w-keywords"
            value={form.keywords}
            onChange={(e) => set('keywords', e.target.value)}
            placeholder="例如：大语言模型, Agent, RAG"
            className={fieldError('keywords') ? 'border-destructive' : ''}
          />
          {fieldError('keywords') && <FieldError>至少填一个关键词</FieldError>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-clc">
            中图分类号（CLC，逗号分隔） <span className="text-destructive">*</span>
          </Label>
          <Input
            id="w-clc"
            list="w-clc-options"
            value={form.clc}
            onChange={(e) => set('clc', e.target.value)}
            placeholder="选择或输入，例如：TP18, G250"
            className={fieldError('clc') ? 'border-destructive' : ''}
          />
          <datalist id="w-clc-options">
            {CLC_SUGGESTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </datalist>
          <p className="text-xs text-muted-foreground">
            可直接选常用号，也可手填完整分类号；找不到时填最接近的大类。
          </p>
          {fieldError('clc') && <FieldError>中图分类号不能为空</FieldError>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-year">年份</Label>
          <select
            id="w-year"
            value={form.year}
            onChange={(e) => set('year', e.target.value)}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          >
            {YEAR_OPTIONS.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-venue">出版物/期刊（选填）</Label>
          <Input
            id="w-venue"
            value={form.venue}
            onChange={(e) => set('venue', e.target.value)}
            placeholder="若已有正式出处"
          />
        </div>
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="w-doi">官方 DOI（选填，作者自行决定是否注册）</Label>
          <Input
            id="w-doi"
            value={form.doi}
            onChange={(e) => set('doi', e.target.value)}
            placeholder="例如：10.12345/rubbish.2026.001；没有就留空"
          />
          <p className="text-xs text-muted-foreground">
            本站会为每篇录用稿生成内部刊号；官方 DOI 由作者决定是否另行注册，不强制。
          </p>
        </div>
      </div>
    </div>
  )
}

function StepUpload({
  form,
  set,
  fieldError,
  acceptAttr,
  uploadMaxMb,
  fileInputRef,
  onPickFile,
  converting,
}: {
  form: WizardForm
  set: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  fieldError: (key: string) => boolean
  acceptAttr: string
  uploadMaxMb: number
  fileInputRef: React.RefObject<HTMLInputElement | null>
  onPickFile: (f: File) => void
  converting: boolean
}) {
  const hasRefsHeading = RE_REFS_HEADING.test(form.body)
  const [sourcePreviewOpen, setSourcePreviewOpen] = useState(false)
  const [sourcePreview, setSourcePreview] = useState<{ token: string; pages: number } | null>(null)
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false)

  const openSourcePreview = async () => {
    if (!form.file) {
      toast.error('请先选择要预览的 Word / PDF 文件')
      return
    }
    setSourcePreviewLoading(true)
    try {
      const preview = await previewUploadedSourcePages(form.file)
      setSourcePreview(preview)
      setSourcePreviewOpen(true)
    } catch (err) {
      toast.error(extractError(err, '原件预览失败；可先提交，服务器会在上传后解析'))
    } finally {
      setSourcePreviewLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">正文与文件</h2>
        <p className="text-sm text-muted-foreground">
          先上传 Word / PDF，系统识别后自动填到下面的正文；也可以直接在线写。两条都保留时，以你在编辑器里最终改定的正文为准。
        </p>
      </div>

      {/* 1. 上传优先：人的动作是“先给稿，再校对”，不是先面对一个空编辑器。 */}
      <section className="rounded-xl border bg-card p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                1
              </span>
              <h3 className="text-sm font-semibold">上传 Word / PDF</h3>
              <Badge variant="secondary" className="text-[10px]">可选 · 推荐</Badge>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              选完文件就会自动识别并回填正文，不需要先提交。DOCX 识别最稳；PDF 识别后会转成可编辑正文。
            </p>
          </div>
          {form.file && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={sourcePreviewLoading}
              onClick={() => void openSourcePreview()}
            >
              {sourcePreviewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              原件预览
            </Button>
          )}
        </div>

        <div className="rounded-lg border border-dashed bg-muted/20 p-3">
          <input
            ref={fileInputRef}
            type="file"
            accept={acceptAttr}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onPickFile(f)
              e.target.value = ''
            }}
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {form.file ? (
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <FileText className="h-7 w-7 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{form.file.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {(form.file.size / 1024).toFixed(0)} KB ·
                    {converting ? ' 正在识别并回填正文…' : ' 已识别，可在下方正文继续修改'}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-destructive"
                  onClick={() => set('file', null)}
                >
                  <X className="h-4 w-4" />
                  移除
                </Button>
              </div>
            ) : (
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <Upload className="h-7 w-7 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">还没有选择文件</div>
                  <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                    支持 DOCX / PDF 等 {acceptAttr.split(',').length} 种格式，单文件 ≤ {uploadMaxMb} MB
                  </div>
                </div>
              </div>
            )}
            <Button
              type="button"
              variant={form.file ? 'outline' : 'default'}
              size="sm"
              disabled={converting}
              className="w-full sm:w-auto"
              onClick={() => fileInputRef.current?.click()}
            >
              {converting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {form.file ? '替换文件' : '选择文件'}
            </Button>
          </div>
        </div>
        {converting && (
          <p className="mt-2 flex items-center gap-2 text-xs text-primary">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在识别文档结构并填入正文，请稍候…
          </p>
        )}
      </section>

      {/* 2. 正文：上传后自动回填到这里，校对/修改都在这一块完成。 */}
      <section className="rounded-xl border bg-card p-4 sm:p-5">
        <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                2
              </span>
              <h3 className="text-sm font-semibold">在线正文（Markdown）</h3>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              这里就是最终发表与 Word/PDF 下载使用的正文。上方识别结果会自动填进来。
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {hasRefsHeading ? (
              <Badge className="bg-emerald-500/15 text-emerald-700">已检测到参考文献</Badge>
            ) : (
              <Badge variant="outline" className={fieldError('references') ? 'border-destructive/50 text-destructive' : ''}>
                未检测到参考文献
              </Badge>
            )}
          </div>
        </div>
        <MarkdownEditor
          value={form.body}
          onChange={(v) => set('body', v)}
          minHeight={320}
          placeholder={
            '# 1 引言\n\n# 2 方法\n\n# 3 结果\n\n# 4 结论\n\n# 参考文献\n\n[1] …'
          }
          testId="wizard-body-editor"
        />
        {fieldError('references') && (
          <FieldError>
            请在正文末尾加入「参考文献」章节，或直接上传稿件文件
          </FieldError>
        )}
      </section>

      {/* 3. 规范与模板：不常看，收进折叠；需要时再展开，不再占正文上方一整屏。 */}
      <details className="rounded-lg border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none font-medium text-foreground">
          格式要求与模板（点击展开）
        </summary>
        <ul className="mt-2 list-inside list-disc space-y-1 leading-relaxed">
          <li>允许格式：{acceptAttr.split(',').join(' / ')} 等；单文件 ≤ {uploadMaxMb} MB。</li>
          <li>正文内请包含「摘要」「关键词」段落，并在文末给出「参考文献 / References」章节。</li>
          <li>
            版式：先下载
            <a className="mx-1 font-medium text-primary hover:underline" href="/templates/rubbish-submission-template.docx" download>
              Word 模板（推荐）
            </a>
            照着改；逐项设置见
            <a className="mx-1 font-medium text-primary hover:underline" href="/templates/rubbish-submission-template-word.md" download>
              Word 排版要求
            </a>
            ，完整细则见
            <a className="mx-1 font-medium text-primary hover:underline" href="/templates/rubbish-editorial-standards.md" download>
              编辑规范
            </a>
            。
          </li>
        </ul>
      </details>

      <Dialog open={sourcePreviewOpen} onOpenChange={setSourcePreviewOpen}>
        <DialogContent className="flex h-[86vh] max-w-5xl flex-col overflow-hidden p-0">
          <DialogHeader className="border-b px-4 py-3">
            <DialogTitle className="text-sm">原件预览 · {form.file?.name ?? ''}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 p-2">
            {sourcePreview ? (
              <SourcePreviewPng token={sourcePreview.token} pages={sourcePreview.pages} />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                正在生成原件预览…
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* 4. 补充材料：不打断主流程，需要时展开。 */}
      <details className="rounded-lg border bg-card px-3 py-2">
        <summary className="cursor-pointer select-none text-sm font-medium">
          补充材料（代码 / 数据 / 外部链接，可选）
        </summary>
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="w-ext">代码与数据链接</Label>
            <Input
              id="w-ext"
              type="url"
              value={form.externalUrl}
              onChange={(e) => set('externalUrl', e.target.value)}
              placeholder="https://github.com/you/paper"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="w-dl">稿件直链</Label>
            <Input
              id="w-dl"
              type="url"
              value={form.downloadUrl}
              onChange={(e) => set('downloadUrl', e.target.value)}
              placeholder="https://…/paper.pdf"
            />
          </div>
        </div>
      </details>
    </div>
  )
}

function StepAuthors({
  form,
  set,
  fieldError,
}: {
  form: WizardForm
  set: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  fieldError: (key: string) => boolean
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">作者与声明</h2>
        <p className="text-sm text-muted-foreground">
          作者顺序即署名顺序；请确认通讯作者与三项承诺。
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="w-authors">
          作者（逗号分隔，顺序即署名顺序） <span className="text-destructive">*</span>
        </Label>
        <Input
          id="w-authors"
          value={form.authors}
          onChange={(e) => set('authors', e.target.value)}
          placeholder="张三, 李四, 王五"
          className={fieldError('authors') ? 'border-destructive' : ''}
        />
        {fieldError('authors') && <FieldError>至少填写一位作者</FieldError>}
      </div>

      <div className="space-y-2">
        <Label htmlFor="w-corresp">通讯作者邮箱（选填）</Label>
        <Input
          id="w-corresp"
          type="email"
          value={form.correspondingAuthorEmail}
          onChange={(e) => set('correspondingAuthorEmail', e.target.value)}
          placeholder="corresponding@example.com"
        />
        <p className="text-xs text-muted-foreground">
          审稿意见与录用通知会发到这个邮箱；留空则用账号注册邮箱。
        </p>
      </div>

      <div className="space-y-3 rounded-lg border p-4">
        <div className="text-sm font-medium">投稿承诺</div>
        <DeclCheckbox
          checked={form.declOriginal}
          onChange={(v) => set('declOriginal', v)}
          label="原创性声明"
          description="本稿件为作者原创，未一稿多投，不存在抄袭、代写或署名不当。"
          error={fieldError('declOriginal')}
        />
        <DeclCheckbox
          checked={form.declConfidential}
          onChange={(v) => set('declConfidential', v)}
          label="保密与合规声明"
          description="稿件不涉及未公开的涉密数据、隐私数据或第三方知识产权侵权。"
          error={fieldError('declConfidential')}
        />
        <DeclCheckbox
          checked={form.declCopyright}
          onChange={(v) => set('declCopyright', v)}
          label="版权与许可确认"
          description="作者同意本刊以现行许可协议（CC BY-NC 等）发布本稿件，授权编辑部进行编校与导出。"
          error={fieldError('declCopyright')}
        />
      </div>
    </div>
  )
}

function StepReview({
  form,
  missing,
  uploadMaxMb,
}: {
  form: WizardForm
  missing: { key: string; label: string }[]
  uploadMaxMb: number
}) {
  const authors = parseListField(form.authors)
  const keywords = parseListField(form.keywords)
  const clc = parseListField(form.clc)
  const firstPara =
    form.abstract
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean)[0] ?? ''
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">预览并提交</h2>
        <p className="text-sm text-muted-foreground">
          请通读一遍。确认无误后点击下方「确认提交」，提交后状态为「待审核」。
        </p>
      </div>

      {missing.length > 0 && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          <div className="mb-1 flex items-center gap-1.5 font-medium">
            <AlertCircle className="h-4 w-4" />
            还有 {missing.length} 项未完成
          </div>
          <ul className="list-inside list-disc text-xs">
            {missing.map((m) => (
              <li key={m.key}>{m.label}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-3 rounded-lg border p-4 text-sm">
        <div>
          <div className="text-xs text-muted-foreground">标题</div>
          <div className="mt-0.5 font-medium">{form.title || '—'}</div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-xs text-muted-foreground">类型</div>
            <div>{form.type === 'tutorial' ? '副刊' : form.paperKind === 'absurd' ? '荒诞论文' : '学术论文'}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">学科/栏目</div>
            <div>{form.discipline || '—'}</div>
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">摘要（首段）</div>
          <p className="mt-0.5 whitespace-pre-wrap text-muted-foreground">
            {firstPara || '—'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {keywords.length > 0 ? (
            keywords.map((k) => (
              <Badge key={k} variant="secondary">
                {k}
              </Badge>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">关键词未填</span>
          )}
        </div>
        <div>
          <div className="text-xs text-muted-foreground">中图分类号（CLC）</div>
          <div className="mt-0.5">{clc.join(' / ') || '—'}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">作者</div>
          <div className="mt-0.5">
            {authors.length > 0 ? authors.join('、') : '—'}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">稿件文件</div>
          <div className="mt-0.5">
            {form.file ? (
              <span>
                {form.file.name} · {(form.file.size / 1024).toFixed(0)} KB（≤ {uploadMaxMb} MB）
              </span>
            ) : form.body.trim() ? (
              <span>使用在线正文（{form.body.length} 字）</span>
            ) : (
              <span className="text-destructive">未上传文件，也未填写在线正文</span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 pt-1">
          <DeclBadge ok={form.declOriginal} label="原创性声明" />
          <DeclBadge ok={form.declConfidential} label="保密声明" />
          <DeclBadge ok={form.declCopyright} label="版权许可" />
        </div>
      </div>

      {form.body.trim() ? (
        <ArticlePreview
          title={form.title}
          authors={authors}
          abstract={form.abstract}
          keywords={keywords}
          body={form.body}
        />
      ) : (
        <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          还没有正文，无法生成发布效果预览。请先上传 Word/PDF 或填写在线正文。
        </div>
      )}
    </div>
  )
}

function FieldError({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-1 text-xs text-destructive">
      <AlertCircle className="h-3 w-3" />
      {children}
    </p>
  )
}

function DeclCheckbox({
  checked,
  onChange,
  label,
  description,
  error,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description: string
  error?: boolean
}) {
  return (
    <label
      className={[
        'flex cursor-pointer items-start gap-3 rounded-md p-2',
        error ? 'bg-destructive/5' : 'hover:bg-muted/40',
      ].join(' ')}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4"
      />
      <span>
        <span className="block text-sm font-medium">{label}</span>
        <span className="block text-xs text-muted-foreground">{description}</span>
      </span>
    </label>
  )
}

function DeclBadge({ ok, label }: { ok: boolean; label: string }) {
  return ok ? (
    <Badge className="bg-emerald-500/15 text-emerald-700">
      <Check className="mr-1 h-3 w-3" />
      {label}已确认
    </Badge>
  ) : (
    <Badge variant="outline" className="border-destructive/50 text-destructive">
      {label}未勾选
    </Badge>
  )
}
