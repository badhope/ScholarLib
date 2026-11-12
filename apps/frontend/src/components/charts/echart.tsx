import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, RadarChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DatasetComponent,
  MarkLineComponent,
  MarkPointComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { cn } from '@/lib/utils'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DatasetComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
])

export type EChartOption = echarts.EChartsCoreOption

// 统一的图表主题：与站点配色一致，字体走 OFL 衬线栈，网格极淡。
// 每一处图表都从这份主题出发，保证「一页里所有图看起来是同一套设计」。
// 主色是回收墨绿，暖赭色只作对比色出现；顺序即语义优先级，
// 第一根柱子永远是最能代表刊物的颜色。
const PALETTE = ['#2f6b52', '#c7a24b', '#5f9e7d', '#c96f5e', '#3f7d8c', '#8aa79b']

export function EChart({
  option,
  height = 260,
  className,
  ariaLabel,
}: {
  option: EChartOption
  height?: number
  className?: string
  ariaLabel: string
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    chart.setOption({
      color: PALETTE,
      animation: !reduce,
      animationDuration: reduce ? 0 : 700,
      animationEasing: 'cubicOut',
      textStyle: { fontFamily: "'Noto Serif SC', 'DejaVu Serif', serif", fontSize: 12 },
      grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', confine: true },
      ...option,
    })

    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    // 容器宽度随抽屉/侧栏变化时也要重排（ResizeObserver 比 window resize 准）
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)

    return () => {
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [option])

  return (
    <div
      ref={ref}
      role="img"
      aria-label={ariaLabel}
      className={cn('w-full', className)}
      style={{ height }}
    />
  )
}
