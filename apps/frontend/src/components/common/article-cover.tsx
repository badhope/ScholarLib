import { cn } from '@/lib/utils'
import type { ResourceResponse } from '@/lib/types'

// 专题封面：优先用编辑为本刊选定的主题图（/covers/xx.jpg，已本地化，
// 1600×900，无外链依赖）；没有封面时回退到生成式纸面卡（CoverArt 的
// 极简版本），保证任何条目都有视觉锚点且不会出现破图占位。
//
// 与 CoverArt 的分工：CoverArt 用于「还没有主题图」的占位；本组件用于
// 内容卡片上的真实封面，叠一层从下往上的暗色渐层保证标题可读。

interface ArticleCoverProps {
  resource: Pick<ResourceResponse, 'title' | 'discipline' | 'cover_image' | 'cover_theme'>
  className?: string
  /** 是否显示左下角学科标签（卡片与详情页可不同） */
  showDiscipline?: boolean
  priority?: boolean
}

export function ArticleCover({
  resource,
  className,
  showDiscipline = true,
  priority = false,
}: ArticleCoverProps) {
  const hasImage = Boolean(resource.cover_image)
  return (
    <div
      className={cn(
        'relative isolate overflow-hidden bg-muted',
        // 固定 16:9，避免图片加载前后高度变化引起的版面抖动（CLS）。
        'aspect-[16/9] w-full',
        className,
      )}
    >
      {hasImage ? (
        <img
          src={resource.cover_image ?? ''}
          alt=""
          aria-hidden="true"
          loading={priority ? 'eager' : 'lazy'}
          decoding="async"
          // 宽高比由父容器锁定，图片填满；object-cover 防拉伸。
          className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
        />
      ) : (
        <div
          aria-hidden
          className="absolute inset-0 bg-[radial-gradient(120%_100%_at_0%_0%,oklch(0.93_0.05_150),transparent_60%),radial-gradient(120%_100%_at_100%_100%,oklch(0.90_0.04_120),transparent_55%)]"
        />
      )}
      {/* 无封面时的识别符号：淡淡的回收箭头，避免整块变成无信息的色斑 */}
      {!hasImage ? (
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className="absolute left-1/2 top-1/2 h-1/3 w-1/3 -translate-x-1/2 -translate-y-1/2 text-primary/20"
          fill="currentColor"
        >
          <path d="M12 3l3.5 3.5-1.4 1.4L12 5.8 9.9 7.9 8.5 6.5 12 3zM4 11l2 2-2 2v-4zm16 0v4l-2-2 2-2zM7 19l2-2h6l2 2H7z" />
        </svg>
      ) : null}
      {/* 可读性渐层：只压下半部，不整张变灰 */}
      <div
        aria-hidden
        className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/10 to-transparent"
      />
      {showDiscipline && resource.discipline ? (
        <span className="absolute bottom-2.5 left-3 rounded-full bg-black/35 px-2 py-0.5 text-[10px] font-medium tracking-wide text-white/90 backdrop-blur-sm">
          {resource.discipline}
        </span>
      ) : null}
    </div>
  )
}
