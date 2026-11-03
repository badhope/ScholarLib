import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { AnimatePresence, motion, MotionConfig, type Variants } from 'motion/react'
import { useInViewReveal } from '@/hooks/use-in-view-reveal'
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
import { ArticleCover } from '@/components/common/article-cover'
import { qualityGrade } from '@/lib/resource-labels'
import { issueTitle } from '@/lib/issue-meta'
import { Skeleton } from '@/components/ui/skeleton'
import { absurdityLevel, typeLabel } from '@/lib/resource-labels'

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
  "'Playfair Display Variable', Georgia, 'Times New Roman', 'Noto Serif SC Variable', 'Noto Serif SC', serif"

const TYPEWRITER_PHRASES = [
  '投稿 · 同行评审 · 开放出版',
  '让每一篇经过评审的研究被世界看见',
  'Open Access · No Paywall · No Embargo',
  '双盲评审 · 版本留痕 · 全文免费',
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
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10)
}

/** 打字机：轮播短语，尊重系统减弱动效（直接显示第一条，无动画）。 */
function useTypewriter(phrases: string[]): string {
  const [text, setText] = useState(() =>
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? phrases[0]
      : '',
  )
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
  const [started, setStarted] = useState(false)
  const [value, setValue] = useState(0)

  useEffect(() => {
    if (!started) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const duration = reduce ? 0 : 1300
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const p = duration === 0 ? 1 : Math.min(1, (t - t0) / duration)
      setValue(Math.round(target * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [started, target])

  return (
    <motion.span
      onViewportEnter={() => setStarted(true)}
      viewport={{ once: true, amount: 0.6 }}
    >
      {value}
      {suffix}
    </motion.span>
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
          <span className="font-medium">第 1 卷 第 {Number(current.issue)} 期</span>
          <span className="truncate text-muted-foreground">《{issueTitle(current.issue)}》</span>
          <Badge variant="outline" className="tabular-nums">
            {current.published} 篇已上线
          </Badge>
        </p>
        <Link
          to="/archive"
          className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary transition-colors hover:underline"
        >
          本期目录 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </motion.div>
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
                  body: '注册即可投稿，统一评审标准、每篇标注荒诞指数（0–10），无需申请、无需介绍信。',
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
                <Button asChild size="lg">
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
                <Link to="/about" className="hover:text-foreground hover:underline">
                  关于本刊与编委会
                </Link>
              </li>
              <li>
                <Link to="/journal-metrics" className="hover:text-foreground hover:underline">
                  期刊指标与 R 因子
                </Link>
              </li>
              <li>
                <a href="/help.html" className="hover:text-foreground hover:underline">
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

function HomePage() {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const typed = useTypewriter(TYPEWRITER_PHRASES)
  const { data, isLoading, isError, refetch } = useResources({
    page: 1,
    page_size: 6,
    sort: 'created_at',
    order: 'desc',
  })
  const { data: stats } = useCatalogStats()
  const { data: metrics } = useJournalMetrics()

  // 公告：自动弹出 + 顶栏重开入口共用一份状态
  const notice = useAnnouncementPortal()

  const resources = data?.data ?? []
  const total = stats?.total ?? 0
  const disciplines = stats ? Object.keys(stats.by_discipline).length : 0
  // 荒诞指数均值：赛道下线后，首页第二张卡改用荒诞指数均值回答
  // "这本刊物有多正经"，口径见 /api/catalog/journal-metrics。
  const absurdityMedian = metrics?.absurdity_index_median

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
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.35] [background-image:radial-gradient(circle,theme(colors.foreground)_0.5px,transparent_0.5px)] [background-size:22px_22px] [mask-image:radial-gradient(50%_40%_at_50%_20%,black,transparent)]"
          />

          <div className="relative mx-auto max-w-6xl px-4 pb-12 pt-14 text-center sm:px-6 sm:pt-20">
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
              className="mt-5 text-7xl leading-none tracking-tight sm:text-9xl"
              style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}
            >
              Rubbish
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
                <Button asChild size="lg">
                  <Link to="/submissions">
                    <PenLine className="h-4 w-4" /> 提交稿件
                  </Link>
                </Button>
              ) : (
                <Button asChild size="lg">
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
              className="mx-auto mt-12 grid max-w-4xl grid-cols-2 gap-4 lg:grid-cols-4"
            >
              {[
                // 四项都必须回答读者/作者真正关心的问题：
                // 有多少可读、覆盖多广、内容气质如何、审稿要多久。
                // 「累计阅读」这种虚荣指标留给后台看，不放在期刊门面。
                { label: '已刊文章', node: <CountUpNumber target={total} /> },
                { label: '覆盖学科', node: <CountUpNumber target={disciplines} /> },
                {
                  label: '荒诞指数均值',
                  node:
                    absurdityMedian != null ? (
                      <span className="tabular-nums">{absurdityMedian.toFixed(1)} / 10</span>
                    ) : (
                      <span className="text-2xl text-muted-foreground">—</span>
                    ),
                },
                {
                  label: '平均审稿天数',
                  node:
                    metrics?.avg_review_days != null ? (
                      <CountUpNumber target={Math.round(metrics.avg_review_days)} suffix=" 天" />
                    ) : (
                      <span className="text-2xl text-muted-foreground">—</span>
                    ),
                },
              ].map((s) => (
                <motion.div
                  key={s.label}
                  variants={card}
                  animate={statsReveal ? 'show' : 'hidden'}
                  whileHover={{ y: -4 }}
                  className="rounded-lg border bg-card/80 p-5 text-left shadow-sm backdrop-blur transition-colors hover:border-primary/40"
                >
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {s.label}
                  </p>
                  <p
                    className="mt-2 text-4xl text-primary"
                    style={{ fontFamily: DISPLAY_FONT, fontWeight: 600 }}
                  >
                    {s.node}
                  </p>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </motion.section>

        <CurrentIssueBar />

        {/* ── 吸顶导航 + 检索：单根发丝线，无双线 ── */}
        <div className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
            <nav className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
              <span aria-current="page" className="font-medium">
                首页
              </span>
              <Link
                to="/catalog"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                资源目录
              </Link>
              <Link
                to="/archive"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                卷期归档
              </Link>
              <Link
                to="/levels"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                等级与规范
              </Link>
              <Link
                to="/journal-metrics"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                期刊指标
              </Link>
              <Link
                to="/authors"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                作者指南
              </Link>
              <a
                href="#faq"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                常见问题
              </a>
              <Link
                to="/about"
                className="link-underline text-muted-foreground transition-colors hover:text-foreground"
              >
                关于本刊
              </Link>
            </nav>
            <form onSubmit={onSearch} className="flex w-full max-w-xs items-center sm:w-64">
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

        {/* ── 最新发表：卡片网格 ── */}
        <motion.section
          ref={revealLatestRef}
          initial="hidden"
          animate={revealLatest ? 'show' : 'hidden'}
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07 } } }}
          className="mx-auto max-w-6xl px-4 py-16 sm:px-6"
        >
          <SectionHeading
            title="最新发表"
            label="Latest Articles"
            action={
              <Link
                to="/catalog"
                className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                全部文章 <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          {isLoading ? (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-lg border bg-card p-5 shadow-sm">
                  <Skeleton className="h-3 w-16 rounded-full" />
                  <Skeleton className="mt-4 h-5 w-4/5" />
                  <Skeleton className="mt-2 h-3.5 w-1/2" />
                  <Skeleton className="mt-4 h-3 w-full" />
                  <Skeleton className="mt-2 h-3 w-full" />
                  <Skeleton className="mt-2 h-3 w-2/3" />
                  <Skeleton className="mt-5 h-px w-full" />
                  <Skeleton className="mt-4 h-3 w-1/3" />
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
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {resources.map((r, i) => (
                <motion.article
                  key={r.id}
                  variants={card}
                  animate={revealLatest ? 'show' : 'hidden'}
                  whileHover={{ y: -5 }}
                  className="card-lift group relative flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm hover:border-primary/40"
                >
                  {/* 整卡可点：覆盖整张卡片的链接（视觉内容在其上、不拦截点击） */}
                  <Link
                    to="/catalog/$resourceId"
                    params={{ resourceId: String(r.id) }}
                    aria-label={`阅读《${r.title}》`}
                    className="absolute inset-0 z-20 rounded-lg focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  {/* 主题封面：16:9 固定比例，图片懒加载不引起版面跳动 */}
                  <ArticleCover resource={r} priority={i < 3} />
                  <div className="pointer-events-none relative z-10 flex flex-1 flex-col p-5 [&_a]:pointer-events-auto">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        <Badge
                          variant="outline"
                          className="rounded-full px-2.5 text-[10px] font-normal uppercase tracking-widest text-muted-foreground"
                        >
                          {typeLabel(r.type)}
                        </Badge>
                        {(() => {
                          const grade = qualityGrade(r.quality_grade)
                          return grade ? (
                            <Badge
                              variant="outline"
                              className={`rounded-full px-2.5 text-[10px] font-normal ${grade.className}`}
                              title={`RQS ${r.quality_score ?? ''} / 100 · ${grade.description}`}
                            >
                              {grade.label}
                            </Badge>
                          ) : null
                        })()}
                        {(() => {
                          const level = absurdityLevel(r.absurdity_index)
                          return level ? (
                            <Badge
                              variant={level.variant}
                              className="rounded-full px-2.5 text-[10px] font-normal"
                              title={`荒诞指数 ${r.absurdity_index} / 10 · ${level.description}`}
                            >
                              {level.label}
                            </Badge>
                          ) : null
                        })()}
                      </div>
                      <time className="shrink-0 text-xs text-muted-foreground">
                        {fmtDate(r.created_at)}
                      </time>
                    </div>
                    <h3 className="text-lg leading-snug" style={{ fontFamily: DISPLAY_FONT }}>
                      <Link
                        to="/catalog/$resourceId"
                        params={{ resourceId: String(r.id) }}
                        className="pointer-events-auto underline-offset-4 decoration-1 hover:underline"
                      >
                        {r.title}
                      </Link>
                    </h3>
                    <p className="mt-2 line-clamp-1 text-xs text-muted-foreground">
                      {r.authors.join('、')}
                    </p>
                    <p className="mt-3 line-clamp-3 flex-1 text-sm leading-relaxed text-muted-foreground">
                      {r.abstract}
                    </p>
                    <div className="mt-4 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
                      <span className="truncate">
                        {r.discipline}
                        {/* R 指数只在有真实阅读样本时展示：仅 1 次下载也会算出
                            R 30.0，满屏同号会被误读成假指标。 */}
                        {r.r_index != null &&
                        (r.reads ?? 0) + (r.downloads ?? 0) + (r.saves ?? 0) >= 3 ? (
                          <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 font-medium tabular-nums text-primary">
                            R {r.r_index.toFixed(1)}
                          </span>
                        ) : null}
                      </span>
                      <span
                        className="inline-flex items-center gap-1 text-primary opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden
                      >
                        阅读 <ArrowRight className="h-3 w-3" />
                      </span>
                    </div>
                  </div>
                  <span aria-hidden className="absolute right-4 top-8 text-5xl leading-none text-muted-foreground/10" style={{ fontFamily: DISPLAY_FONT }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </motion.article>
              ))}
            </div>
          )}
        </motion.section>

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
                    href="/help.html"
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
              <span>© 2026 Rubbish · An Open Access Journal</span>
              <span>Powered by Rubbish</span>
            </div>
          </div>
        </footer>
      </div>
    </MotionConfig>
  )
}
