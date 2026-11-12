import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { MoreHorizontal, Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { requireAdminGuard } from '@/lib/route-guards'
import { useAdminUsers, useAssignRole, useCreateAdminUser, useRevokeRole, useSetUserActive, useSetUserAdmin } from '@/hooks/api/use-modules'
import { useAuth } from '@/hooks/use-auth'
import type { AssignableRole, UserResponse } from '@/lib/types'
import { extractError, inferTotalPagesFromFullPage } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { Pagination } from '@/components/common/pagination'
import { EmptyState, ErrorState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const PAGE_SIZE = 50

// 与后端 ASSIGNABLE_ROLES 一致；admin 角色由 is_admin 控制，不在此处。
// 作者/读者是"身份"不是"角色"：读者=注册即得、作者=确认《投稿规范》
// 即得，不由管理员手工分配（2026-11 收窄口径，授权只管编辑线）。
const ASSIGNABLE_ROLES: AssignableRole[] = [
  'chief_editor',
  'deputy_editor',
  'board_editor',
  'reviewer',
  'senior_reviewer',
  'editor',
  'section_editor',
]

const ROLE_LABELS: Record<AssignableRole, string> = {
  chief_editor: '主编',
  deputy_editor: '副主编',
  board_editor: '编委',
  reviewer: '审稿人',
  senior_reviewer: '资深审稿人',
  editor: '编辑',
  section_editor: '栏目编辑',
  author: '作者',
  reader: '读者',
}

export const Route = createFileRoute('/admin/users')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminUsersPage,
})

function AdminUsersPage() {
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({
    email: '',
    username: '',
    role: 'reviewer' as AssignableRole,
    note: '',
  })
  const [createError, setCreateError] = useState('')
  // 受控的「当前展开的那行菜单」。Radix 默认在 onSelect 时立即卸载菜单，
  // 而列表 mutation 又会 invalidate 重拉数据；键盘 Enter/Space 的 keyup
  // 常落在菜单卸载之后，Playwright 判定元素 detached 反复重试（E2E 稳定
  // 复现）。菜单改为动作完成后再关，键盘用户也不会在请求途中失去焦点。
  const [openUserId, setOpenUserId] = useState<number | null>(null)
  // 300ms 防抖：输入每个字母都打一次 /admin/users 会造成请求风暴，
  // 且乱序返回可能让列表"倒退"。防抖后 keystroke 只更新输入框值。
  const [debouncedQuery, setDebouncedQuery] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQuery(query.trim())
      setPage(1)
    }, 300)
    return () => window.clearTimeout(t)
  }, [query])
  const offset = (page - 1) * PAGE_SIZE
  // 服务端过滤：本地过滤只能看到当前这一页，用户超过 50 个后搜不到老账号。
  const { data, isLoading, isError, refetch } = useAdminUsers(PAGE_SIZE, offset, debouncedQuery)
  const setActiveMut = useSetUserActive()
  const setAdminMut = useSetUserAdmin()
  const assignRoleMut = useAssignRole()
  const revokeRoleMut = useRevokeRole()
  const createUserMut = useCreateAdminUser()
  const { user } = useAuth()

  // 后端返回裸数组无 meta，totalPages 用「当前页是否满页」推断（与审计日志页共用）。
  const totalPages = inferTotalPagesFromFullPage(data ?? [], PAGE_SIZE, page)

  // 搜索由服务端完成（分页前过滤）；这里不再二次过滤，
  // 否则「搜到了但被本地条件筛掉」会把结果又变空。
  const filtered = data ?? []

  const onToggleActive = async (u: UserResponse) => {
    try {
      await setActiveMut.mutateAsync({ userId: u.id, isActive: !u.is_active })
      toast.success(u.is_active ? '已禁用' : '已启用')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  // 点击角色 checkbox：已分配→撤销，未分配→分配
  const onToggleRole = async (u: UserResponse, role: AssignableRole) => {
    const has = (u.roles ?? []).includes(role)
    try {
      if (has) {
        await revokeRoleMut.mutateAsync({ userId: u.id, role })
        toast.success(`已撤销 ${ROLE_LABELS[role]} 角色`)
      } else {
        await assignRoleMut.mutateAsync({ userId: u.id, role })
        toast.success(`已分配 ${ROLE_LABELS[role]} 角色`)
      }
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div>
      <PageHeader
        title="用户管理"
        description="管理用户、启用状态与编辑线角色分配。读者身份=注册即得，作者身份=确认《投稿规范》即得，均不在此分配。"
        actions={
          <div className="flex items-center gap-2">
            {data ? <Badge variant="secondary">当前页 {data.length}</Badge> : null}
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              新增人员
            </Button>
          </div>
        }
      />

      <div className="mb-4 max-w-sm">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索用户名或邮箱"
            className="pl-8"
          />
        </div>
      </div>

      {isLoading ? (
        <Loading />
      ) : isError ? (
        <ErrorState message="加载用户失败" onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState title="暂无用户" />
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>用户名</TableHead>
                <TableHead>邮箱</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>管理员</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>邮箱验证</TableHead>
                <TableHead>注册时间</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((u) => {
                // 后端会拒绝自助改 active，前端直接禁用当前 admin 自己那行
                const isSelf = user?.id === u.id
                const roles = u.roles ?? []
                return (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.username}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {u.email}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {roles.length === 0 ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : (
                          roles.map((r) => (
                            <Badge key={r} variant="outline" className="text-xs">
                              {ROLE_LABELS[r as AssignableRole] ?? r}
                            </Badge>
                          ))
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_admin ? 'default' : 'secondary'}>
                        {u.is_admin ? '是' : '否'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? 'default' : 'destructive'}>
                        {u.is_active ? '启用' : '禁用'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_email_verified ? 'default' : 'outline'}>
                        {u.is_email_verified ? '已验证' : '未验证'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(u.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <DropdownMenu
                        open={openUserId === u.id}
                        onOpenChange={(open) => setOpenUserId(open ? u.id : null)}
                      >
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" disabled={isSelf} aria-label="用户操作">
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-48">
                          <DropdownMenuLabel>用户操作</DropdownMenuLabel>
                          <DropdownMenuItem
                            onSelect={(e) => {
                              e.preventDefault()
                              void onToggleActive(u).finally(() => setOpenUserId(null))
                            }}
                            disabled={setActiveMut.isPending}
                          >
                            {u.is_active ? '禁用账号' : '启用账号'}
                          </DropdownMenuItem>
                          {/* 平台管理员提权：此前只能改数据库，界面上无路可走 */}
                          <DropdownMenuItem
                            onSelect={async (e) => {
                              e.preventDefault()
                              try {
                                await setAdminMut.mutateAsync({ userId: u.id, isAdmin: !u.is_admin })
                                toast.success(u.is_admin ? '已取消管理员' : '已设为平台管理员')
                              } catch (err) {
                                toast.error(extractError(err, '操作失败'))
                              } finally {
                                setOpenUserId(null)
                              }
                            }}
                            disabled={setAdminMut.isPending}
                            className={u.is_admin ? 'text-destructive' : ''}
                          >
                            {u.is_admin ? '取消平台管理员' : '设为平台管理员'}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuLabel>编辑线角色分配</DropdownMenuLabel>
                          {ASSIGNABLE_ROLES.map((role) => {
                            const checked = roles.includes(role)
                            const pending =
                              (assignRoleMut.isPending && assignRoleMut.variables?.userId === u.id && assignRoleMut.variables?.role === role) ||
                              (revokeRoleMut.isPending && revokeRoleMut.variables?.userId === u.id && revokeRoleMut.variables?.role === role)
                            return (
                              <DropdownMenuCheckboxItem
                                key={role}
                                checked={checked}
                                disabled={pending}
                                onSelect={(e) => {
                                  e.preventDefault()
                                  void onToggleRole(u, role).finally(() => setOpenUserId(null))
                                }}
                              >
                                {ROLE_LABELS[role]}
                              </DropdownMenuCheckboxItem>
                            )
                          })}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {data && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新增人员</DialogTitle>
            <DialogDescription>
              直接创建编辑部账号并指派角色；对方无需注册，用邮箱验证码登录后即可开始工作。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="create-email">邮箱</Label>
              <Input
                id="create-email"
                type="email"
                value={createForm.email}
                onChange={(e) => setCreateForm((v) => ({ ...v, email: e.target.value }))}
                placeholder="name@example.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="create-username">用户名</Label>
              <Input
                id="create-username"
                value={createForm.username}
                onChange={(e) => setCreateForm((v) => ({ ...v, username: e.target.value }))}
                placeholder="用于登录与署名"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="create-role">角色</Label>
              <select
                id="create-role"
                value={createForm.role}
                onChange={(e) =>
                  setCreateForm((v) => ({ ...v, role: e.target.value as AssignableRole }))
                }
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {ASSIGNABLE_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="create-note">邀请留言（可选）</Label>
              <Textarea
                id="create-note"
                rows={3}
                maxLength={300}
                value={createForm.note}
                onChange={(e) => setCreateForm((v) => ({ ...v, note: e.target.value }))}
                placeholder="例：请负责本期方法学稿件的外审。"
              />
            </div>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button
              disabled={createUserMut.isPending}
              onClick={async () => {
                setCreateError('')
                if (!createForm.email.trim() || !createForm.username.trim()) {
                  setCreateError('邮箱和用户名都必须填写')
                  return
                }
                try {
                  const res = await createUserMut.mutateAsync({
                    email: createForm.email.trim(),
                    username: createForm.username.trim(),
                    role: createForm.role,
                    note: createForm.note.trim(),
                  })
                  if (res.invite_sent) {
                    toast.success('账号已创建，邀请邮件已发送')
                  } else {
                    toast.warning(
                      `账号已创建，但邀请邮件发送失败：${res.invite_error || '请稍后让对方用邮箱验证码登录'}`,
                    )
                  }
                  setCreateOpen(false)
                  setCreateForm({ email: '', username: '', role: 'reviewer', note: '' })
                } catch (err) {
                  setCreateError(extractError(err, '创建失败'))
                }
              }}
            >
              {createUserMut.isPending ? '创建中…' : '创建并邀请'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
