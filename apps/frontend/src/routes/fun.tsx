import { createFileRoute } from '@tanstack/react-router'
import { CatalogListPage } from './catalog/index'

// 副刊独立入口：不共用论文目录的筛选与学术卡片。
// 页头、文体分栏与格式说明统一由 FunCatalog 承担，外层不再叠一条说明条。
export const Route = createFileRoute('/fun')({
  component: SupplementPage,
})

function SupplementPage() {
  return <CatalogListPage fixedTrack="essay" />
}
