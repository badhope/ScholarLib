import { useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { ChevronLeft, CheckCircle2, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/use-auth'
import { useClaimResource, useClaimStatus, useResource } from '@/hooks/api/use-modules'
import { extractError, formatDateTime, sanitizeAuthors } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState, LoadingSkeleton } from '@/components/common/state'
import type { ClaimEvidenceType } from '@/lib/types'

export const Route = createFileRoute('/claim/$resourceId')({
  component: ClaimPage,
})

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const ORCID_RE = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/

const EVIDENCE_OPTIONS: { value: ClaimEvidenceType; label: string; hint: string }[] = [
  { value: 'email', label: '原稿邮箱', hint: '投稿时使用的邮箱' },
  { value: 'orcid', label: 'ORCID 编号', hint: '0000-000X-XXXX-XXXX' },
  { value: 'manuscript_id', label: '稿件编号', hint: '投稿系统或编辑部邮件中的编号' },
]

function ClaimPage() {
  const { resourceId } = Route.useParams()
  const id = Number(resourceId)
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()

  const { data: resource, isLoading, isError, refetch } = useResource(id)
  const { data: status } = useClaimStatus(id, isAuthenticated)
  const claimMut = useClaimResource()

  const [position, setPosition] = useState<number>(1)
  const [evidenceType, setEvidenceType] = useState<ClaimEvidenceType>('email')
  const [evidenceValue, setEvidenceValue] = useState('')
  const [touched, setTouched] = useState(false)

  if (isLoading) return <LoadingSkeleton rows={6} />
  if (isError || !resource) {
    return <ErrorState message="加载资源失败" onRetry={() => refetch()} />
  }

  const authorCount = resource.authors_detail?.length ?? resource.authors.length
  const cleanAuthors = sanitizeAuthors(resource.authors)

  if (!isAuthenticated) {
    return (
      <div className="mx-auto max-w-[640px]">
        <Link to="/catalog/$resourceId" params={{ resourceId }} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-primary">
          <ChevronLeft className="mr-1 h-4 w-4" />
          返回文章
        </Link>
        <Card>
          <CardContent className="py-10 text-center">
            <AlertCircle className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="mb-2 text-base font-medium">登录后才能认领文章</p>
            <p className="mb-4 text-sm text-muted-foreground">
              认领需要绑定你的站内账号，编辑部审核通过后文章会挂到你名下。
            </p>
            <Button asChild>
              <Link to="/login" search={{ redirect: `/claim/${id}` }}>
                去登录
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (status?.state === 'claimed' || status?.owner) {
    return (
      <div className="mx-auto max-w-[640px]">
        <Link to="/catalog/$resourceId" params={{ resourceId }} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-primary">
          <ChevronLeft className="mr-1 h-4 w-4" />
          返回文章
        </Link>
        <Card>
          <CardContent className="py-10 text-center">
            <CheckCircle2 className="mx-auto mb-3 h-8 w-8 text-green-600" />
            <p className="text-base font-medium">本文已有归属作者</p>
            <p className="mt-1 text-sm text-muted-foreground">
              已绑定到 {status.owner?.username ?? '站内账号'}，无需重复认领。
            </p>
            <Button asChild variant="outline" className="mt-4">
              <Link to="/catalog/$resourceId" params={{ resourceId }}>返回文章</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (status?.mine) {
    const s = status.mine
    const color =
      s.status === 'approved'
        ? 'text-green-600'
        : s.status === 'rejected'
          ? 'text-destructive'
          : 'text-amber-600'
    return (
      <div className="mx-auto max-w-[640px]">
        <Link to="/catalog/$resourceId" params={{ resourceId }} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-primary">
          <ChevronLeft className="mr-1 h-4 w-4" />
          返回文章
        </Link>
        <Card>
          <CardContent className="py-10 text-center">
            <p className={`text-base font-medium ${color}`}>
              {s.status === 'pending' && '认领申请审核中'}
              {s.status === 'approved' && '认领已通过'}
              {s.status === 'rejected' && '认领被驳回'}
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              提交时间：{s.created_at ? formatDateTime(s.created_at) : '—'}
            </p>
            {s.note && (
              <p className="mt-2 rounded-md bg-muted/50 px-3 py-2 text-left text-xs text-muted-foreground">
                编辑部备注：{s.note}
              </p>
            )}
            <Button asChild variant="outline" className="mt-4">
              <Link to="/catalog/$resourceId" params={{ resourceId }}>返回文章</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  let evidenceError = ''
  if (touched) {
    if (!evidenceValue.trim()) evidenceError = '请填写认领依据'
    else if (evidenceType === 'email' && !EMAIL_RE.test(evidenceValue.trim()))
      evidenceError = '邮箱格式不正确'
    else if (evidenceType === 'orcid' && !ORCID_RE.test(evidenceValue.trim()))
      evidenceError = 'ORCID 格式应为 0000-0000-0000-0000'
  }

  const onSubmit = async () => {
    setTouched(true)
    if (evidenceError) return
    try {
      await claimMut.mutateAsync({
        resourceId: id,
        body: {
          author_position: position,
          evidence_type: evidenceType,
          evidence_value: evidenceValue.trim(),
        },
      })
      toast.success('已提交，等待编辑部审核')
      void navigate({ to: '/catalog/$resourceId', params: { resourceId } })
    } catch (err) {
      toast.error(extractError(err, '提交失败'))
    }
  }

  return (
    <div className="mx-auto max-w-[640px] py-6">
      <Link to="/catalog/$resourceId" params={{ resourceId }} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-primary">
        <ChevronLeft className="mr-1 h-4 w-4" />
        返回文章
      </Link>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">认领本文</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="font-medium leading-snug">{resource.title}</p>
          <p className="text-xs text-muted-foreground">
            现有署名：{cleanAuthors.join('、') || '（未署名）'}
          </p>
          <p className="text-xs text-muted-foreground">
            发布时间：{resource.created_at ? formatDateTime(resource.created_at) : '—'}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">认领信息</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label>我是第几作者</Label>
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: Math.max(1, authorCount) }, (_, i) => i + 1).map((n) => (
                <Badge
                  key={n}
                  variant={position === n ? 'default' : 'outline'}
                  className="cursor-pointer px-3 py-1"
                  onClick={() => setPosition(n)}
                >
                  第 {n} 作者
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              按稿件署名顺序选择（共 {authorCount} 位作者）。
            </p>
          </div>

          <div className="space-y-2">
            <Label>认领依据（三选一）</Label>
            <div className="flex flex-col gap-2">
              {EVIDENCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setEvidenceType(opt.value)}
                  className={
                    'flex items-start gap-2 rounded-md border p-2 text-left text-sm ' +
                    (evidenceType === opt.value
                      ? 'border-primary bg-primary/5'
                      : 'hover:bg-muted/50')
                  }
                >
                  <span className={'mt-1 h-3.5 w-3.5 shrink-0 rounded-full border ' + (evidenceType === opt.value ? 'border-primary bg-primary' : 'border-muted-foreground')} />
                  <span>
                    <span className="block font-medium">{opt.label}</span>
                    <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="evidence">
              {evidenceType === 'email' && '原稿邮箱'}
              {evidenceType === 'orcid' && 'ORCID'}
              {evidenceType === 'manuscript_id' && '稿件编号'}
            </Label>
            {evidenceType === 'manuscript_id' ? (
              <Textarea
                id="evidence"
                rows={2}
                value={evidenceValue}
                onChange={(e) => setEvidenceValue(e.target.value)}
                placeholder="例：rubbish-2026-0312"
              />
            ) : (
              <Input
                id="evidence"
                value={evidenceValue}
                onChange={(e) => setEvidenceValue(e.target.value)}
                placeholder={evidenceType === 'email' ? 'you@university.edu' : '0000-0001-2345-6789'}
              />
            )}
            {touched && evidenceError && (
              <p className="text-xs text-destructive">{evidenceError}</p>
            )}
          </div>

          <Button onClick={() => void onSubmit()} disabled={claimMut.isPending} className="w-full">
            {claimMut.isPending ? '提交中…' : '提交认领申请'}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            提交后编辑部会在 3–5 个工作日内审核；通过后文章将挂到你的账号名下。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
