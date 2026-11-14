import { useEffect, useState } from 'react'
import { Link, useLocation } from '@tanstack/react-router'
import { ArrowRight, Compass, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/use-auth'

const KEY = 'rubbish.onboarding.v1'

/** 首次使用手把手引导：可跳过，只在本机显示一次。 */
export function OnboardingTour() {
  const { user, isAuthenticated, isAdmin } = useAuth()
  const isEditor = isAdmin || (user?.roles ?? []).some((r) => ['editor', 'section_editor', 'board_editor', 'deputy_editor', 'chief_editor', 'editor_in_chief'].includes(r))
  const isReviewer = (user?.roles ?? []).some((r) => ['reviewer', 'editor_in_chief'].includes(r))
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const location = useLocation()

  useEffect(() => {
    try { setOpen(localStorage.getItem(KEY) !== 'done') } catch { /* 隐私模式下忽略 */ }
  }, [])

  const close = () => { try { localStorage.setItem(KEY, 'done') } catch { /* ignore */ } setOpen(false) }

  // 不在设置、后台、审稿、投稿这些“正在办事”的页面弹浮层：
  // 用户此刻要看表单和按钮，引导卡不能压住正文。
  const busy = ['/settings', '/admin', '/review', '/editor', '/submissions', '/ingest', '/account']
    .some((prefix) => location.pathname === prefix || location.pathname.startsWith(prefix + '/'))
  if (!open || busy) return null

  const steps = [
    { title: '先看五个入口', body: '顶部固定 首页 / 论文 / 副刊 / 讨论 / 我的；“栏目”已降级为论文筛选与专题索引，不再单独占一级入口。', to: '/papers', label: '去论文' },
    { title: isAuthenticated ? '投稿与进度' : '注册后投稿', body: isAuthenticated ? '在“我的提交”看审稿状态；每篇稿件的操作旁都有说明，遇到决定可提交申诉。' : '注册并登录后可投稿、认领作者位、提交申诉；论文轨会进入正式评审与计分。', to: isAuthenticated ? '/submissions' : '/login', label: isAuthenticated ? '我的提交' : '去登录' },
    ...(isReviewer ? [{ title: '审稿工作台', body: '待审、已审、超期都在工作台；每条操作旁注写明了拒审、延期、提交意见的边界。', to: '/review/assignments', label: '进入审稿' }] : []),
    ...(isEditor ? [{ title: '主编工作台', body: '分派、催办、裁决与申诉待办集中在一处；受理撤回会下架作品，重审分数/分区要写处置说明。', to: '/editor/workbench', label: '进入编辑部' }] : []),
    { title: '遇到问题随时提', body: '分数、分区或撤回问题走“作者申诉”，会进入编辑部待办；站务问题见“常见问题”。', to: '/appeals', label: '作者申诉' },
  ]
  const current = steps[Math.min(step, steps.length - 1)]

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="fixed bottom-[calc(5.2rem+env(safe-area-inset-bottom))] right-4 z-[70] inline-flex items-center gap-1.5 rounded-full border bg-background/95 px-3 py-1.5 text-xs font-medium shadow-md backdrop-blur transition-colors hover:bg-muted"
        aria-label="打开新手指引"
      >
        <Compass className="h-3.5 w-3.5" />
        新手指引
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {step + 1}/{steps.length}
        </span>
      </button>
    )
  }

  return (
    <div className="fixed inset-x-3 bottom-[calc(5.2rem+env(safe-area-inset-bottom))] z-[80] rounded-xl border bg-background p-4 shadow-xl sm:inset-x-auto sm:right-6 sm:bottom-20 sm:w-80">
      <button className="absolute right-3 top-3 text-muted-foreground" onClick={close} aria-label="关闭引导"><X className="h-4 w-4" /></button>
      <p className="text-xs text-muted-foreground">首次使用 · {step + 1}/{steps.length}</p>
      <h3 className="mt-1 text-base font-semibold">{current.title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{current.body}</p>
      <div className="mt-4 flex items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={close}>跳过引导</Button>
        <div className="flex gap-2">
          <Link to={current.to} onClick={close}><Button variant="outline" size="sm">{current.label}</Button></Link>
          {step < steps.length - 1 ? <Button size="sm" onClick={() => setStep(step + 1)}>下一步 <ArrowRight className="h-3.5 w-3.5" /></Button> : <Button size="sm" onClick={close}>开始使用</Button>}
        </div>
      </div>
    </div>
  )
}
