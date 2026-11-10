/**
 * Rubbish 期刊标志 —— “退稿纸折成 R”。
 *
 * 三张错落纸页构成 R 骨架，右上纸角折起为回收箭头。
 * 站徽使用带奶油纸底的圆角小方章：浅色页面近乎融入背景，
 * 深色页面仍保留足够对比；不依赖 currentColor 反白，
 * 避免绿色主形在暗色侧边栏里失去层次。
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-[5px] bg-[#F4EFE4] p-[2px] ${className ?? ''}`}
    >
      <img
        src="/brand-rubbish.png"
        alt="Rubbish"
        className="h-full w-full object-contain"
        draggable={false}
      />
    </span>
  )
}
