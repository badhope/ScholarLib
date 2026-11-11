/**
 * Rubbish 期刊标志 —— 矢量版“退稿纸折成 R”。
 * 三张错落纸页构成 R 骨架，右上纸角折起为回收箭头。
 */
export function BrandMark({
  className,
  decorative = false,
}: {
  className?: string
  /** 与文字字标并排时置为装饰图，避免读屏把品牌名读两遍 */
  decorative?: boolean
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-[5px] bg-[#F4EFE4] p-[2px] ${className ?? ''}`}
    >
      <svg
        viewBox="0 0 64 64"
        role={decorative ? 'presentation' : 'img'}
        aria-label={decorative ? undefined : 'Rubbish'}
        aria-hidden={decorative || undefined}
        className="h-full w-full"
      >
        <rect x="1" y="1" width="62" height="62" rx="10" fill="#F4EFE4" />
        <path
          d="M14 12.5 18 10l17 30.5-4 2.5L14 12.5Z"
          fill="#9DBCA8"
          opacity="0.45"
        />
        <path
          d="M47.5 15 51 17.5 34 48l-3.5-2.5L47.5 15Z"
          fill="#6F9B80"
          opacity="0.5"
        />
        <path
          d="M17 13h18.5c8.8 0 14.3 4.6 14.3 12 0 5.6-3.2 9.6-8.6 11l11.4 15H40.4L30.5 37.2h-4.2v13.8H17V13Zm9.3 7.7v9.1h8.5c4 0 6.4-1.7 6.4-4.6 0-2.8-2.4-4.5-6.4-4.5h-8.5Z"
          fill="#2F5D46"
        />
        <path
          d="M45.5 8.5c4.2 1.4 7.2 4.6 8.4 8.6"
          fill="none"
          stroke="#1F7A4D"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <path
          d="M54.5 17.8 55 24l-6.2-1.2"
          fill="none"
          stroke="#1F7A4D"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M12 52h25" stroke="#2F5D46" strokeWidth="1.6" strokeLinecap="round" opacity="0.35" />
      </svg>
    </span>
  )
}
