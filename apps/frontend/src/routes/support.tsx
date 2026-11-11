import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Coffee, Heart, Info, Mail } from 'lucide-react'
import { PageHeader } from '@/components/common/page-header'
import { RevealSection } from '@/components/common/reveal-section'
import { Card, CardContent } from '@/components/ui/card'

export const Route = createFileRoute('/support')({
  component: SupportPage,
})

// 赞助与支持：低可见度入口（页脚次级链接 + 关于页引用），不做弹窗、
// 不进导航、不在内容页插入任何募捐元素。
// 收款方式全部来自环境变量（构建期注入），未配置时只展示文字渠道，
// 不硬编码任何个人收款账户。
const VITE_PREFIX = 'VITE_SUPPORT_'

interface SupportChannel {
  key: string
  label: string
  hint: string
}

const CHANNELS: SupportChannel[] = [
  { key: 'ALIPAY', label: '支付宝', hint: '打开支付宝扫一扫，或转账到下方账号。' },
  { key: 'WECHAT', label: '微信', hint: '打开微信扫一扫即可支持。' },
  { key: 'BANK', label: '银行转账', hint: '跨行转账请备注「Rubbish 赞助」。' },
]

function env(key: string): string {
  return (import.meta.env[`${VITE_PREFIX}${key}`] as string | undefined)?.trim() ?? ''
}

function SupportPage() {
  const qrcode = env('QRCODE_URL')
  const account = env('ACCOUNT')
  const note = env('NOTE')
  const email = env('EMAIL')
  const configured = Boolean(qrcode || account)

  return (
    <div className="mx-auto max-w-3xl">
      <Link
        to="/"
        className="mb-4 inline-flex items-center text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        返回首页
      </Link>

      <PageHeader
        title="支持本刊"
        description="Rubbish 是无广告、无付费墙的开放获取期刊，服务器与域名靠读者自愿支持维持。"
      />

      <div className="space-y-6">
        <RevealSection>
          <Card>
            <CardContent className="p-6">
              <h2 className="flex items-center gap-2 text-lg font-medium">
                <Heart className="h-5 w-5 text-primary" />
                赞助去向
              </h2>
              <ul className="mt-3 space-y-2.5">
                {[
                  '服务器与对象存储：全部已刊出论文的 PDF 与在线稿托管。',
                  '域名与证书：rubbish.argjiemi.cn 的续费与 HTTPS。',
                  '审稿与出版工具链：排版、DOI 注册与邮件服务的运行成本。',
                  '赞助完全自愿，不与投稿、评审、展示位置挂钩——本刊不卖版面。',
                ].map((para) => (
                  <li
                    key={para}
                    className="flex gap-2.5 text-sm leading-relaxed text-muted-foreground"
                  >
                    <span
                      aria-hidden
                      className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary/50"
                    />
                    {para}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </RevealSection>

        {configured ? (
          <RevealSection>
            <Card>
              <CardContent className="p-6">
                <h2 className="flex items-center gap-2 text-lg font-medium">
                  <Coffee className="h-5 w-5 text-primary" />
                  转账方式
                </h2>
                {qrcode ? (
                  <figure className="mt-4 flex flex-col items-center gap-2">
                    <img
                      src={qrcode}
                      alt="收款二维码"
                      width={220}
                      height={220}
                      loading="lazy"
                      className="rounded-lg border bg-white p-2"
                    />
                    <figcaption className="text-xs text-muted-foreground">
                      扫码支持（请以实际到账为准，本站不显示也不存储任何交易信息）
                    </figcaption>
                  </figure>
                ) : null}
                {account ? (
                  <p className="mt-4 break-all rounded-md bg-muted/50 px-4 py-3 text-sm">
                    {account}
                  </p>
                ) : null}
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  {CHANNELS.map((c) => (
                    <div key={c.key} className="rounded-md border p-3">
                      <p className="text-sm font-medium">{c.label}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{c.hint}</p>
                    </div>
                  ))}
                </div>
                {note ? <p className="mt-4 text-xs text-muted-foreground">{note}</p> : null}
              </CardContent>
            </Card>
          </RevealSection>
        ) : (
          <RevealSection>
            <Card>
              <CardContent className="p-6">
                <h2 className="flex items-center gap-2 text-lg font-medium">
                  <Info className="h-5 w-5 text-primary" />
                  转账通道
                </h2>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  本刊暂未开通电子收款通道。如需支持本刊运行，可通过页脚邮箱与编辑部联系；
                  我们不接受与投稿、评审结果挂钩的任何款项。
                </p>
              </CardContent>
            </Card>
          </RevealSection>
        )}

        {email ? (
          <RevealSection>
            <Card>
              <CardContent className="p-6">
                <h2 className="flex items-center gap-2 text-lg font-medium">
                  <Mail className="h-5 w-5 text-primary" />
                  联系编辑部
                </h2>
                <p className="mt-3 text-sm text-muted-foreground">
                  赞助-related 事务（对账、鸣谢名单、机构赞助）请来信：
                  <a className="ml-1 text-primary hover:underline" href={`mailto:${email}`}>
                    {email}
                  </a>
                </p>
              </CardContent>
            </Card>
          </RevealSection>
        ) : null}
      </div>
    </div>
  )
}
