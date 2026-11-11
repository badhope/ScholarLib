/**
 * 内页轻量环境背景：只用 CSS 动画，不创建 Canvas/RAF，避免全站粒子带来的持续耗电。
 * 首页需要更强粒子网络时仍使用 HeroBackdrop。
 */
export function AmbientBackdrop() {
  return (
    <div className="ambient-backdrop" aria-hidden="true">
      <span className="ambient-shape ambient-circle" />
      <span className="ambient-shape ambient-triangle" />
      <span className="ambient-shape ambient-square" />
      <span className="ambient-shape ambient-ring" />
    </div>
  )
}
