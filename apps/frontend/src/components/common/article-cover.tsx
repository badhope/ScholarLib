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
  /** 宽度以外的比例类：默认 16:9；缩略图传空串交给外层高度控制 */
  aspect?: string
  /** 叠加暗色渐层：只有「文字压在图上」的场景才需要；
   *  列表缩略图里开会把照片下半截压成灰块，看起来像加载失败。 */
  overlay?: boolean
}

export function ArticleCover({
  resource,
  className,
  showDiscipline = true,
  priority = false,
  overlay = false,
  aspect = '',
}: ArticleCoverProps) {
  const hasImage = Boolean(resource.cover_image)
  return (
    <div
      className={cn(
        'relative isolate overflow-hidden bg-muted w-full',
        // 比例由调用方显式传入：同一元素上同时存在两个 aspect-* 时，
        // 编译后的 CSS 谁生效不确定，实测缩略图只填了上半截、下面留白。
        aspect,
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
      {/* 无封面时的识别符号。旧版放的是一个回收箭头 SVG（text-primary/20），
          在浅绿渐变上缩到 1/3 大小后极像浏览器的「图片加载失败」占位符，
          读者第一反应是破图。改成衬线刊名水印：一眼看出是设计，不是故障。 */}
      {!hasImage ? (
        <div
          aria-hidden
          className="absolute inset-0 flex items-center justify-center"
        >
          <span className="font-serif text-3xl font-semibold tracking-[0.18em] text-primary/25 sm:text-4xl">
            RUBBISH
          </span>
        </div>
      ) : null}
      {/* 可读性渐层：仅 overlay 场景（文字压在图上）才开；默认关闭 */}
      {overlay ? (
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/10 to-transparent"
        />
      ) : null}
      {showDiscipline && resource.discipline ? (
        <span className="absolute bottom-2.5 left-3 rounded-full bg-black/45 px-2 py-0.5 text-[10px] font-medium tracking-wide text-white/90 backdrop-blur-sm">
          {resource.discipline}
        </span>
      ) : null}
    </div>
  )
}
