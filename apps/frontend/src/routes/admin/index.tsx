import { createFileRoute, Link } from '@tanstack/react-router'
import {
  ArrowRight,
  CalendarDays,
  ClipboardCheck,
  FileSignature,
  Gavel,
  Layers,
  Megaphone,
  ShieldCheck,
  Users,
} from 'lucide-react'

import { requireAdminGuard } from '@/lib/route-guards'
import { useAuth } from '@/hooks/use-auth'
import { usePendingClaimsCount } from '@/hooks/api/use-modules'
import { PageHeader } from '@/components/common/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export const Route = createFileRoute('/admin/')({
  beforeLoad: () => {
    requireAdminGuard()
  },
  component: AdminDashboard,
})

// 图形化的站点总览（v1.11）：把「塞在侧栏折叠列表」里的管理动作按
// 工作流重新分层——稿件流水线 / 刊出与内容 / 站点治理 三条泳道，
// 每张卡是一个可点击的落点，管理员不用再猜入口在哪个折叠组里。
const WORKFLOWS: { title: string; desc: string; to: string; icon: typeof Gavel }[][] = [
  [
    { title: '编辑工作台', desc: '初筛 · 送审 · 推荐', to: '/submissions/pending', icon: Gavel },
    { title: '审稿工作台', desc: '邀请 · 评审 · 意见', to: '/review/assignments', icon: ClipboardCheck },
    { title: '认领审批', desc: '作者认领存量文章', to: '/admin/claims', icon: FileSignature },
  ],
  [
    { title: '期管理', desc: '组期 · 排期 · 一键刊出', to: '/admin/issues', icon: CalendarDays },
    { title: '卷管理', desc: '卷结构与覆盖范围', to: '/admin/volumes', icon: Layers },
    { title: '公告管理', desc: '首屏公告板', to: '/admin/announcements', icon: Megaphone },
  ],
  [
    { title: '用户管理', desc: '角色 · 状态 · 检索', to: '/admin/users', icon: Users },
    { title: '角色申请', desc: '审稿人/编辑申请审批', to: '/admin/role-applications', icon: ClipboardCheck },
    { title: '审计日志', desc: '全站敏感操作留痕', to: '/admin/audit-logs', icon: ShieldCheck },
  ],
]

const CHAIN = [
  { role: '主编 / 副主编', power: '终审：录用 · 修回 · 拒稿' },
  { role: '编委 / 执行编辑', power: '初筛 · 送审 · 推荐' },
  { role: '审稿人', power: '评审 · 提交意见' },
  { role: '作者', power: '投稿 · 修回 · 认领' },
]

function AdminDashboard() {
  const { user, isAuthenticated } = useAuth()
  const { data: claimsCount } = usePendingClaimsCount(isAuthenticated)
  const pendingCount = claimsCount?.count ?? 0
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader title="站点总览" description={`欢迎，${user?.username ?? '管理员'}。按工作流找入口。`} />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">编辑部职权链</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-4">
          {CHAIN.map((c, i) => (
            <div key={c.role} className="rounded-lg border bg-muted/30 p-3">
              <div className="mb-1 flex items-center gap-2">
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
                  {i + 1}
                </span>
                <span className="text-sm font-medium">{c.role}</span>
              </div>
              <p className="text-xs text-muted-foreground">{c.power}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      {WORKFLOWS.map((lane, i) => (
        <div key={i}>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            {['稿件流水线', '刊出与内容', '站点治理'][i]}
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {lane.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="group rounded-xl border bg-card p-4 shadow-sm transition-shadow hover:shadow-md"
              >
                <div className="mb-2 flex items-center justify-between">
                  <item.icon className="h-5 w-5 text-primary" />
                  {item.to === '/admin/claims' && pendingCount > 0 ? (
                    <Badge variant="destructive" className="ml-auto mr-2">
                      {pendingCount} 待处理
                    </Badge>
                  ) : null}
                  <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1" />
                </div>
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{item.desc}</p>
              </Link>
            ))}
          </div>
        </div>
      ))}

      <p className="text-xs text-muted-foreground">
        <Badge variant="outline" className="mr-1.5 text-[10px]">提示</Badge>
        内容类别的口径与职权链见「等级与规范」页；本页按工作流组织，逐项表单仍在各管理子页。
      </p>
    </div>
  )
}
