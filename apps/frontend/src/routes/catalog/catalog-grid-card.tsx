import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import type { ResourceResponse } from '@/lib/types'
import { formatAuthors, cn } from '@/lib/utils'
import { isScholarlyContent } from '@/lib/resource-labels'
import { DISCIPLINE_STYLE, DEFAULT_DISCIPLINE_STYLE } from '@/lib/discipline-style'

// 目录九宫格封面卡（v1.15）：一眼分轨道。
//
// 为什么是「文字徽标」而不是颜色小点：色弱/暗模式下纯颜色区分失效，
// 徽标里直接写「论文 / 娱乐」两个汉字，配合冷暖底色，第一屏就能分流。
//   - 论文：冷色/深色底（slate-900），信息行给 CLC + 学术年；
//   - 娱乐：暖色底（amber-500），信息行给「娱乐向/吐槽向」，绝不渲染空 CLC。
// 封面图缺失时用学科渐变底色 + 学科图标占位（DISCIPLINE_STYLE），
// 并对加载失败的图 onError 回退到同一占位——杜绝「破图」感。

interface CatalogGridCardProps {
  resource: ResourceResponse
}

export function CatalogGridCard({ resource }: CatalogGridCardProps) {
  const scholarly = isScholarlyContent(resource.content_category, resource.content_track)
  const authors = formatAuthors(resource.authors)
  const style = DISCIPLINE_STYLE[resource.discipline] ?? DEFAULT_DISCIPLINE_STYLE
  const Icon = style.icon

  const [coverBroken, setCoverBroken] = useState(false)

  return (
    <Link
      to="/catalog/$resourceId"
      params={{ resourceId: String(resource.id) }}
      className="group flex flex-row overflow-hidden rounded-xl border bg-card shadow-sm transition-shadow hover:shadow-md sm:flex-col"
    >
      {/* 封面区：封面图在上层，学科色块在底层兜底 */}
      <div className="relative aspect-[3/4] w-24 shrink-0 overflow-hidden sm:w-full">
        <div
          aria-hidden
          className={cn('absolute inset-0 bg-gradient-to-br', style.tint)}
        >
          <Icon className="absolute inset-0 m-auto h-10 w-10 text-foreground/20" />
        </div>
        {resource.cover_image && !coverBroken ? (
          <img
            src={resource.cover_image}
            alt=""
            aria-hidden
            loading="lazy"
            decoding="async"
            onError={() => setCoverBroken(true)}
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          />
        ) : null}

        {/* 轨道文字徽标：左上，汉字 + 冷暖底色 + 描边，不靠颜色小点 */}
        <span
          className={cn(
            'absolute left-2 top-2 rounded-md border px-2 py-0.5 text-[11px] font-semibold leading-none shadow-sm backdrop-blur-sm',
            scholarly
              ? 'border-slate-700/40 bg-slate-900/85 text-white'
              : 'border-amber-600/40 bg-amber-500/90 text-white',
          )}
        >
          {scholarly ? (resource.track === 'absurd' ? '荒诞论文' : '学术论文') : '副刊'}
        </span>

        {resource.is_special_issue ? (
          <span
            className="absolute right-2 top-2 rounded-md border border-rose-200/60 bg-rose-50/90 px-2 py-0.5 text-[11px] font-semibold leading-none text-rose-800 shadow-sm backdrop-blur-sm"
            title={resource.special_issue_reason ?? '篇幅特许收录'}
          >
            特别篇
          </span>
        ) : null}

        {/* 学科角标：封面左下角，辅助识别 */}
        {resource.discipline ? (
          <span className="absolute bottom-2 left-2 rounded bg-black/45 px-1.5 py-0.5 text-[10px] font-medium text-white/90 backdrop-blur-sm">
            {resource.discipline}
          </span>
        ) : null}
      </div>

      {/* 信息区：标题 + 一行轨道/学术元信息 + 作者 */}
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <p className="line-clamp-2 text-sm font-medium leading-snug">{resource.title}</p>

        {scholarly ? (
          // 论文卡：CLC + 学术信息一行；没有 CLC 时只给学科/年，不渲染空占位
          <p className="line-clamp-1 text-[11px] text-muted-foreground">
            {resource.clc_code ? `CLC ${resource.clc_code}` : resource.discipline}
            {resource.year ? ` · ${resource.year}` : ''}
          </p>
        ) : (
          // 娱乐卡：轨道向标（不显示 CLC 空占位）
          <p className="line-clamp-1 text-[11px] text-muted-foreground">
            {resource.content_category === 'rant' ? '吐槽向' : '副刊'}
            {resource.year ? ` · ${resource.year}` : ''}
          </p>
        )}

        <p className="mt-auto line-clamp-1 pt-0.5 text-[11px] text-muted-foreground">
          {authors || '佚名'}
        </p>
      </div>
    </Link>
  )
}
