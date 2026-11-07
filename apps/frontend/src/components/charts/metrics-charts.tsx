import type { JournalMetrics } from '@/lib/types'
import { EChart } from './echart'

// 指标页的三张图：把「一列数字」变成「一眼能看出的形状」。
// 口径与数字卡完全一致，只是换了呈现方式——不引入任何新指标。

export function DisciplineBar({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) {
    // 空数据时给一张有说明的空态卡，而不是 return null
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
        xAxis: { type: 'value', splitLine: { lineStyle: { color: '#e8efe9' } }, axisLabel: { color: '#8a9a92' } },
        yAxis: {
          type: 'category',
          data: entries.map(([k]) => k),
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#5c6b64' },
        },
        tooltip: { trigger: 'item', formatter: '{b}：{c} 篇' },
        series: [
          {
            type: 'bar',
            data: entries.map(([, v], i) => ({
              value: v,
              itemStyle: { color: ['#2f6b52', '#c7a24b', '#5f9e7d', '#c96f5e', '#3f7d8c'][i % 5], borderRadius: [0, 4, 4, 0] },
            })),
            barWidth: 16,
            label: { show: true, position: 'right', color: '#5c6b64', fontSize: 11 },
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
          axisName: { color: '#5c6b64', fontSize: 12 },
          splitLine: { lineStyle: { color: '#e4ece6' } },
          splitArea: { areaStyle: { color: ['#fbfdfb', '#f4f9f5'] } },
          axisLine: { lineStyle: { color: '#e4ece6' } },
        },
        series: [
          {
            type: 'radar',
            data: [{ value: values, name: '全刊合计' }],
            areaStyle: { color: 'rgba(47,107,82,0.14)' },
            lineStyle: { color: '#2f6b52', width: 2 },
            itemStyle: { color: '#2f6b52' },
          },
        ],
      }}
    />
  )
}
