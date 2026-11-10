import { createFileRoute, Link, redirect } from '@tanstack/react-router'
import { PageHeader } from '@/components/common/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export const Route = createFileRoute('/help')({
  // 操作指南并入 /guide 的第二个页签，旧链接与书签统一跳转。
  beforeLoad: () => {
    throw redirect({ to: '/guide', search: { tab: 'help' } })
  },
  component: HelpPage,
})

const GROUPS = [
  {
    who: '作者',
    items: [
      ['投稿前', '先在“作者指南”确认栏目与格式；论文轨（学术/荒诞）都需要摘要、关键词、完整参考文献与图注，副刊轨不要求论文范式。'],
      ['投稿', '“我的提交 → 新建投稿”四步向导可保存草稿；上传后系统给出结构报告，按提示补缺即可。'],
      ['审稿中', '状态为 under_review 时等待分派；major_revision / minor_revision 按意见修改后重投，不要新建重复稿。'],
      ['有异议', '“作者申诉”选择作品与类型（撤回 / 重审分数 / 重审分区），理由至少 100 字，写清争议点与依据。编辑部受理后会通知。'],
      ['撤回', '撤回申请经编辑部批准后作品下架；已下架作品不会重新计分，历史记录保留在审计日志。'],
    ],
  },
  {
    who: '审稿人',
    items: [
      ['接审', '审稿工作台查看邀请；有利益冲突或无法按时完成时先拒审/申请延期，不要静默拖到超期。'],
      ['匿名', '只看匿名稿与附件，不检索作者身份；发现身份线索在意见里提示编辑，不在报告中公开猜测。'],
      ['意见', '按 rubric 五维两段式打分并写可执行意见：问题、证据、修改建议分开写；避免人身评价。'],
      ['冲突', '两位审稿人结论冲突时由编辑裁决；审稿人不需要私下说服对方。'],
    ],
  },
  {
    who: '编辑 / 主编',
    items: [
      ['分派', '主编工作台按栏目与学科分派；同一稿件回避利益冲突，超期先催办再换人。'],
      ['决定', '录用前核对结构报告、作者位与通信邮箱；退修要写清可执行的修改点。'],
      ['申诉', '“作者申诉”待办里逐条受理或驳回，处置说明至少 20 字；受理撤回会下架作品。'],
      ['更正', '更正、撤稿与编辑部说明统一进 Amendments & Corrections 栏目，不混在研究正文。'],
      ['期次', '卷期归档按期分部分（Editorial / Features / Articles / Reviews / Corrections）；新一期先排 parts 再发布。'],
    ],
  },
] as const

export function HelpPage() {
  return (
    <div>
      <PageHeader
        title="操作指南"
        description="作者、审稿人、编辑在各种情况下该点哪里、需要什么材料、会被怎样处理。第一次使用还会看到可跳过的分步引导。"
        actions={<Badge variant="secondary">可随时跳过引导</Badge>}
      />
      <div className="grid gap-5 lg:grid-cols-3">
        {GROUPS.map((g) => (
          <Card key={g.who} className="h-fit">
            <CardHeader><CardTitle className="text-lg">{g.who}</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {g.items.map(([title, body]) => (
                <div key={title}>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{body}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="mt-6 flex flex-wrap gap-3 text-sm">
        <Link className="underline underline-offset-4" to="/submissions">我的提交</Link>
        <Link className="underline underline-offset-4" to="/appeals">作者申诉</Link>
        <Link className="underline underline-offset-4" to="/review/workbench">审稿工作台</Link>
        <Link className="underline underline-offset-4" to="/editor/workbench">主编工作台</Link>
        <Link className="underline underline-offset-4" to="/sections">栏目</Link>
      </div>
    </div>
  )
}
