import { useState } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { AxiosError } from 'axios'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import { parseListField } from '@/lib/utils'
import { DISCIPLINES } from '@/lib/disciplines'
import { ARTICLE_SECTION_OPTIONS } from '@/lib/article-sections'
import { useCreateResource } from '@/hooks/api/use-modules'
import type { PublicationStatus, ResourceCreate, ResourceType } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export const Route = createFileRoute('/catalog/new')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: NewResourcePage,
})

const TYPE_OPTIONS: { value: ResourceType; label: string }[] = [
  { value: 'paper', label: '论文' },
  { value: 'book', label: '图书' },
  { value: 'dataset', label: '数据集' },
  { value: 'tutorial', label: '教程' },
]

const STATUS_OPTIONS: { value: PublicationStatus; label: string }[] = [
  { value: 'published', label: '已发表' },
  { value: 'in_review', label: '审稿中' },
  { value: 'draft', label: '草稿' },
]

interface FormState {
  type: ResourceType
  title: string
  authors: string
  year: string
  discipline: string
  article_section: string
  issue_part: string
  abstract: string
  preview: string
  venue: string
  subdiscipline: string
  tags: string
  doi: string
  download_url: string
  external_url: string
  volume: string
  issue: string
  pages: string
  issn: string
  isbn: string
  language: string
  publication_status: PublicationStatus
  slug: string
}

function NewResourcePage() {
  const navigate = useNavigate()
  const createMut = useCreateResource()

  const [form, setForm] = useState<FormState>({
    type: 'paper',
    title: '',
    authors: '',
    year: String(new Date().getFullYear()),
    discipline: '',
    article_section: '',
    issue_part: '',
    abstract: '',
    preview: '',
    venue: '',
    subdiscipline: '',
    tags: '',
    doi: '',
    download_url: '',
    external_url: '',
    volume: '',
    issue: '',
    pages: '',
    issn: '',
    isbn: '',
    language: 'zh',
    publication_status: 'published',
    slug: '',
  })

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const body: ResourceCreate = {
      type: form.type,
      title: form.title,
      authors: parseListField(form.authors),
      year: Number(form.year),
      discipline: form.discipline,
      article_section: form.article_section || undefined,
      issue_part: form.issue_part || undefined,
      abstract: form.abstract,
      preview: form.preview,
      tags: parseListField(form.tags),
      language: form.language,
      publication_status: form.publication_status,
      venue: form.venue || undefined,
      subdiscipline: form.subdiscipline || undefined,
      doi: form.doi || undefined,
      download_url: form.download_url || undefined,
      external_url: form.external_url || undefined,
      volume: form.volume || undefined,
      issue: form.issue || undefined,
      pages: form.pages || undefined,
      issn: form.issn || undefined,
      isbn: form.isbn || undefined,
      slug: form.slug || undefined,
    }
    try {
      const created = await createMut.mutateAsync(body)
      toast.success('创建成功')
      void navigate({
        to: '/catalog/$resourceId',
        params: { resourceId: String(created.id) },
      })
    } catch (err) {
      const msg =
        err instanceof AxiosError
          ? (err.response?.data as { detail?: string })?.detail ?? '创建失败'
          : '创建失败'
      toast.error(msg)
    }
  }

  return (
    <div>
      <PageHeader title="新建资源" description="创建一条新的学术资源记录。" />
      <Card>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-6">
            {/* 必填区 */}
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-muted-foreground">必填信息</h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="type">类型</Label>
                  <Select
                    value={form.type}
                    onValueChange={(v) => set('type', v as ResourceType)}
                  >
                    <SelectTrigger id="type" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TYPE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="year">年份</Label>
                  <Input
                    id="year"
                    type="number"
                    value={form.year}
                    onChange={(e) => set('year', e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="title">标题</Label>
                <Input
                  id="title"
                  value={form.title}
                  onChange={(e) => set('title', e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="authors">作者（逗号分隔）</Label>
                <Input
                  id="authors"
                  value={form.authors}
                  onChange={(e) => set('authors', e.target.value)}
                  placeholder="Alice Smith, Bob Jones"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="discipline">学科</Label>
                {/* datalist 选择器：选项来自 2026 学科目录，同时保留自由输入
                    兜底——本刊为讽刺性期刊，允许自创学科。存学科名。 */}
                <Input
                  id="discipline"
                  list="discipline-options"
                  value={form.discipline}
                  onChange={(e) => set('discipline', e.target.value)}
                  placeholder="选择或输入学科"
                  required
                />
                <datalist id="discipline-options">
                  {DISCIPLINES.flatMap((c) => c.items).map((d) => (
                    <option key={d.code} value={d.name}>
                      {d.name}（{d.code}）
                    </option>
                  ))}
                </datalist>
              </div>
              <div className="space-y-2">
                <Label htmlFor="article_section">栏目 / 分部</Label>
                <select
                  id="article_section"
                  value={form.article_section}
                  onChange={(e) => set('article_section', e.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="">不指定（由目录按学科归组）</option>
                  {ARTICLE_SECTION_OPTIONS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="issue_part">期次分部</Label>
                <Input
                  id="issue_part"
                  value={form.issue_part}
                  onChange={(e) => set('issue_part', e.target.value)}
                  placeholder="例如：06 期 · 游戏、语言与身体"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="abstract">摘要</Label>
                <Textarea
                  id="abstract"
                  value={form.abstract}
                  onChange={(e) => set('abstract', e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="preview">预览（留空将自动截取摘要）</Label>
                <Textarea
                  id="preview"
                  value={form.preview}
                  onChange={(e) => set('preview', e.target.value)}
                />
              </div>
            </div>

            {/* 选填区 */}
            <div className="space-y-4 border-t pt-4">
              <h3 className="text-sm font-medium text-muted-foreground">选填信息</h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="venue">出版物</Label>
                  <Input
                    id="venue"
                    value={form.venue}
                    onChange={(e) => set('venue', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="subdiscipline">子学科</Label>
                  {/* 子学科同样走 datalist：目录为一级学科名，可自由输入 */}
                  <Input
                    id="subdiscipline"
                    list="subdiscipline-options"
                    value={form.subdiscipline}
                    onChange={(e) => set('subdiscipline', e.target.value)}
                    placeholder="选择或输入子学科"
                  />
                  <datalist id="subdiscipline-options">
                    {DISCIPLINES.flatMap((c) => c.items).map((d) => (
                      <option key={d.code} value={d.name}>
                        {d.name}（{d.code}）
                      </option>
                    ))}
                  </datalist>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tags">标签（逗号分隔）</Label>
                  <Input
                    id="tags"
                    value={form.tags}
                    onChange={(e) => set('tags', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="doi">DOI</Label>
                  <Input
                    id="doi"
                    value={form.doi}
                    onChange={(e) => set('doi', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="download_url">下载链接</Label>
                  <Input
                    id="download_url"
                    type="url"
                    value={form.download_url}
                    onChange={(e) => set('download_url', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="external_url">外部链接</Label>
                  <Input
                    id="external_url"
                    type="url"
                    value={form.external_url}
                    onChange={(e) => set('external_url', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="volume">卷</Label>
                  <Input
                    id="volume"
                    value={form.volume}
                    onChange={(e) => set('volume', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="issue">期</Label>
                  <Input
                    id="issue"
                    value={form.issue}
                    onChange={(e) => set('issue', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pages">页码</Label>
                  <Input
                    id="pages"
                    value={form.pages}
                    onChange={(e) => set('pages', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="issn">ISSN</Label>
                  <Input
                    id="issn"
                    value={form.issn}
                    onChange={(e) => set('issn', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="isbn">ISBN</Label>
                  <Input
                    id="isbn"
                    value={form.isbn}
                    onChange={(e) => set('isbn', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="language">语言</Label>
                  <Input
                    id="language"
                    value={form.language}
                    onChange={(e) => set('language', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="publication_status">发表状态</Label>
                  <Select
                    value={form.publication_status}
                    onValueChange={(v) =>
                      set('publication_status', v as PublicationStatus)
                    }
                  >
                    <SelectTrigger id="publication_status" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="slug">Slug</Label>
                  <Input
                    id="slug"
                    value={form.slug}
                    onChange={(e) => set('slug', e.target.value)}
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate({ to: '/catalog' })}
              >
                取消
              </Button>
              <Button type="submit" disabled={createMut.isPending}>
                {createMut.isPending ? '创建中…' : '创建'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
