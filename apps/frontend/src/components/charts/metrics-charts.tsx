import type { JournalMetrics } from '@/lib/types'
import { EChart } from './echart'

// 指标页的三张图：把「一列数字」变成「一眼能看出的形状」。
// 口径与数字卡完全一致，只是换了呈现方式——不引入任何新指标。

export function DisciplineBar({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) {
    // 与荒诞环形图同理：空数据时给一张有说明的空态卡，而不是 return null
    // 在三栏网格里留下让读者误以为加载失败的空白卡片。
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center">
        <span className="text-2xl font-semibold text-muted-foreground">—</span>
        <p className="max-w-[16rem] text-xs leading-relaxed text-muted-foreground">
          暂无数据：站内互动与学科分布样本积累中。已有论文刊出后，这里会显示各学科构成。
        </p>
      </div>
    )
  }
  return (
    <EChart
      height={Math.max(170, entries.length * 30 + 30)}
      ariaLabel="各学科已发表论文数条形图"
      option={{
        grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
        xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef2f7' } }, axisLabel: { color: '#8a97a6' } },
        yAxis: {
          type: 'category',
          data: entries.map(([k]) => k),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#5b6b7c' },
        },
        tooltip: { trigger: 'item', formatter: '{b}：{c} 篇' },
        series: [
          {
            type: 'bar',
            data: entries.map(([, v], i) => ({
              value: v,
              itemStyle: { color: ['#2c5aa0', '#c7a24b', '#4e8a6b', '#c96f5e', '#7a6fa8'][i % 5], borderRadius: [0, 4, 4, 0] },
            })),
            barWidth: 16,
            label: { show: true, position: 'right', color: '#5b6b7c', fontSize: 11 },
          },
        ],
      }}
    />
  )
}

export function EngagementRadar({ data }: { data: JournalMetrics }) {
  const values = [
    data.reads_total,
    data.downloads_total,
    data.saves_total,
  ]
  const max = Math.max(...values, 1)
  return (
    <EChart
      height={220}
      ariaLabel="全刊阅读、下载、收藏总量对比图"
      option={{
        tooltip: { trigger: 'item' },
        radar: {
          indicator: [
            { name: '阅读', max },
            { name: '下载', max },
            { name: '收藏', max },
          ],
          radius: '62%',
          axisName: { color: '#5b6b7c', fontSize: 12 },
          splitLine: { lineStyle: { color: '#e6ecf3' } },
          splitArea: { areaStyle: { color: ['#fbfcfe', '#f5f8fc'] } },
          axisLine: { lineStyle: { color: '#e6ecf3' } },
        },
        series: [
          {
            type: 'radar',
            data: [{ value: values, name: '全刊合计' }],
            areaStyle: { color: 'rgba(44,90,160,0.14)' },
            lineStyle: { color: '#2c5aa0', width: 2 },
            itemStyle: { color: '#2c5aa0' },
          },
        ],
      }}
    />
  )
}

export function AbsurdityDonut({ median }: { median: number | null }) {
  // 未评定：给一张有说明的空态卡，而不是 return null（那会在三栏网格里
  // 留一个比邻卡矮一半的空白卡片，读者会以为是加载失败）。
  if (median == null) {
    return (
      <div className="flex h-[180px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center">
        <span className="text-2xl font-semibold text-muted-foreground">—</span>
        <p className="max-w-[16rem] text-xs leading-relaxed text-muted-foreground">
          已刊论文尚未做荒诞指数评定。编辑部完成评定后，这里会显示全刊中位数与分布。
        </p>
      </div>
    )
  }
  const share = Math.max(0, Math.min(100, (median / 10) * 100))
  return (
    <EChart
      height={180}
      ariaLabel={`荒诞指数中位数 ${median.toFixed(1)}，满分 10`}
      option={{
        tooltip: { trigger: 'item', formatter: '{b}：{c}%' },
        series: [
          {
            type: 'pie',
            radius: ['62%', '84%'],
            center: ['50%', '50%'],
            avoidLabelOverlap: false,
            label: {
              show: true,
              position: 'center',
              formatter: () => `{v|${median.toFixed(1)}}\n{s|荒诞指数中位数}`,
              rich: {
                v: { fontSize: 30, fontWeight: 600, color: '#1b2430', fontFamily: 'Georgia, serif', lineHeight: 38 },
                s: { fontSize: 11, color: '#8a97a6', lineHeight: 18 },
              },
            },
            labelLine: { show: false },
            data: [
              { value: Number(share.toFixed(1)), name: '荒诞度', itemStyle: { color: '#c7a24b' } },
              { value: Number((100 - share).toFixed(1)), name: '剩余', itemStyle: { color: '#eef2f7' } },
            ],
          },
        ],
      }}
    />
  )
}
