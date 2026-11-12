import { createFileRoute, Link, useSearch } from '@tanstack/react-router'
import { LevelsPage } from './levels'
import { PoliciesPage } from './policies'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/rules')({
  validateSearch: (search: Record<string, unknown>) => ({
    tab: search.tab === 'levels' ? 'levels' : 'policies',
  }),
  component: RulesPage,
})

const TABS = [
  { value: 'policies', label: '政策规范', desc: '投稿、评审、更正与伦理' },
  { value: 'levels', label: '等级与规范', desc: '身份等级、权限与计分口径' },
] as const

function RulesPage() {
  const { tab } = useSearch({ from: '/rules' })
  return (
    <div>
      <div className="mx-auto mb-4 grid max-w-5xl grid-cols-2 gap-2 px-4 pt-6 sm:flex sm:flex-wrap sm:px-6">
        {TABS.map((t) => (
          <Link
            key={t.value}
            to="/rules"
            search={{ tab: t.value }}
            className={cn(
              'rounded-xl border px-3 py-2 text-left transition-colors',
              tab === t.value
                ? 'border-emerald-600 bg-emerald-600 text-white'
                : 'border-input bg-card hover:bg-muted/60',
            )}
          >
            <span className="block text-sm font-medium">{t.label}</span>
            <span className={cn('mt-0.5 block text-[11px]', tab === t.value ? 'text-white/75' : 'text-muted-foreground')}>
              {t.desc}
            </span>
          </Link>
        ))}
      </div>
      {tab === 'levels' ? <LevelsPage /> : <PoliciesPage />}
    </div>
  )
}
