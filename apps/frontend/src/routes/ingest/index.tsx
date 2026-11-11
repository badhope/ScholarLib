import { useState } from 'react'
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { AlertCircle, ArrowRight } from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import { useFetchIngest, useParseIngest } from '@/hooks/api/use-modules'
import type { FetchSource, IngestResource, ParseFormat } from '@/lib/types'
import { PageHeader } from '@/components/common/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { extractError } from '@/lib/utils'

export const Route = createFileRoute('/ingest/')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: IngestPage,
})

const FORMAT_OPTIONS: { value: ParseFormat; label: string }[] = [
  { value: 'bibtex', label: 'BibTeX' },
  { value: 'ris', label: 'RIS' },
  { value: 'csv', label: 'CSV' },
]

const SOURCE_OPTIONS: { value: FetchSource; label: string }[] = [
  { value: 'crossref', label: 'Crossref' },
  { value: 'arxiv', label: 'arXiv' },
]

// 解析结果与查询结果共用同一种卡片渲染，"提交到目录" 跳 /submissions 并带 preset
function ResourceCard({
  resource,
  onSend,
}: {
  resource: IngestResource
  onSend: (r: IngestResource) => void
}) {
  return (
    <Card>
      <CardContent className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-medium">{resource.title}</h3>
          <Button size="sm" onClick={() => onSend(resource)}>
            提交到目录
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline">{resource.type}</Badge>
          {resource.year && <span>{resource.year}</span>}
          <span>{resource.discipline}</span>
          {resource.doi && <span>{resource.doi}</span>}
        </div>
        {resource.authors.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {/* 解析结果常是 "Last, First" 形式：先规范成 "First Last" 再用顿号连接，
                否则 "Kingma, Diederik P, Ba, Jimmy" 看着像四个作者 */}
            {resource.authors
              .map((a) => {
                const parts = a
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean)
                return parts.length >= 2
                  ? `${parts.slice(1).join(' ')} ${parts[0]}`
                  : a
              })
              .join('、')}
          </p>
        )}
        {resource.abstract && (
          <p className="line-clamp-3 text-sm">{resource.abstract}</p>
        )}
      </CardContent>
    </Card>
  )
}

function IngestPage() {
  const navigate = useNavigate()
  const parseMut = useParseIngest()
  const fetchMut = useFetchIngest()

  const [format, setFormat] = useState<ParseFormat>('bibtex')
  const [content, setContent] = useState('')
  const [source, setSource] = useState<FetchSource>('crossref')
  const [id, setId] = useState('')

  const sendToSubmissions = (r: IngestResource) => {
    void navigate({ to: '/submissions/new', state: { preset: r } })
  }

  const onParse = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const res = await parseMut.mutateAsync({ format, content })
      toast.success(`解析完成，成功 ${res.count} 条`)
    } catch (err) {
      toast.error(extractError(err, '解析失败'))
    }
  }

  const onFetch = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await fetchMut.mutateAsync({ source, id })
    } catch (err) {
      toast.error(extractError(err, '查询失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="导入"
        description="从 BibTeX/RIS/CSV 解析或通过 DOI/arXiv 查询导入资源。"
      />

      <Tabs defaultValue="parse">
        <TabsList>
          <TabsTrigger value="parse">解析文件</TabsTrigger>
          <TabsTrigger value="fetch">DOI/arXiv 查询</TabsTrigger>
        </TabsList>

        <TabsContent value="parse" className="mt-4 space-y-4">
          <Card>
            <CardContent>
              <form onSubmit={onParse} className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">格式</label>
                  <Select
                    value={format}
                    onValueChange={(v) => setFormat(v as ParseFormat)}
                  >
                    <SelectTrigger className="w-40">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FORMAT_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-muted-foreground">内容</label>
                  <Textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    rows={12}
                    placeholder="粘贴 BibTeX / RIS / CSV 内容…"
                    required
                  />
                </div>
                <Button
                  type="submit"
                  disabled={parseMut.isPending || !content}
                >
                  {parseMut.isPending ? '解析中…' : '解析'}
                </Button>
              </form>
            </CardContent>
          </Card>

          {parseMut.data && (
            <div className="space-y-4">
              {parseMut.data.count > 0 && (
                <p className="text-sm text-muted-foreground">
                  成功解析 {parseMut.data.count} 条
                </p>
              )}
              {parseMut.data.data.map((r, i) => (
                <ResourceCard key={i} resource={r} onSend={sendToSubmissions} />
              ))}
              {parseMut.data.errors.length > 0 && (
                <div className="space-y-2 rounded-md border border-destructive/30 bg-destructive/5 p-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    {parseMut.data.errors.length} 条错误
                  </div>
                  <ul className="space-y-1 text-xs">
                    {parseMut.data.errors.map((er, i) => (
                      <li key={i} className="text-muted-foreground">
                        第 {er.line} 行：{er.error}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </TabsContent>

        <TabsContent value="fetch" className="mt-4 space-y-4">
          <Card>
            <CardContent>
              <form onSubmit={onFetch} className="space-y-4">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <label className="text-xs text-muted-foreground">来源</label>
                    <Select
                      value={source}
                      onValueChange={(v) => setSource(v as FetchSource)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SOURCE_OPTIONS.map((o) => (
                          <SelectItem key={o.value} value={o.value}>
                            {o.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs text-muted-foreground">ID</label>
                    <Input
                      value={id}
                      onChange={(e) => setId(e.target.value)}
                      placeholder="10.1000/xyz123 或 2401.00001"
                      required
                    />
                  </div>
                </div>
                <Button type="submit" disabled={fetchMut.isPending || !id}>
                  {fetchMut.isPending ? '查询中…' : '查询'}
                </Button>
              </form>
            </CardContent>
          </Card>

          {fetchMut.data && (
            <ResourceCard resource={fetchMut.data} onSend={sendToSubmissions} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
