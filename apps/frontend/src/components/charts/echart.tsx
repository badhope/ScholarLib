import { useEffect, useRef } from 'react'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import { cn } from '@/lib/utils'

// ECharts 只在指标页/后台图表真正渲染时才加载，避免首页被 579K 的图表库拖慢。
type EChartsCore = typeof import('echarts/core')
let echartsPromise: Promise<EChartsCore> | null = null

function loadEcharts(): Promise<EChartsCore> {
  if (!echartsPromise) {
    echartsPromise = Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ]).then(([core, charts, components, renderers]) => {
      core.use([
        charts.BarChart,
        charts.LineChart,
        charts.PieChart,
        charts.RadarChart,
        charts.ScatterChart,
        components.GridComponent,
        components.LegendComponent,
        components.TooltipComponent,
        components.DatasetComponent,
        components.MarkLineComponent,
        components.MarkPointComponent,
        renderers.CanvasRenderer,
      ])
      return core
    })
  }
  return echartsPromise
}

export type EChartOption = EChartsCoreOption

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
  const chartRef = useRef<ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    let disposed = false
    let chart: ECharts | null = null
    let ro: ResizeObserver | null = null
    const onResize = () => chart?.resize()

    loadEcharts().then((echarts) => {
      if (disposed || !ref.current) return
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      chart = echarts.init(ref.current, undefined, { renderer: 'canvas' })
      chartRef.current = chart
      chart.setOption({
        color: PALETTE,
        animation: !reduce,
        animationDuration: reduce ? 0 : 700,
        animationEasing: 'cubicOut',
        textStyle: { fontFamily: "'Noto Serif SC Site', 'DejaVu Serif', serif", fontSize: 12 },
        grid: { left: 8, right: 12, top: 28, bottom: 8, containLabel: true },
        tooltip: { trigger: 'axis', confine: true },
        ...option,
      })
      window.addEventListener('resize', onResize)
      ro = new ResizeObserver(() => chart?.resize())
      ro.observe(ref.current)
    })

    return () => {
      disposed = true
      window.removeEventListener('resize', onResize)
      ro?.disconnect()
      chart?.dispose()
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
