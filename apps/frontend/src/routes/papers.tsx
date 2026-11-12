import { createFileRoute } from '@tanstack/react-router'
import { CatalogListPage } from './catalog/index'

// 论文轨独立入口：URL 与娱乐区分开，导航高亮、分享链接、返回路径都不再
// 依赖 /catalog?track=paper 这种“同一页换参数”的临时状态。
export const Route = createFileRoute('/papers')({
  component: () => <CatalogListPage fixedTrack="paper" />,
})
