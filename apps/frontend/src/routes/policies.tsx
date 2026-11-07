import { createFileRoute, Link } from '@tanstack/react-router'
import {
  ArrowLeft,
  BarChart3,
  EyeOff,
  Gavel,
  HeartHandshake,
  Lock,
  Scale,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { Card, CardContent } from '@/components/ui/card'

export const Route = createFileRoute('/policies')({
  component: PoliciesPage,
})

// 期刊政策与社区规范：开放获取、学术诚信、虚构内容免责、社区行为、
// 撤稿、隐私。一条一条写实，不留"最终解释权归本刊所有"这种废话。
const SECTIONS = [
  {
    icon: Scale,
    title: '开放获取政策',
    body: [
      '本刊为纯开放获取期刊：所有已刊出内容对所有人免费开放，无订阅墙、无阅读时限。',
      '作者保留论文著作权，投稿即授予本刊非独占的展示、存储与分发许可；作者可自行将稿件存档至个人主页或机构库。',
      '本站源代码以 PolyForm Noncommercial 1.0.0 开源：可自由学习与修改，但不得用于商业目的。站点内容与代码许可相互独立。',
    ],
  },
  {
    icon: Gavel,
    title: '学术诚信',
    body: [
      '抄袭、数据造假、代写、不当署名均属学术不端。经查实的稿件将被拒稿或撤稿，并在目录页保留撤稿声明。',
      '一稿多投：审稿期内发现即终止评审；已刊出后发现，按撤稿处理。',
      'AI 辅助写作不禁止，但必须在致谢中声明工具与用途；AI 不得署名作者——AI 无法对内容负责。',
      '发现不端行为可向编辑部举报（见页脚联系方式），编辑部在 14 个工作日内回应。',
    ],
  },
  {
    icon: Sparkles,
    title: '虚构与娱乐内容声明',
    body: [
      '本刊部分文章具有明确的虚构与娱乐性质：它们用规范的学术格式讨论脑洞命题，其"研究"可能基于想象、玩笑或不可复现的观察。',
      '这类内容不代表编辑部认可其中的事实陈述；引用时请像引用小说一样保持清醒。',
      '内容按学术、娱乐、吐槽三类标注，娱乐与吐槽类文章不参与学术指标统计。',
    ],
  },
  {
    icon: BarChart3,
    title: '本刊指数体系',
    body: [
      '本刊不使用引用数，不发布影响因子：所有指数均基于站内互动数据与 Editorial 评审记录计算，与任何外部评价体系互不隶属。',
      'RQS 质量分（0–100，14 档 A+ 至 F）：由 AI 初评与编辑复核按学术评审维度加权评定，是稿件能否录用的唯一质量依据。',
      'R 指数（篇级）：100 ×（0.5 × 阅读 + 0.3 × 下载 + 0.2 × 收藏），各行为量在同一学科内按最大值归一，衡量单篇在站内的综合互动热度。',
      'R 因子（刊级）：全刊已发表记录 R 指数的均值；站内互动事件总量达到最小样本（30）才出数，样本不足时宁可不显示，也不给一个会被单次点击放大的假数字。',
      'R1–R4 分区：同一学科内按 R 指数百分位分带（前 25% 为 R1）；学科已发表记录不足 4 篇时不出分区。',
    ],
  },
  {
    icon: HeartHandshake,
    title: '社区规范',
    body: [
      '尊重每一位参与者：不人身攻击、不地域歧视、不骚扰其他用户——对离谱论文的批评针对论文本身。',
      '账户不得出售、转让或冒用他人身份；用户名不得含侮辱性或误导性词汇。',
      '系统内的通知、阅读记录属于个人数据；请勿爬取或批量导出他人公开内容用于商业目的。',
      '违规行为按情节轻重处置：提醒 → 限制功能 → 封禁账号；严重违规记录审计日志并拒绝申诉解封。',
    ],
  },
  {
    icon: Trash2,
    title: '撤稿与更正',
    body: [
      '作者可申请撤回未刊出的稿件，随时、无理由、免费。',
      '已刊出内容发现实质错误时优先发布更正启事；只有错误严重影响结论或涉及不端时才撤稿。',
      '撤稿不是删稿：被撤稿件保留在目录中并标注"已撤稿"，撤稿原因公开可查。',
    ],
  },
  {
    icon: Lock,
    title: '隐私与数据',
    body: [
      '本站收集的数据仅限账号运行所必需：邮箱、阅读记录、收藏与投稿内容。',
      '不出售用户数据，不投放第三方跟踪广告。阅读记录仅用于向你提供进度与推荐，可在个人设置中清除。',
      '完整的隐私政策（含数据保留期限与你的权利）见独立页面。',
    ],
  },
  {
    icon: EyeOff,
    title: '评审保密',
    body: [
      '双盲评审：审稿人身份对作者保密，作者身份对审稿人保密，双方由系统匿名中转。',
      '审稿意见在录用后仅向作者公开；编辑部不公开审稿人之间的分歧讨论。',
      '任何一方试图打听或人肉对方身份，均视为破坏评审制度，按社区规范顶格处理。',
    ],
  },
]

function PoliciesPage() {
  return (
    <div className="mx-auto max-w-4xl py-8">
      <Link
        to="/"
        className="mb-4 inline-flex items-center text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        返回首页
      </Link>

      <PageHeader
        title="期刊政策与社区规范"
        description="开放获取、学术诚信、虚构内容声明、社区行为与撤稿政策——本刊怎么运作，写在这里。"
      />

      <div className="space-y-6">
        {SECTIONS.map(({ icon: Icon, title, body }) => (
          <RevealSection key={title}>
            <Card>
              <CardContent className="p-6">
                <h2 className="flex items-center gap-2 text-lg font-medium">
                  <Icon className="h-5 w-5 text-primary" />
                  {title}
                </h2>
                <ul className="mt-3 space-y-2.5">
                  {body.map((para) => (
                    <li key={para} className="flex gap-2.5 text-sm leading-relaxed text-muted-foreground">
                      <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary/50" />
                      {para}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </RevealSection>
        ))}

        <RevealSection as="p" className="border-t pt-6 text-xs leading-relaxed text-muted-foreground">
          政策更新会在本页与站内公告同步注明日期；重大变更提前 14 天公示。
          上一版政策文本可向编辑部索取。
          完整隐私条款见
          <a href="/privacy" className="mx-1 text-primary hover:underline">
            隐私政策
          </a>
          。
        </RevealSection>
      </div>
    </div>
  )
}
