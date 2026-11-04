import { Link } from '@tanstack/react-router'
import { FileDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ArticleCover } from '@/components/common/article-cover'
import { absurdityLevel, qualityGrade, typeLabel } from '@/lib/resource-labels'
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
  const level = absurdityLevel(resource.absurdity_index)
  const grade = qualityGrade(resource.quality_grade)

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
          className="aspect-auto h-full w-full"
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
              {typeLabel(resource.type)}
            </Badge>
            {grade ? (
              <Badge
                variant="outline"
                className={`px-1.5 py-0 text-[10px] ${grade.className}`}
                title={`RQS ${resource.quality_score ?? ''} / 100 · ${grade.description}`}
              >
                {grade.label}
              </Badge>
            ) : null}
            {level ? (
              <Badge
                variant={level.variant}
                className="px-1.5 py-0 text-[10px]"
                title={`荒诞指数 ${resource.absurdity_index} / 10 · ${level.description}`}
              >
                {level.label}
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
