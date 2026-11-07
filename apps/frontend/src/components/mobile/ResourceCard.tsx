import { Link } from '@tanstack/react-router'
import { FileDown } from 'lucide-react'
import { ArticleCover } from '@/components/common/article-cover'
import { isScholarlyContent } from '@/lib/resource-labels'
import { formatAuthors, cn } from '@/lib/utils'
import type { ResourceResponse } from '@/lib/types'

// 移动端目录卡片：横向紧凑布局。
//
// 桌面端可以铺 3 列大图卡，手机一屏只有 390px——沿用「16:9 大图 + 四行元信息」
// 的结果是一屏只能看到一张半，浏览目录变成翻相册。这里改成「左侧缩略图 +
// 右侧两行标题」的信息流卡：封面只负责识别，标题和等级负责决策。
// 封面高度锁定 84px，图片懒加载也不会引起滚动跳动。
//
// v1.15：加轨道文字徽标「论文 / 娱乐」（论文=冷深色底，娱乐=暖色底），
// 与九宫格卡同一口径——列表视图也能一眼分轨道，不靠颜色小点。
export function ResourceCard({ resource }: { resource: ResourceResponse }) {
  const authors = formatAuthors(resource.authors)
  const scholarly = isScholarlyContent(resource.content_category, resource.content_track)
  // 论文卡：CLC + 学科一行；娱乐卡：娱乐向/吐槽向，不渲染空 CLC 占位。
  const subLabel = scholarly
    ? resource.clc_code
      ? `CLC ${resource.clc_code}`
      : resource.discipline
    : resource.content_category === 'rant'
      ? '吐槽向'
      : '娱乐向'

  return (
    <Link
      to="/catalog/$resourceId"
      params={{ resourceId: String(resource.id) }}
      className="group flex gap-3 rounded-xl border bg-card p-3 active:scale-[0.99]"
    >
      <div className="h-[84px] w-[112px] shrink-0 overflow-hidden rounded-lg">
        <ArticleCover
          resource={resource}
          showDiscipline={false}
          aspect=""
          className="h-full w-full"
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col justify-between py-0.5">
        <p className="line-clamp-2 text-sm font-medium leading-snug">{resource.title}</p>
        <div>
          <p className="line-clamp-1 text-[11px] text-muted-foreground">
            {authors || resource.discipline}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
            {/* 轨道文字徽标：汉字 + 冷暖底色，不靠颜色小点 */}
            <span
              className={cn(
                'inline-flex items-center rounded border px-1.5 py-0 font-semibold leading-none',
                scholarly
                  ? 'border-slate-700/40 bg-slate-900/85 text-white'
                  : 'border-amber-600/40 bg-amber-500/90 text-white',
              )}
            >
              {scholarly ? '论文' : '娱乐'}
            </span>
            <span className="text-muted-foreground">{subLabel}</span>
            {resource.has_file ? <FileDown className="h-3 w-3" /> : null}
            <span>{resource.year}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}
