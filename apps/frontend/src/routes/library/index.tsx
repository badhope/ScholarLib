import { useState } from 'react'
import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { MoreVertical, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { getAuthState } from '@/lib/auth'
import {
  useCreateReadingList,
  useDeleteReadingList,
  useReadingLists,
  useUpdateReadingList,
} from '@/hooks/api/use-modules'
import type { ReadingListResponse, ReadingListUpdate } from '@/lib/types'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { ConfirmDialog } from '@/components/common/confirm-dialog'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/library/')({
  beforeLoad: () => {
    if (!getAuthState().isAuthenticated) throw redirect({ to: '/login' })
  },
  component: LibraryPage,
})

const PAGE_SIZE = 12

interface ListFormState {
  name: string
  description: string
}

function LibraryPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading, isError, refetch } = useReadingLists(page, PAGE_SIZE)
  const createMut = useCreateReadingList()
  const updateMut = useUpdateReadingList()
  const deleteMut = useDeleteReadingList()

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ReadingListResponse | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [form, setForm] = useState<ListFormState>({ name: '', description: '' })

  const openCreate = () => {
    setForm({ name: '', description: '' })
    setCreateOpen(true)
  }

  const openEdit = (list: ReadingListResponse) => {
    setEditTarget(list)
    setForm({
      name: list.name,
      description: list.description ?? '',
    })
  }

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await createMut.mutateAsync({
        name: form.name,
        description: form.description || null,
      })
      toast.success('已创建')
      setCreateOpen(false)
    } catch (err) {
      toast.error(extractError(err, '创建失败'))
    }
  }

  const onEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget) return
    const body: ReadingListUpdate = {
      name: form.name,
      description: form.description || null,
    }
    try {
      await updateMut.mutateAsync({ id: editTarget.id, body })
      toast.success('已更新')
      setEditTarget(null)
    } catch (err) {
      toast.error(extractError(err, '更新失败'))
    }
  }

  const onConfirmDelete = async () => {
    if (deleteId === null) return
    const target = deleteId
    setDeleteId(null)
    try {
      await deleteMut.mutateAsync(target)
      toast.success('已删除')
    } catch (err) {
      toast.error(extractError(err, '删除失败'))
    }
  }

  return (
    <div className="w-full max-w-5xl space-y-6">
      <PageHeader
        title="我的阅读列表"
        description="管理你的私人收藏与阅读清单。"
        actions={
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" />
            新建列表
          </Button>
        }
      />

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载列表失败" onRetry={() => refetch()} />
      ) : !data || data.data.length === 0 ? (
        <EmptyState
          title="暂无阅读列表"
          description="新建你的第一个列表来收藏资源。"
          action={
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4" />
              新建你的第一个列表
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.data.map((list) => (
            <Card key={list.id} className="group">
              <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
                <Link
                  to="/library/$listId"
                  params={{ listId: String(list.id) }}
                  className="flex-1 hover:text-primary"
                >
                  <CardTitle className="text-base">{list.name}</CardTitle>
                </Link>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      aria-label={`列表操作：${list.name}`}
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => openEdit(list)}>
                      <Pencil className="h-4 w-4" />
                      编辑
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => setDeleteId(list.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                      删除
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </CardHeader>
              <CardContent>
                <Link
                  to="/library/$listId"
                  params={{ listId: String(list.id) }}
                  className="block"
                >
                  {list.description ? (
                    <p className="line-clamp-2 min-h-[2.5rem] text-sm text-muted-foreground">
                      {list.description}
                    </p>
                  ) : (
                    <p className="min-h-[2.5rem] text-sm text-muted-foreground/60">
                      暂无描述
                    </p>
                  )}
                  <div className="mt-3 flex items-center gap-2">
                    <Badge variant="secondary">{list.item_count} 条资源</Badge>
                    <span className="text-xs text-muted-foreground">
                      {new Date(list.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          onPageChange={setPage}
        />
      )}

      {/* 新建列表 Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建列表</DialogTitle>
          </DialogHeader>
          <form onSubmit={onCreate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="list-name">名称</Label>
              <Input
                id="list-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如：深度学习必读"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="list-desc">描述（选填）</Label>
              <Textarea
                id="list-desc"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="这个列表用于…"
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                取消
              </Button>
              <Button type="submit" disabled={createMut.isPending}>
                {createMut.isPending ? '创建中…' : '创建'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 编辑列表 Dialog：复用同一 form state，进入时由 openEdit 重置 */}
      <Dialog open={!!editTarget} onOpenChange={(o) => !o && setEditTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>编辑列表</DialogTitle>
          </DialogHeader>
          <form onSubmit={onEdit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-list-name">名称</Label>
              <Input
                id="edit-list-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-list-desc">描述</Label>
              <Textarea
                id="edit-list-desc"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditTarget(null)}
              >
                取消
              </Button>
              <Button type="submit" disabled={updateMut.isPending}>
                {updateMut.isPending ? '保存中…' : '保存'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteId !== null}
        title="删除列表"
        description="确定删除这个阅读列表吗？此操作不可撤销。"
        confirmText="删除"
        destructive
        onConfirm={onConfirmDelete}
        onOpenChange={(o) => !o && setDeleteId(null)}
      />
    </div>
  )
}
