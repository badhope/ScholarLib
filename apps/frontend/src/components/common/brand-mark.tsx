/**
 * Rubbish 期刊标志 —— 回收三箭头（源自创刊 PDF 刊头原图提取）。
 *
 * 提取自原稿 PDF 第一页的 RUBBISH 回收标志（瓶子 + 三箭头 + 废纸堆），
 * 处理为白色 + alpha 通道的模板图（/brand-rubbish.png），再用 CSS mask
 * 以 currentColor 上色：明暗主题、侧边栏折叠态都自动跟随文字色，
 * 与旧版"R 字印章"的适配行为完全一致。
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      role="img"
      aria-label="Rubbish"
      className={`inline-block shrink-0 ${className ?? ''}`}
      style={{
        backgroundColor: 'currentColor',
        WebkitMaskImage: 'url(/brand-rubbish.png)',
        maskImage: 'url(/brand-rubbish.png)',
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskPosition: 'center',
        maskPosition: 'center',
      }}
    />
  )
}
