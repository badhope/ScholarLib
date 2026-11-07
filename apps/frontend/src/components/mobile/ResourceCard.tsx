import { Link } from '@tanstack/react-router'
import { FileDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ArticleCover } from '@/components/common/article-cover'
import { contentCategoryLabel, displayTypeLabel, isScholarlyContent } from '@/lib/resource-labels'
import { formatAuthors } from '@/lib/utils'
import type { ResourceResponse } from '@/lib/types'

// 移动端目录卡片：横向紧凑布局。
//
// 桌面端可以铺 3 列大图卡，手机一屏只有 390px——沿用「16:9 大图 + 四行元信息」
// 的结果是一屏只能看到一张半，浏览目录变成翻相册。这里改成「左侧缩略图 +
// 右侧两行标题」的信息流卡：封面只负责识别，标题和等级负责决策。
// 封面高度锁定 84px，图片懒加载也不会引起滚动跳动。
export function ResourceCard({ resource }: { resource: ResourceResponse }) {
  const authors = formatAuthors(resource.authors)
  const scholarly = isScholarlyContent(resource.content_category, resource.content_track)
  // 娱乐稿不再打"娱乐向"副标——类型 chip 已写明"娱乐/吐槽"，避免重复。
  const categoryTag = scholarly ? contentCategoryLabel(resource.content_category) : ''

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
            <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
              {displayTypeLabel(resource.type, resource.content_category, resource.content_track)}
            </Badge>
            {categoryTag ? (
              <Badge variant="outline" className="bg-primary/10 px-1.5 py-0 text-[10px] text-primary border-primary/25">
                {categoryTag}
              </Badge>
            ) : null}
            {resource.has_file ? <FileDown className="h-3 w-3" /> : null}
            <span>{resource.year}</span>
          </div>
        </div>
      </div>
    </Link>
  )
}
