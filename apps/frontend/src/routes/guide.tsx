import { createFileRoute, Link, useSearch } from '@tanstack/react-router'
import { AuthorsPage } from './authors'
import { HelpPage } from './help'
import { LevelsPage } from './levels'
import { PoliciesPage } from './policies'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/guide')({
  validateSearch: (search: Record<string, unknown>) => ({
    tab:
      search.tab === 'help' || search.tab === 'policies' || search.tab === 'levels'
        ? search.tab
        : 'authors',
  }),
  component: GuidePage,
})

const TABS = [
  { value: 'authors', label: '投稿指南', desc: '栏目、格式、评审与计分' },
  { value: 'help', label: '操作指南', desc: '作者 / 审稿人 / 编辑该点哪里' },
  { value: 'policies', label: '政策规范', desc: '投稿、评审、更正与伦理' },
  { value: 'levels', label: '等级与规范', desc: '身份等级、权限与计分口径' },
] as const

function GuidePage() {
  const { tab } = useSearch({ from: '/guide' })
  return (
    <div>
      <div className="mx-auto mb-4 grid max-w-5xl grid-cols-2 gap-2 px-4 pt-6 sm:flex sm:flex-wrap sm:px-6">
        {TABS.map((t) => (
          <Link
            key={t.value}
            to="/guide"
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
      {tab === 'help' ? (
        <HelpPage />
      ) : tab === 'policies' ? (
        <PoliciesPage />
      ) : tab === 'levels' ? (
        <LevelsPage />
      ) : (
        <AuthorsPage />
      )}
    </div>
  )
}
