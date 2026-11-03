import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Megaphone, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { extractError } from '@/lib/utils'
import { requireAdminGuard } from '@/lib/route-guards'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/admin/announcements')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AnnouncementsAdminPage,
})

interface Announcement {
  id: number
  slug: string
  title: string
  body: string
  level: string
  is_active: boolean
  starts_at: string
  ends_at: string | null
}

interface AnnouncementForm {
  slug: string
  title: string
  body: string
  level: string
  is_active: boolean
  ends_at: string
}

const EMPTY: AnnouncementForm = {
  slug: '',
  title: '',
  body: '',
  level: 'info',
  is_active: true,
  ends_at: '',
}

const LEVEL_LABELS: Record<string, string> = {
  info: '常规',
  success: '喜讯',
  warning: '提醒',
  critical: '重要',
}

/**
 * 公告管理（管理员）。
 *
 * 此前公告只能改数据库——编辑部想发一条「本期已刊出」的提示都得找人
 * 改 SQL。公告是编辑部对外的第一句话，必须由编辑部自己掌握。
 */
function AnnouncementsAdminPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Announcement | null>(null)
  const [form, setForm] = useState<AnnouncementForm>(EMPTY)
  const [open, setOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Announcement | null>(null)

  const listQ = useQuery<Announcement[]>({
    queryKey: ['admin', 'announcements'],
    queryFn: async () => (await api.get<Announcement[]>('/announcements')).data,
  })

  const saveMut = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (editing) {
        return (await api.patch(`/announcements/${editing.id}`, payload)).data
      }
      return (await api.post('/announcements', payload)).data
    },
    onSuccess: () => {
      toast.success(editing ? '公告已更新' : '公告已发布')
      void qc.invalidateQueries({ queryKey: ['admin', 'announcements'] })
      void qc.invalidateQueries({ queryKey: ['announcements'] })
      setOpen(false)
      setEditing(null)
      setForm(EMPTY)
    },
    onError: (err) => toast.error(extractError(err, '保存失败')),
  })

  const deleteMut = useMutation({
    mutationFn: async (id: number) => (await api.delete(`/announcements/${id}`)).data,
    onSuccess: () => {
      toast.success('公告已删除')
      void qc.invalidateQueries({ queryKey: ['admin', 'announcements'] })
      setDeleteTarget(null)
    },
    onError: (err) => toast.error(extractError(err, '删除失败')),
  })

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY)
    setOpen(true)
  }

  const openEdit = (a: Announcement) => {
    setEditing(a)
    setForm({
      slug: a.slug,
      title: a.title,
      body: a.body,
      level: a.level,
      is_active: a.is_active,
      ends_at: a.ends_at ? a.ends_at.slice(0, 16) : '',
    })
    setOpen(true)
  }

  const onSubmit = () => {
    const payload: Record<string, unknown> = {
      slug: form.slug.trim(),
      title: form.title.trim(),
      body: form.body.trim(),
      level: form.level,
      is_active: form.is_active,
      ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null,
    }
    saveMut.mutate(payload)
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="公告管理"
        description="发布首访弹窗公告、活动通知与维护提示。到点自动下线。"
        actions={
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" />
            新建公告
          </Button>
        }
      />

      {listQ.isLoading ? (
        <Loading />
      ) : listQ.isError ? (
        <ErrorState message="加载公告失败" onRetry={() => listQ.refetch()} />
      ) : !listQ.data?.length ? (
        <EmptyState
          title="还没有公告"
          description="新建一条公告，它会在访客首次进入时弹出。"
          action={
            <Button onClick={openCreate} size="sm">
              新建公告
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {listQ.data.map((a) => (
            <Card key={a.id}>
              <CardContent className="flex items-start gap-3 py-4">
                <Megaphone className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{a.title}</p>
                    <Badge variant={a.is_active ? 'default' : 'secondary'}>
                      {a.is_active ? '启用' : '停用'}
                    </Badge>
                    <Badge variant="outline">{LEVEL_LABELS[a.level] ?? a.level}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{a.body}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {new Date(a.starts_at).toLocaleString()}
                    {a.ends_at ? ` → ${new Date(a.ends_at).toLocaleString()}` : '（长期）'}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button variant="ghost" size="icon-sm" onClick={() => openEdit(a)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setDeleteTarget(a)}
                    className="text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑公告' : '新建公告'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="slug">标识（小写字母/数字/横线）</Label>
                <Input
                  id="slug"
                  value={form.slug}
                  onChange={(e) => setForm((p) => ({ ...p, slug: e.target.value }))}
                  placeholder="issue-4-live"
                  disabled={!!editing}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="level">级别</Label>
                <Select
                  value={form.level}
                  onValueChange={(v) => setForm((p) => ({ ...p, level: v }))}
                >
                  <SelectTrigger id="level">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(LEVEL_LABELS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="title">标题</Label>
              <Input
                id="title"
                value={form.title}
                onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                maxLength={200}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="body">正文</Label>
              <Textarea
                id="body"
                value={form.body}
                onChange={(e) => setForm((p) => ({ ...p, body: e.target.value }))}
                rows={7}
                maxLength={20000}
                placeholder="支持换行。读者首次访问时会在弹窗中看到全文。"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="ends">结束时间（留空 = 长期）</Label>
                <Input
                  id="ends"
                  type="datetime-local"
                  value={form.ends_at}
                  onChange={(e) => setForm((p) => ({ ...p, ends_at: e.target.value }))}
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
                    className="h-4 w-4"
                  />
                  立即启用
                </label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              onClick={onSubmit}
              disabled={saveMut.isPending || !form.slug.trim() || !form.title.trim() || !form.body.trim()}
            >
              {saveMut.isPending ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        title="删除公告"
        description={`确定删除「${deleteTarget?.title ?? ''}」？此操作不可撤销。`}
        confirmText="删除"
        destructive
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
      />
    </div>
  )
}
