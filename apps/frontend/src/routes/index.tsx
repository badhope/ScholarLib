import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { AnimatePresence, motion, MotionConfig, type Variants } from 'motion/react'
import { useInViewReveal } from '@/hooks/use-in-view-reveal'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  ArrowRight,
  ArrowUp,
  CalendarDays,
  CheckCircle2,
  FileText,
  Globe2,
  Archive,
  LogIn,
  Mail,
  MessageCircle,
  PenLine,
  Search,
  ShieldCheck,
} from 'lucide-react'
import '@fontsource-variable/playfair-display'
import { useAuth } from '@/hooks/use-auth'
import {
  useCatalogStats,
  useIssuePlan,
  useJournalMetrics,
  useResources,
} from '@/hooks/api/use-modules'
import { ArticleCover } from '@/components/common/article-cover'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ThemeToggle } from '@/components/theme-toggle'
import { EmptyState, ErrorState } from '@/components/common/state'
import {
  AnnouncementChip,
  AnnouncementDialog,
  useAnnouncementPortal,
} from '@/components/common/announcement-dialog'
import { BrandMark } from '@/components/common/brand-mark'
import { HeroBackdrop } from '@/components/common/hero-backdrop'

import { issueTitle } from '@/lib/issue-meta'
import { DISCIPLINE_STYLE, DEFAULT_DISCIPLINE_STYLE } from '@/lib/discipline-style'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/')({
  component: HomePage,
})

// 期刊门面首页（对访客的"官网"）：报头 + 打字机口号 + 数据卡 + 当期条 +
// 最新发表卡片 + 「了解本刊」标签页（投稿指南 / 征稿范围 / 开放获取 / 关于与社区）
// + FAQ + 页脚。
// 信息架构基准：Nature/Science 式期刊首页是"枢纽"而非"文档" —— 次级内容
// 收进标签页与专页链接，首屏只保留身份、数据与最新发表；完整细则在
// /authors、/journal-metrics、/about 等专页，不与首页重复铺陈。
// 设计基准：展示级衬线大字、留白代替分隔线、卡片化组件、滚动渐入与数字滚动
// 动效。MotionConfig reducedMotion="user" + 打字机/CountUp 内部尊重
// prefers-reduced-motion。

const DISPLAY_FONT =
  "'Playfair Display Variable', Georgia, 'Noto Serif SC Variable', 'Noto Serif SC', 'DejaVu Serif', serif"

const TYPEWRITER_PHRASES = [
  '投稿 · 同行评审 · 开放出版',
  '让每一篇经过评审的研究被世界看见',
  'Open Access · No Paywall · No Embargo',
  '匿名评审 · 版本留痕 · 全文免费',
]

const DEPARTMENTS = [
  { name: '信息科学', note: '数据治理、信息安全、信息系统' },
  { name: '计算机科学', note: '软件工程、人机交互、机器学习' },
  { name: '图书情报', note: '开放科学、学术传播、文献计量' },
  { name: '交叉研究', note: '方法、工具与跨学科实践' },
]

const REVIEW_STEPS = [
  { title: '投稿与初检', detail: '作者在线提交稿件并上传 PDF；编辑部检查格式、范围与完整性。' },
  { title: '分配审稿人', detail: '编辑按学科匹配审稿人，可选择单盲或双盲评审。' },
  { title: '同行评审', detail: '审稿人在浏览器内阅读全文，提交评分、意见与录用建议。' },
  { title: '编辑裁决', detail: '编辑综合意见给出录用、小修、大修或拒稿决定，全程留痕。' },
  { title: '刊前整理与发布', detail: '录用稿件经刊前整理后进入当期目录，全文免费开放，支持引用导出。' },
]

const FAQ = [
  {
    q: '如何投稿？',
    a: '注册并登录后进入「我的投稿」，点击「新建投稿」填写题录信息并上传 PDF。保存后可随时上传新版本，历史版本会保留快照。',
  },
  {
    q: '稿件可以是英文吗？',
    a: '可以。本刊接受中文与英文稿件；题录中的语言字段会如实标注，目录检索与引用导出都按该字段展示。',
  },
  {
    q: '审稿是单盲还是双盲？',
    a: '两种都支持，由编辑根据稿件情况选择。双盲评审时，审稿人看到的稿件会隐藏作者身份，编辑可另行提供匿名稿。',
  },
  {
    q: '录用后多久能上线？',
    a: '编辑裁决为「录用」后，稿件经刊前整理即进入公开目录并开放全文。你可以在投稿详情里看到每一步的状态与时间。',
  },
  {
    q: '如何引用本刊文章？',
    a: '文章详情页提供引用导出，目录页勾选多条后可批量导出 BibTeX、RIS、CSV 或 JSON；图书馆与索引系统可通过 OAI-PMH 接口收割元数据。',
  },
  {
    q: '忘记密码怎么办？',
    a: '当前站点尚未开通邮件服务，自助重置不可用。请使用注册邮箱联系编辑部 admin@argjiemi.cn，由管理员协助重置。',
  },
]

// 入场动效：左右滑入 + 淡入上移。
// 关键约束（0.7.1 事故复盘的延续）：初始 opacity 不低于 0.3，
// 保证打印/截图/未触发/省电模式下内容仍可读；位移量克制（≤28px），
// 避免大幅滑动造成视觉抖动。
const EASE_OUT = [0.22, 1, 0.36, 1] as const

const rise: Variants = {
  hidden: { opacity: 0.3, y: 24 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, duration: 0.62, ease: EASE_OUT },
  }),
}

const slideInLeft: Variants = {
  hidden: { opacity: 0.3, x: -28 },
  show: { opacity: 1, x: 0, transition: { duration: 0.7, ease: EASE_OUT } },
}

const slideInRight: Variants = {
  hidden: { opacity: 0.3, x: 28 },
  show: { opacity: 1, x: 0, transition: { duration: 0.7, ease: EASE_OUT } },
}

const cardsWrap: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.05 } },
}

const card: Variants = {
  hidden: { opacity: 0.3, y: 18, scale: 0.985 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.5, ease: EASE_OUT },
  },
}

function fmtDate(iso: string): string {
  // 本地时区取日期：toISOString() 是 UTC，东八区晚间发布的文章会被
  // 显示成前一天（用户实测过的"日期不对"来源之一）。
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 打字机：轮播短语，尊重系统减弱动效（直接显示第一条，无动画）。 */
function useTypewriter(phrases: string[]): string {
  // 首帧直接给完整句子：原实现从空字符串开始逐字打，慢网/首屏截图会
  // 只看到“让每一篇经…”，读者以为标题被截断。
  const [text, setText] = useState(() => phrases[0])
  const [idx, setIdx] = useState(0)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const full = phrases[idx % phrases.length]
    // 所有状态迁移都走 setTimeout（含 0ms），避免在 effect 内同步 setState。
    if (!deleting && text === full) {
      const t = setTimeout(() => setDeleting(true), 1700)
      return () => clearTimeout(t)
    }
    if (deleting && text === '') {
      const t = setTimeout(() => {
        setDeleting(false)
        setIdx((v) => (v + 1) % phrases.length)
      }, 0)
      return () => clearTimeout(t)
    }
    const t = setTimeout(
      () => setText(deleting ? full.slice(0, text.length - 1) : full.slice(0, text.length + 1)),
      deleting ? 38 : 95,
    )
    return () => clearTimeout(t)
  }, [text, deleting, idx, phrases])

  return text
}

/** 数字滚动：进入视口后从 0 缓动到目标；减弱动效时首帧直接到位。 */
function CountUpNumber({ target, suffix = '' }: { target: number; suffix?: string }) {
  // 首页数字是“刊面事实”，不是装饰动画。原实现用 framer-motion 的
  // onViewportEnter 触发 0→target 的计数：桌面端首屏未进入判定、或截图/
  // 慢网下动画未完成时，页面上会长时间显示 0（读者第一眼以为站点没内容）。
  // 改成挂载即显示真值，数字本身仍然 tabular-nums，不做滚动动画。
  return (
    <span className="tabular-nums">
      {target}
      {suffix}
    </span>
  )
}

function SectionHeading({
  label,
  title,
  action,
}: {
  label: string
  title: string
  action?: ReactNode
}) {
  return (
    <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.28em] text-primary">
          <span aria-hidden className="h-1.5 w-1.5 rotate-45 bg-primary" />
          {label}
        </p>
        <h2 className="mt-2 text-2xl sm:text-3xl" style={{ fontFamily: DISPLAY_FONT }}>
          {title}
        </h2>
      </div>
      {action}
    </div>
  )
}

/** 当期条：一行看懂"最新一期是什么、去哪读"。Nature 式首页的当期入口。 */
function CurrentIssueBar() {
  const plan = useIssuePlan()
  const live = (plan.data?.entries ?? []).filter((e) => e.state === 'live')
  const current = live[live.length - 1]
  if (!current) return null

  return (
    <div className="border-y bg-card/50">
      <motion.div
        variants={rise}
        custom={5}
        className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6"
      >
        <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <span className="font-medium">第 {current.volume} 卷 第 {current.issue} 期</span>
          <span className="truncate text-muted-foreground">《{issueTitle(current.issue)}》</span>
          <Badge variant="outline" className="tabular-nums">
            {current.published} 篇已上线
          </Badge>
        </p>
        <Link
          to="/archive"
          className="ml-auto inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary transition-colors hover:underline"
        >
          本期目录 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </motion.div>
    </div>
  )
}

function ContactStrip() {
  const [copied, setCopied] = useState(false)
  const copyGroup = async () => {
    try {
      await navigator.clipboard.writeText('1084870548')
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      // 浏览器禁用剪贴板时退回选中文本，用户仍可手动复制。
      window.prompt('复制 QQ 群号', '1084870548')
    }
  }
  return (
    <div className="border-b bg-primary/5">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-4 py-3 sm:flex-wrap sm:gap-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <MessageCircle aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">读者与作者 QQ 群</p>
            <p className="hidden text-xs text-muted-foreground sm:block">
              投稿、审稿、格式问题都可以在群里直接问编辑部；不方便加群就用右下角「有问题」。
            </p>
          </div>
        </div>
        <>
          <a
            href="mqqapi://card/show_pslcard?src_type=internal&version=1&uin=1084870548&card_type=group&source=external"
            target="_blank"
            rel="noopener noreferrer"
            title="手机 QQ 可直接打开"
            className="inline-flex shrink-0 items-center gap-1 rounded-full border border-primary/30 bg-card px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground sm:hidden"
          >
            打开 QQ 群
            <ArrowRight className="h-3.5 w-3.5" />
          </a>
          <button
            type="button"
            onClick={() => void copyGroup()}
            className="hidden shrink-0 items-center gap-1 rounded-full border border-primary/30 bg-card px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground sm:inline-flex sm:gap-1.5 sm:px-4 sm:py-2 sm:text-sm"
            title="复制群号后在 QQ 里搜索加入"
          >
            {copied ? '已复制群号' : '复制群号 1084870548'}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </>
      </div>
    </div>
  )
}

/**
 * 「了解本刊」标签页：投稿指南 / 征稿范围 / 开放获取 / 关于与社区。
 * 次级内容按需展开 —— 用户想看哪个栏目就看哪个，完整细则
 * 通过「查看完整…」链到对应专页，首页不再整页铺陈。
 */
function DiscoverTabs({
  isAuthenticated,
  revealed,
}: {
  isAuthenticated: boolean
  revealed: boolean
}) {
  const submitCta = isAuthenticated ? '/submissions' : '/register'
  return (
    <Tabs defaultValue="guide" className="gap-8">
      <TabsList className="h-auto w-full flex-wrap justify-start gap-1 rounded-lg bg-muted/60 p-1">
        <TabsTrigger value="guide" className="px-4 py-2 text-sm">
          投稿指南
        </TabsTrigger>
        <TabsTrigger value="scope" className="px-4 py-2 text-sm">
          征稿范围
        </TabsTrigger>
        <TabsTrigger value="access" className="px-4 py-2 text-sm">
          开放获取
        </TabsTrigger>
        <TabsTrigger value="about" className="px-4 py-2 text-sm">
          关于与社区
        </TabsTrigger>
      </TabsList>

      {/* ── 投稿指南：五步流程 + 完整规范入口 ── */}
      <TabsContent value="guide" className="mt-8">
        <motion.div
          variants={cardsWrap}
          initial="hidden"
          animate={revealed ? 'show' : 'hidden'}
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5"
        >
          {REVIEW_STEPS.map((step, i) => (
            <motion.div
              key={step.title}
              variants={card}
              whileHover={{ y: -4 }}
              className="relative rounded-lg border bg-card p-5 shadow-sm transition-colors hover:border-primary/40"
            >
              <span
                aria-hidden
                className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-sm text-primary-foreground"
                style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}
              >
                {i + 1}
              </span>
              <h3 className="mt-4 text-base" style={{ fontFamily: DISPLAY_FONT }}>
                {step.title}
              </h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{step.detail}</p>
            </motion.div>
          ))}
        </motion.div>
        <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            审稿人身份与稿件内容按角色隔离；每次裁决与版本变更都写入审计日志。
          </p>
          <div className="flex flex-wrap gap-3">
            <Button asChild>
              <Link to={submitCta}>
                <PenLine className="h-4 w-4" />
                {isAuthenticated ? '进入我的投稿' : '免费注册投稿'}
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/authors">
                完整投稿规范 <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </TabsContent>

      {/* ── 征稿范围：宗旨 + 收录类型 + 学科方向 ── */}
      <TabsContent value="scope" className="mt-8">
        <div className="grid gap-10 lg:grid-cols-[1fr_360px]">
          <div>
            <p className="text-xl leading-relaxed sm:text-2xl" style={{ fontFamily: DISPLAY_FONT }}>
              关注学术出版与知识基础设施的工程实践与实证研究——从写作、评审、发布到长期保存。
            </p>
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground sm:text-base">
              既欢迎严格的方法学研究，也欢迎可复现的工具、数据集与案例报告。投稿须为未公开发表的原创工作，引用与数据来源需完整标注；涉及人类受试者的研究须提供伦理审查说明。
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              {[
                '原创研究论文',
                '方法综述',
                '可复现工具与系统',
                '数据集',
                '开放科学研究',
                '教学案例与教程',
              ].map((item) => (
                <span
                  key={item}
                  className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-xs transition-colors hover:border-primary/40"
                >
                  <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-primary" />
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div className="grid gap-3 self-start sm:grid-cols-2 lg:grid-cols-1">
            {DEPARTMENTS.map((d) => (
              <div
                key={d.name}
                className="group relative overflow-hidden rounded-lg border bg-card p-4 shadow-sm transition-colors hover:border-primary/40"
              >
                <span
                  aria-hidden
                  className="absolute inset-y-0 left-0 w-0.5 bg-primary/70 transition-colors group-hover:bg-primary"
                />
                <p className="text-sm font-medium">{d.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">{d.note}</p>
              </div>
            ))}
          </div>
        </div>
      </TabsContent>

      {/* ── 开放获取：三张承诺卡 + 机读接口 ── */}
      <TabsContent value="access" className="mt-8">
        <div className="grid gap-5 md:grid-cols-3">
          {[
            {
              icon: Globe2,
              title: '全文免费',
              copy: '所有已发表文章免费阅读与下载，没有订阅墙，也不需要机构账号。读者可以直接在浏览器内阅读全文。',
            },
            {
              icon: Archive,
              title: '版本留痕',
              copy: '每次投稿修订都保存版本快照，录用与裁决记录可追溯，方便引用与学术史核查。',
            },
            {
              icon: FileText,
              title: '可被索引',
              copy: '提供 OAI-PMH 2.0 元数据接口与站点地图，图书馆、DOAJ 等索引系统可直接收割题录与全文链接。',
            },
          ].map((f) => (
            <div
              key={f.title}
              className="rounded-lg border bg-card p-6 shadow-sm transition-colors hover:border-primary/40"
            >
              <span
                aria-hidden
                className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10 text-primary"
              >
                <f.icon className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-lg" style={{ fontFamily: DISPLAY_FONT }}>
                {f.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{f.copy}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 text-xs text-muted-foreground">
          接口：
          <code className="mx-1 rounded bg-muted px-1.5 py-0.5 font-mono">/oai?verb=Identify</code>
          站点地图：
          <a className="mx-1 text-primary hover:underline" href="/sitemap.xml">
            /sitemap.xml
          </a>
        </p>
      </TabsContent>

      {/* ── 关于与社区：编辑部引言 + 参与方式 + 联系方式 ── */}
      <TabsContent value="about" className="mt-8">
        <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
          <div>
            <blockquote className="relative rounded-lg border bg-card p-6 shadow-sm">
              <span
                aria-hidden
                className="absolute left-5 top-3 text-6xl leading-none text-primary/25"
                style={{ fontFamily: DISPLAY_FONT }}
              >
                “
              </span>
              <p className="relative pl-8 text-lg leading-relaxed" style={{ fontFamily: DISPLAY_FONT }}>
                可信的知识不应该有围墙。每一篇经过严格评审的研究，都值得被世界看见。
              </p>
              <footer className="mt-3 pl-8 text-xs text-muted-foreground">—— Rubbish 编辑部</footer>
            </blockquote>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              {[
                {
                  title: '评论互动',
                  body: '对每篇论文公开发表质疑、补充与吐槽——像审稿人一样较真。',
                },
                {
                  title: '进度跨设备同步',
                  body: '阅读进度、收藏与关注随账号走：换设备接着读，书架不会丢。',
                },
                {
                  title: '投稿开放',
                  body: '注册即可投稿。论文轨再分学术论文与荒诞论文，统一走百分制评审；副刊轨不用论文体，只做格式与合规检查，不计分。无需申请、无需介绍信。',
                },
                {
                  title: '读者活动',
                  body: '年度 Rubbish Prize 读者票选、评论区精选、新刊试读。',
                },
              ].map((f) => (
                <div key={f.title} className="rounded-lg border bg-card p-4 shadow-sm">
                  <h3 className="text-sm font-medium">{f.title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{f.body}</p>
                </div>
              ))}
            </div>
            {!isAuthenticated && (
              <div className="mt-6">
                <Button asChild size="lg" className="button-shine">
                  <Link to="/register">免费注册，参与社区</Link>
                </Button>
                <p className="mt-2 text-xs text-muted-foreground">
                  已有账号？
                  <Link to="/login" className="text-primary hover:underline">
                    直接登录
                  </Link>
                  ·注册不需要邮箱验证
                </p>
              </div>
            )}
          </div>
          <div className="relative h-fit overflow-hidden rounded-lg border bg-card p-6 shadow-sm">
            <span
              aria-hidden
              className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-primary/60 to-transparent"
            />
            <h3 className="text-lg" style={{ fontFamily: DISPLAY_FONT }}>
              联系编辑部
            </h3>
            <p className="mt-3 flex items-center gap-2 text-sm">
              <Mail aria-hidden className="h-4 w-4 text-muted-foreground" />
              <a href="mailto:admin@argjiemi.cn" className="text-primary hover:underline">
                admin@argjiemi.cn
              </a>
            </p>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              投稿、审稿、账号与数据相关事宜均可来信；请在邮件中注明稿件编号或注册邮箱。
            </p>
            <ul className="mt-4 space-y-1.5 text-xs text-muted-foreground">
              <li>
                <Link to="/authors" className="hover:text-foreground hover:underline">
                  作者指南与收录标准
                </Link>
              </li>
              <li>
                <Link to="/policies" className="hover:text-foreground hover:underline">
                  期刊政策与社区规范
                </Link>
              </li>
              <li>
                <Link to="/about" search={{ tab: 'about' }} className="hover:text-foreground hover:underline">
                  关于本刊与编委会
                </Link>
              </li>
              <li>
                <Link to="/journal-metrics" className="hover:text-foreground hover:underline">
                  期刊指标与 R 因子
                </Link>
              </li>
              <li>
                <a href="/help" className="hover:text-foreground hover:underline">
                  使用帮助
                </a>
              </li>
              <li>
                <a href="/privacy" className="hover:text-foreground hover:underline">
                  隐私政策
                </a>
              </li>
            </ul>
          </div>
        </div>
      </TabsContent>
    </Tabs>
  )
}

/** 首页社区脉搏：把“正在讨论”搬到首页，给论坛一个不靠用户主动点 tab 的入口。 */
function ForumPulse() {
  const q = useQuery({
    queryKey: ['home', 'forum-pulse'],
    queryFn: async () =>
      (await api.get('/forum/topics', { params: { page_size: 5 } })).data,
  })
  const topics = (q.data?.data ?? []) as Array<{
    id: number
    title: string
    category: string
    reply_count: number
    last_reply_at: string | null
    author: { username: string } | null
  }>
  if (topics.length === 0) return null

  const label: Record<string, string> = {
    paper: '论文沙龙',
    method: '方法与写作',
    life: '学术生存',
    collab: '组队招募',
    meta: '站务公告',
    notice: '公告',
    discussion: '论文沙龙',
    question: '方法与写作',
    suggestion: '站务公告',
  }
  const rel = (iso: string | null) => {
    if (!iso) return ''
    const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
    if (m < 60) return `${Math.max(1, m)} 分钟前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h} 小时前`
    return `${Math.floor(h / 24)} 天前`
  }

  return (
    <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <SectionHeading
        label="Community"
        title="正在讨论"
        action={
          <Link to="/forum" className="text-sm text-muted-foreground hover:text-primary">
            进入讨论 →
          </Link>
        }
      />
      <div className="divide-y overflow-hidden rounded-xl border bg-card">
        {topics.map((t) => (
          <Link
            key={t.id}
            to="/forum/$topicId"
            params={{ topicId: String(t.id) }}
            className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/50"
          >
            <Badge variant="outline" className="mt-0.5 shrink-0">
              {label[t.category] ?? t.category}
            </Badge>
            <span className="min-w-0 flex-1">
              <span className="line-clamp-1 text-sm font-medium">{t.title}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {t.author?.username ?? '匿名'} · {t.reply_count} 回复
                {t.last_reply_at ? ` · 最后活跃 ${rel(t.last_reply_at)}` : ''}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

function HomePage() {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const typed = useTypewriter(TYPEWRITER_PHRASES)
  const { data, isLoading, isError, refetch } = useResources({
    track: 'paper',
    page: 1,
    page_size: 6,
    sort: 'created_at',
    order: 'desc',
  })
  const { data: stats, isLoading: statsLoading } = useCatalogStats('paper')
  const { data: funStats } = useCatalogStats('essay')
  const { data: metrics } = useJournalMetrics()

  // 公告：自动弹出 + 顶栏重开入口共用一份状态
  const notice = useAnnouncementPortal()

  const resources = data?.data ?? []
  const paperTotal = stats?.by_type?.paper ?? 0
  const seriousTotal = stats?.by_paper_kind?.serious ?? 0
  const absurdTotal = stats?.by_paper_kind?.absurd ?? 0
  const funTotal = funStats?.total ?? 0
  const disciplines = stats ? Object.keys(stats.by_discipline).length : 0
  // 分类入口数据：按篇数降序，点击直达 /catalog?discipline=…（跳转式导航）
  const disciplineEntries = Object.entries(stats?.by_discipline ?? {}).sort(
    (a, b) => b[1] - a[1],
  )
  // P0 后风格光谱分数不再作为期刊门面统计：全局均值/中位数整块下线，
  // 学术稿文章页也不再对外展示该分数；首页四张卡只回答"这本刊在做什么"。

  // 滚动入场：motion 14.5.0 的 whileInView 在本项目不触发（线上同样复现），
  // 改由原生 IntersectionObserver 驱动 animate；容器保留原本的 stagger variants。
  const [statsRevealRef, statsReveal] = useInViewReveal()
  const [revealLatestRef, revealLatest] = useInViewReveal()
  const [revealDiscoverRef, revealDiscover] = useInViewReveal()
  const [revealFaqRef, revealFaq] = useInViewReveal()

  // 返回顶部按钮：滚过首屏后出现
  const [showTop, setShowTop] = useState(false)
  useEffect(() => {
    const onScroll = () => setShowTop(window.scrollY > 720)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const onSearch = (e: FormEvent) => {
    e.preventDefault()
    const q = query.trim()
    void navigate({ to: '/catalog', search: q ? { q } : {} })
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen bg-background text-foreground">
        {/* ── 公告弹窗：未读自动弹出，顶栏按钮随时重开 ── */}
        {notice.announcement && (
          <AnnouncementDialog
            announcement={notice.announcement}
            open={notice.open}
            onOpenChange={notice.onOpenChange}
          />
        )}

        {/* ── 顶部细条：身份 + 公告 + 账号入口（<header> 即 banner 地标） ── */}
        <header className="bg-muted/40">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-1.5 text-xs text-muted-foreground sm:px-6">
            <span className="tracking-wide">An Open Access Journal · 开放获取期刊</span>
            <div className="flex items-center gap-3">
              <AnnouncementChip
                announcement={notice.announcement}
                seen={notice.seen}
                onOpen={() => notice.setOpen(true)}
              />
              {isAuthenticated ? (
                <Link
                  to="/dashboard"
                  className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                >
                  进入工作台 <ArrowRight className="h-3 w-3" />
                </Link>
              ) : (
                <>
                  <Link
                    to="/login"
                    className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                  >
                    <LogIn className="h-3 w-3" /> 登录
                  </Link>
                  <Link to="/register" className="transition-colors hover:text-foreground">
                    注册
                  </Link>
                </>
              )}
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* ── 刊头 Hero：展示级衬线大字 + 打字机口号 + 数据卡 ── */}
        <motion.section
          initial="hidden"
          animate="show"
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.1 } } }}
          className="relative overflow-hidden"
        >
          {/* 背景装饰：柔光渐晕 + 细点阵，纯 CSS，无图片 */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_0%,rgba(22,50,79,0.08),transparent_70%)] dark:bg-[radial-gradient(60%_50%_at_50%_0%,rgba(199,162,75,0.10),transparent_70%)]"
          />
          <HeroBackdrop />

          <div className="relative mx-auto max-w-6xl px-4 pb-12 pt-8 text-center sm:px-6 sm:pt-20">
            <motion.p
              variants={rise}
              custom={0}
              className="flex items-center justify-center gap-2 text-[11px] uppercase tracking-[0.35em] text-muted-foreground"
            >
              <span aria-hidden className="h-1.5 w-1.5 rotate-45 bg-primary" />
              Open Access · Peer Reviewed
              <span aria-hidden className="h-1.5 w-1.5 rotate-45 bg-primary" />
            </motion.p>

            <motion.h1
              variants={slideInLeft}
              className="mt-5 flex flex-wrap items-center justify-center gap-3 sm:flex-nowrap sm:gap-6"
            >
              {/* 刊头回收标志：源自创刊 PDF 原图，随主题色（品牌绿） */}
              <BrandMark
                decorative
                className="h-11 w-11 shrink-0 text-primary sm:h-24 sm:w-24"
              />
              <span
                className="hero-title whitespace-nowrap text-5xl leading-none tracking-tight sm:text-9xl"
                style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}
              >
                Rubbish
              </span>
            </motion.h1>

            {/* 打字机口号：固定两行高度 + 移动端降字号。
                之前只有 min-h-7，长句在 390px 上换行→高度跳变，
                每打一个字整页就抖一下（用户实测的「页面抖动」来源之一）。 */}
            <motion.p
              variants={slideInRight}
              className="mx-auto mt-5 flex h-14 max-w-[22rem] items-center justify-center px-2 text-sm leading-snug text-muted-foreground sm:h-8 sm:max-w-none sm:text-lg"
            >
              <span className="mr-1 line-clamp-2" style={{ fontFamily: DISPLAY_FONT }}>
                {typed}
              </span>
              <span
                aria-hidden
                className="inline-block h-4 w-[2px] shrink-0 animate-pulse bg-primary sm:h-6"
              />
            </motion.p>

            <motion.p
              variants={rise}
              custom={3}
              className="mt-3 text-xs text-muted-foreground/80"
            >
              ISSN 申请中
            </motion.p>

            <motion.div
              variants={rise}
              custom={4}
              className="mt-7 flex flex-wrap items-center justify-center gap-3"
            >
              {isAuthenticated ? (
                <Button asChild size="lg" className="button-shine">
                  <Link to="/submissions">
                    <PenLine className="h-4 w-4" /> 提交稿件
                  </Link>
                </Button>
              ) : (
                <Button asChild size="lg" className="button-shine">
                  <Link to="/register">
                    <PenLine className="h-4 w-4" /> 免费注册投稿
                  </Link>
                </Button>
              )}
              <Button asChild size="lg" variant="outline">
                <Link to="/catalog">
                  浏览全部目录 <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </motion.div>

            {/* 数据卡：进入视口数字滚动 */}
            <motion.div
              ref={statsRevealRef}
              variants={cardsWrap}
              initial="hidden"
              animate={statsReveal ? 'show' : 'hidden'}
              className="mx-auto mt-6 grid max-w-4xl grid-cols-2 gap-2.5 sm:mt-12 sm:gap-4 lg:grid-cols-4"
            >
              {[
                // 四项都必须回答读者/作者真正关心的问题：
                // 有多少可读、覆盖多广、是否付费、审稿要多久。
                // 「累计阅读」这种虚荣指标留给后台看，不放在期刊门面。
                {
                  label: '已刊论文',
                  node: (
                    <span className="inline-flex flex-col items-start">
                      <CountUpNumber target={paperTotal} />
                      <span className="mt-1 text-[10px] font-normal tracking-normal text-muted-foreground sm:text-xs">
                        学术 {seriousTotal} · 荒诞 {absurdTotal}
                      </span>
                    </span>
                  ),
                },
                { label: '覆盖学科', node: <CountUpNumber target={disciplines} /> },
                {
                  label: '开放获取',
                  node:
                    metrics?.open_access_rate != null ? (
                      <span className="tabular-nums">{metrics.open_access_rate.toFixed(0)}%</span>
                    ) : (
                      <span className="text-base text-muted-foreground">全部</span>
                    ),
                },
                {
                  label: '平均处理天数',
                  node:
                    // 0 天不是「很快」，是「还没有完成的评审」：旧逻辑把 0 也
                    // 渲染成「0 天」，门面上等于自曝一份没人审过的刊物。
                    metrics?.avg_review_days ? (
                      <CountUpNumber target={Math.round(metrics.avg_review_days)} suffix=" 天" />
                    ) : (
                      <span className="text-base text-muted-foreground">数据积累中</span>
                    ),
                },
              ].map((s) => (
                <motion.div
                  key={s.label}
                  variants={card}
                  animate={statsReveal ? 'show' : 'hidden'}
                  whileHover={{ y: -4 }}
                  className="glass-card rounded-lg p-3.5 text-left transition-colors hover:border-primary/40 sm:p-5"
                >
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {s.label}
                  </p>
                  <p
                    className="mt-1 text-2xl text-primary sm:mt-2 sm:text-4xl"
                    style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}
                  >
                    {s.node}
                  </p>
                </motion.div>
              ))}
            </motion.div>

            {funStats ? (
              <div className="mx-auto mt-3 flex max-w-4xl flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-muted-foreground sm:mt-4 sm:text-sm">
                <Link to="/papers" className="font-medium text-primary hover:underline">
                  论文 {paperTotal} 篇 →
                </Link>
                <span aria-hidden className="h-1 w-1 rounded-full bg-border" />
                <Link to="/fun" className="font-medium text-primary hover:underline">
                  副刊 {funTotal} 篇 →
                </Link>
              </div>
            ) : null}
          </div>
        </motion.section>

        <ContactStrip />
        <CurrentIssueBar />

        {/* ── 吸顶导航 + 检索：单根发丝线，无双线 ── */}
        <div className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-col items-stretch gap-2 px-4 py-2.5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6 sm:gap-y-2 sm:px-6">
            {/* 手机端底部已有主导航，这里不再重复一行一级入口；桌面端保留。 */}
            <nav className="hidden w-full items-center gap-x-5 overflow-x-auto whitespace-nowrap text-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:flex sm:w-auto sm:flex-wrap sm:overflow-visible">
              <span aria-current="page" className="font-medium">
                首页
              </span>
              <Link
                to="/papers"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                论文
              </Link>
              <Link
                to="/fun"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                副刊
              </Link>
              <Link
                to="/forum"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                讨论
              </Link>
              {isAuthenticated ? (
                <Link
                  to="/me"
                  className="link-underline text-muted-foreground transition-colors hover:text-foreground"
                >
                  我的
                </Link>
              ) : (
                <Link
                  to="/login"
                  className="link-underline text-muted-foreground transition-colors hover:text-foreground"
                >
                  登录
                </Link>
              )}
            </nav>
            <form onSubmit={onSearch} className="flex w-full items-center sm:w-64 sm:max-w-xs">
              <div className="relative w-full">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="检索文献…"
                  aria-label="检索文献"
                  className="h-8 rounded-full border bg-transparent pl-8 text-sm"
                />
              </div>
            </form>
          </div>
        </div>

        {/* ── 分类入口：跳转式导航（点哪个学科进哪个模块） ──
            用户口径：入门先是分类界面，而不是把全部文章铺在脸上。
            每张卡直达 /catalog?discipline=…，最新文章降级为下方紧凑列表。 */}
        <motion.section
          ref={revealLatestRef}
          initial="hidden"
          animate={revealLatest ? 'show' : 'hidden'}
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
          className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-16"
        >
          <SectionHeading
            title="按学科浏览"
            label="Browse by Discipline"
            action={
              <Link
                to="/catalog"
                className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                全部文章 <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          {statsLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
              {Array.from({ length: 9 }).map((_, i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {disciplineEntries.map(([name, count]) => {
                const style = DISCIPLINE_STYLE[name] ?? DEFAULT_DISCIPLINE_STYLE
                const Icon = style.icon
                return (
                  <motion.div
                    key={name}
                    variants={card}
                    animate={revealLatest ? 'show' : 'hidden'}
                    whileHover={{ y: -4 }}
                  >
                    <Link
                      to="/catalog"
                      search={{ discipline: name }}
                      className={cn(
                        'group flex items-center gap-4 rounded-xl border bg-gradient-to-br p-4 shadow-sm transition-all hover:shadow-md hover:border-primary/40',
                        style.tint,
                      )}
                    >
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-background/70 ring-1 ring-border">
                        <Icon className="h-5 w-5 text-foreground/75" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{name}</span>
                        <span className="block text-xs text-muted-foreground">{count} 篇</span>
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-primary" />
                    </Link>
                  </motion.div>
                )
              })}
            </div>
          )}
        </motion.section>

        {/* ── 最新发表：紧凑列表（分类已承担导航，这里只做"随便看看"） ── */}
        <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
          <SectionHeading
            title="最新发表"
            label="Latest Articles"
          />
          {isLoading ? (
            <div className="space-y-2" aria-hidden>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-lg border bg-card px-4 py-3">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="mt-2 h-3 w-1/3" />
                </div>
              ))}
            </div>
          ) : isError ? (
            <ErrorState message="加载文章失败" onRetry={() => refetch()} />
          ) : resources.length === 0 ? (
            <EmptyState
              title="首篇文章即将发布"
              description="编辑接受投稿后，论文会第一时间出现在这里。欢迎注册成为作者，投出第一稿。"
            />
          ) : (
            <div>
              {/* 横向滚动的封面卡条（v1.11）：首页最新发表从干列表升级为
                  可扫读的封面流，一屏多卡；列表形态保留在目录页。 */}
              <div className="-mx-4 flex snap-x gap-4 overflow-x-auto px-4 pb-3 sm:mx-0 sm:px-0">
                {resources.map((r, i) => (
                  <Link
                    key={r.id}
                    to="/catalog/$resourceId"
                    params={{ resourceId: String(r.id) }}
                    className="w-44 shrink-0 snap-start overflow-hidden rounded-xl border bg-card shadow-sm transition-shadow hover:shadow-md sm:w-52"
                  >
                    <ArticleCover resource={r} aspect="aspect-[3/4]" className="w-full" priority={i < 2} />
                    <div className="space-y-1 p-3">
                      <p className="line-clamp-2 text-sm font-medium leading-snug">{r.title}</p>
                      <p className="text-xs text-muted-foreground">{fmtDate(r.created_at)}</p>
                    </div>
                  </Link>
                ))}
              </div>
              <div className="mt-2 text-right">
                <Link to="/catalog" className="text-xs text-muted-foreground hover:text-primary">
                  查看全部 →
                </Link>
              </div>
            </div>
          )}
        </section>

        <ForumPulse />

        {/* ── 了解本刊：四个栏目按需展开 ── */}
        <motion.section
          ref={revealDiscoverRef}
          initial="hidden"
          animate={revealDiscover ? 'show' : 'hidden'}
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
          className="bg-muted/40 py-16"
        >
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <SectionHeading title="了解本刊" label="Explore the Journal" />
            <motion.div
              variants={card}
              animate={revealDiscover ? 'show' : 'hidden'}
              className="rounded-xl border bg-card p-4 shadow-sm sm:p-6"
            >
              <DiscoverTabs isAuthenticated={isAuthenticated} revealed={revealDiscover} />
            </motion.div>
          </div>
        </motion.section>

        {/* ── 常见问题 ── */}
        <motion.section
          ref={revealFaqRef}
          initial="hidden"
          animate={revealFaq ? 'show' : 'hidden'}
          id="faq"
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
          className="scroll-mt-16 py-16"
        >
          <div className="mx-auto max-w-4xl px-4 sm:px-6">
            <SectionHeading title="常见问题" label="FAQ" />
            <div className="grid gap-3">
              {FAQ.map((item) => (
                <motion.details
                  key={item.q}
                  variants={card}
                  animate={revealFaq ? 'show' : 'hidden'}
                  className="group rounded-lg border bg-card px-5 py-4 shadow-sm transition-colors hover:border-primary/40"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-medium sm:text-base">
                    {item.q}
                    <span
                      aria-hidden
                      className="text-xl text-muted-foreground transition-transform group-open:rotate-45"
                    >
                      +
                    </span>
                  </summary>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{item.a}</p>
                </motion.details>
              ))}
            </div>
          </div>
        </motion.section>

        <AnimatePresence>
          {showTop && (
            <motion.button
              type="button"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              whileHover={{ y: -2 }}
              onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              aria-label="返回顶部"
              className="fixed bottom-6 right-6 z-40 flex h-11 w-11 items-center justify-center rounded-full border bg-card/90 text-foreground shadow-lg backdrop-blur transition-colors hover:border-primary/50 hover:text-primary"
            >
              <ArrowUp className="h-4 w-4" />
            </motion.button>
          )}
        </AnimatePresence>

        {/* ── 页脚：深色收底，替代浅灰双线 ── */}
        <footer className="bg-primary text-primary-foreground">
          <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-4">
            <div className="md:col-span-2">
              <p className="text-3xl" style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}>
                Rubbish
              </p>
              <p className="mt-2 text-xs leading-relaxed text-primary-foreground/70">
                开放获取学术期刊
                <br />
                An Open Access Journal · ISSN 申请中
              </p>
            </div>
            <div className="text-sm">
              <p className="mb-3 text-xs uppercase tracking-[0.2em] text-primary-foreground/60">
                浏览
              </p>
              <ul className="space-y-2">
                <li>
                  <Link
                    to="/catalog"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    资源目录
                  </Link>
                </li>
                <li>
                  <Link
                    to="/archive"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    卷期归档
                  </Link>
                </li>
                <li>
                  <Link
                    to="/policies"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    期刊政策
                  </Link>
                </li>
                <li>
                  <Link
                    to="/support"
                    className="text-primary-foreground/60 transition-colors hover:text-primary-foreground"
                  >
                    支持本刊
                  </Link>
                </li>
                <li>
                  <a
                    href="/feed.xml"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    RSS 订阅
                  </a>
                </li>
                <li>
                  <a
                    href="/help"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    使用帮助
                  </a>
                </li>
                <li>
                  <a
                    href="/sitemap.xml"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    站点地图
                  </a>
                </li>
                <li>
                  <a
                    href="/privacy"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    隐私政策
                  </a>
                </li>
              </ul>
            </div>
            <div className="text-sm">
              <p className="mb-3 text-xs uppercase tracking-[0.2em] text-primary-foreground/60">
                参与
              </p>
              <ul className="space-y-2">
                <li>
                  <Link
                    to="/register"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    注册账号
                  </Link>
                </li>
                <li>
                  <Link
                    to="/login"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    登录
                  </Link>
                </li>
                <li>
                  <span className="text-primary-foreground/75">
                    QQ 群：1084870548（电脑端搜索群号）
                  </span>
                </li>
                <li>
                  <a
                    href="mailto:admin@argjiemi.cn"
                    className="text-primary-foreground/75 transition-colors hover:text-primary-foreground"
                  >
                    联系编辑部
                  </a>
                </li>
              </ul>
            </div>
          </div>
          <div className="border-t border-primary-foreground/15">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-primary-foreground/60 sm:px-6">
              <span>
                © {new Date().getFullYear()} Rubbish · An Open Access Journal
              </span>
              <span className="text-primary-foreground/50">
                独立实验项目 · 非正式出版机构 · 不收取任何费用
              </span>
            </div>
          </div>
        </footer>
      </div>
    </MotionConfig>
  )
}
