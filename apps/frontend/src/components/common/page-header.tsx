import type { ReactNode } from 'react'

interface Props {
  title: string
  description?: string
  actions?: ReactNode
}

// 页面标题区，所有列表/详情页统一头部
// 窄屏 flex-col：标题在上，actions 在下左对齐；sm+ 横排右对齐
export function PageHeader({ title, description, actions }: Props) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <h1 className="section-title text-xl font-semibold sm:text-2xl">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 sm:shrink-0">{actions}</div>
      )}
    </div>
  )
}
