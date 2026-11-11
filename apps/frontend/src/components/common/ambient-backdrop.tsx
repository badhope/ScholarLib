/**
 * 内页轻量环境背景：只用 CSS 动画，不创建 Canvas/RAF，避免全站粒子带来的持续耗电。
 * 首页需要更强粒子网络时仍使用 HeroBackdrop。
 *
 * 第三批扩展：在几何图形之外补一版「尘埃光点」。位置与节奏写死，
 * 不随机，保证同一页面每次进来构图一致（截图与视觉回归更好比对）。
 */
import type { CSSProperties } from 'react'

const DUST = [
  { left: '12%', top: '18%', duration: '29s', delay: '0s' },
  { left: '26%', top: '62%', duration: '34s', delay: '-6s' },
  { left: '41%', top: '30%', duration: '31s', delay: '-12s', large: true },
  { left: '58%', top: '74%', duration: '37s', delay: '-3s' },
  { left: '69%', top: '22%', duration: '28s', delay: '-16s' },
  { left: '83%', top: '52%', duration: '33s', delay: '-9s', large: true },
  { left: '91%', top: '84%', duration: '36s', delay: '-20s' },
  { left: '8%', top: '88%', duration: '30s', delay: '-14s' },
]

export function AmbientBackdrop() {
  return (
    <div className="ambient-backdrop" aria-hidden="true">
      <span className="ambient-shape ambient-circle" />
      <span className="ambient-shape ambient-triangle" />
      <span className="ambient-shape ambient-square" />
      <span className="ambient-shape ambient-ring" />
      {DUST.map((dot, i) => (
        <span
          key={i}
          className={dot.large ? 'ambient-dot ambient-dot-lg' : 'ambient-dot'}
          style={
            {
              left: dot.left,
              top: dot.top,
              '--dot-duration': dot.duration,
              '--dot-delay': dot.delay,
            } as CSSProperties
          }
        />
      ))}
    </div>
  )
}
