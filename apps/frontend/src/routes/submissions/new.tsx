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
import { useCapabilities } from '@/hooks/use-capabilities'
import {
  useCreateSubmission,
  useSaveSubmissionMarkdown,
  useSubmission,
  useSubmissionMarkdown,
  useUpdateSubmission,
  useUploadSubmissionFile,
} from '@/hooks/api/use-modules'
import { MarkdownEditor } from '@/components/common/markdown-editor'
import type {
  IngestResource,
  SubmissionCreate,
  SubmissionResponse,
  SubmissionType,
} from '@/lib/types'
import { DISCIPLINES } from '@/lib/disciplines'
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
}

// ---------------------------------------------------------------------------
// 表单状态：字段命名贴近向导语义，提交时再拍平成 SubmissionCreate。
//   clc  → jel_codes（后端只有这个分类号数组字段，前端按「中图分类号」暴露）
//   type → 'paper'（论文）/ 'tutorial'（娱乐/轻松）
// ---------------------------------------------------------------------------
interface WizardForm {
  title: string
  type: SubmissionType
  year: string
  discipline: string
  subdiscipline: string
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
  year: String(new Date().getFullYear()),
  discipline: '',
  subdiscipline: '',
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
      label: '学科/栏目',
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
    caps.data?.upload_extensions ?? ['.pdf', '.docx', '.doc', '.txt', '.zip']
  ).join(',')

  const [step, setStep] = useState(0)
  // 用户已访问过的步骤：进入过 / 点过「上一步/下一步」的步骤才显示红框，
  // 避免刚打开页面就满屏红字。
  const [visited, setVisited] = useState<boolean[]>([true, false, false, false])
  const [form, setForm] = useState<WizardForm>(EMPTY_FORM)
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
        setForm({ ...EMPTY_FORM, ...parsed })
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
      authors: parseListField(form.authors),
      year: Number(form.year) || new Date().getFullYear(),
      discipline: form.discipline.trim(),
      subdiscipline: form.subdiscipline.trim() || undefined,
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
        if (form.body.trim() !== '') {
          await saveBodyMut.mutateAsync({ id: editId, content: form.body })
        }
        toast.success('稿件已更新')
      } else {
        created = await createMut.mutateAsync(body)
        if (form.body.trim() !== '') {
          await saveBodyMut.mutateAsync({ id: created.id, content: form.body })
        }
        if (form.file) {
          try {
            await uploadMut.mutateAsync({ id: created.id, file: form.file })
          } catch (err) {
            // 文件上传失败不阻塞主流程：元数据已提交，作者可在详情页补传
            toast.warning(extractError(err, '文件上传失败，可稍后在详情页补传'))
          }
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
    <div className="mx-auto w-full max-w-6xl px-4 py-6">
      {/* 顶部：标题 + 草稿状态 */}
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">
            {editId !== undefined ? '修改稿件' : '新建投稿'}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            分四步完成：题录 → 正文 → 作者与声明 → 预览提交。草稿会自动保存在本机。
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        {/* 左侧：步骤导航（桌面纵向；移动横向可滑动） */}
        <nav
          aria-label="投稿步骤"
          className="flex gap-2 overflow-x-auto pb-2 lg:flex-col lg:overflow-visible lg:pb-0"
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
                  'flex shrink-0 items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors lg:w-full',
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
                  <span className="block truncate text-sm font-medium">
                    {s.title}
                    {showRed && (
                      <span className="ml-1 text-xs text-destructive">
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

      {/* 稿件类型：论文 / 娱乐 */}
      <div className="space-y-2">
        <Label>稿件类型</Label>
        <div className="grid max-w-md grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => set('type', 'paper')}
            className={[
              'rounded-lg border px-4 py-3 text-sm transition-colors',
              form.type === 'paper'
                ? 'border-primary bg-primary/5 font-medium'
                : 'border-border bg-card hover:bg-muted/40',
            ].join(' ')}
          >
            学术论文
            <span className="mt-0.5 block text-xs text-muted-foreground">
              正式研究、实证、综述
            </span>
          </button>
          <button
            type="button"
            onClick={() => set('type', 'tutorial')}
            className={[
              'rounded-lg border px-4 py-3 text-sm transition-colors',
              form.type === 'tutorial'
                ? 'border-primary bg-primary/5 font-medium'
                : 'border-border bg-card hover:bg-muted/40',
            ].join(' ')}
          >
            娱乐/轻松
            <span className="mt-0.5 block text-xs text-muted-foreground">
              随笔、吐槽、趣味教程
            </span>
          </button>
        </div>
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
            学科/栏目 <span className="text-destructive">*</span>
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
            value={form.clc}
            onChange={(e) => set('clc', e.target.value)}
            placeholder="例如：TP18, G250"
            className={fieldError('clc') ? 'border-destructive' : ''}
          />
          <p className="text-xs text-muted-foreground">
            在<span className="mx-1">《中国图书馆分类法》</span>网站可查；找不到可填最接近的大类。
          </p>
          {fieldError('clc') && <FieldError>中图分类号不能为空</FieldError>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-year">年份</Label>
          <Input
            id="w-year"
            type="number"
            value={form.year}
            onChange={(e) => set('year', e.target.value)}
          />
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
}: {
  form: WizardForm
  set: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  fieldError: (key: string) => boolean
  acceptAttr: string
  uploadMaxMb: number
  fileInputRef: React.RefObject<HTMLInputElement | null>
  onPickFile: (f: File) => void
}) {
  const hasRefsHeading = RE_REFS_HEADING.test(form.body)
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">正文与文件上传</h2>
        <p className="text-sm text-muted-foreground">
          在线正文与上传文件二选一或并用：直接在下方写 Markdown，或上传 PDF / Word 稿件。
        </p>
      </div>

      {/* 格式要求常显卡片 */}
      <div className="rounded-md border border-dashed bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
        <div className="mb-1 font-medium text-foreground">稿件格式要求</div>
        <ul className="list-inside list-disc space-y-0.5">
          <li>允许格式：{acceptAttr.split(',').join(' / ')} 等</li>
          <li>单文件大小上限：{uploadMaxMb} MB（更大请用网盘/仓库链接）</li>
          <li>
            正文内请包含「摘要」「关键词」段落，并在文末给出
            <span className="mx-1 font-medium">「参考文献 / References」</span>
            章节——这是编辑部结构检查的硬指标。
          </li>
        </ul>
      </div>

      {/* 在线正文 */}
      <div className="space-y-2">
        <Label htmlFor="w-body">在线正文（Markdown）</Label>
        <p className="text-xs text-muted-foreground">
          写在这里的正文会直接进入在线阅读、Word 下载与 JATS 导出；与上传文件互为补充。
        </p>
        <MarkdownEditor
          value={form.body}
          onChange={(v) => set('body', v)}
          minHeight={280}
          placeholder={
            '# 1 引言\n\n# 2 方法\n\n# 3 结果\n\n# 4 结论\n\n# 参考文献\n\n[1] …'
          }
          testId="wizard-body-editor"
        />
        <div className="flex flex-wrap gap-2 text-xs">
          {hasRefsHeading ? (
            <Badge className="bg-emerald-500/15 text-emerald-700">
              已检测到「参考文献」章节
            </Badge>
          ) : (
            <Badge variant="outline" className={fieldError('references') ? 'border-destructive/50 text-destructive' : ''}>
              未检测到「参考文献」章节标题
            </Badge>
          )}
          {form.file && (
            <Badge className="bg-primary/15 text-primary">
              已选择文件：{form.file.name}
            </Badge>
          )}
        </div>
        {fieldError('references') && (
          <FieldError>
            请在正文末尾加入「参考文献」章节，或直接上传稿件文件
          </FieldError>
        )}
      </div>

      {/* 文件上传区 */}
      <div className="space-y-2">
        <Label>稿件文件</Label>
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-4">
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
          {form.file ? (
            <div className="flex flex-1 items-center gap-3">
              <FileText className="h-8 w-8 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{form.file.name}</div>
                <div className="text-xs text-muted-foreground">
                  {(form.file.size / 1024).toFixed(0)} KB · 等待提交后由服务器解析
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => set('file', null)}
              >
                <X className="h-4 w-4" />
                移除
              </Button>
            </div>
          ) : (
            <div className="flex flex-1 items-center gap-3">
              <Upload className="h-8 w-8 text-muted-foreground" />
              <div className="flex-1 text-sm text-muted-foreground">
                未选择文件。点击右侧按钮选择 PDF / Word / Markdown，
                或直接在上方写在线正文。
              </div>
            </div>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-4 w-4" />
            {form.file ? '替换文件' : '选择文件'}
          </Button>
        </div>
      </div>

      {/* 选填：外部链接 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="w-ext">代码与数据链接（推荐）</Label>
          <Input
            id="w-ext"
            type="url"
            value={form.externalUrl}
            onChange={(e) => set('externalUrl', e.target.value)}
            placeholder="https://github.com/you/paper"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="w-dl">稿件直链（选填）</Label>
          <Input
            id="w-dl"
            type="url"
            value={form.downloadUrl}
            onChange={(e) => set('downloadUrl', e.target.value)}
            placeholder="https://…/paper.pdf"
          />
        </div>
      </div>
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
            <div>{form.type === 'tutorial' ? '娱乐/轻松' : '学术论文'}</div>
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
