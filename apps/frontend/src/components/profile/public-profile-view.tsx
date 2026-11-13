import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import {
  Award,
  BookOpen,
  Building2,
  CalendarDays,
  Globe2,
  Mail,
  MapPin,
  MessageSquareText,
  Users,
} from 'lucide-react'
import type { PublicProfile } from '@/hooks/api/use-profile'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

function fmtDate(value: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
}

const STAT_ITEMS = [
  { key: 'works', label: '作品', icon: BookOpen },
  { key: 'forum_topics', label: '帖子', icon: MessageSquareText },
  { key: 'followers', label: '关注者', icon: Users },
  { key: 'badges', label: '徽章', icon: Award },
] as const

export function PublicProfileView({
  profile,
  actions,
  footer,
}: {
  profile: PublicProfile
  actions?: ReactNode
  footer?: ReactNode
}) {
  const user = profile.user
  const accent = user.accent_color || '#2f5d46'
  const name = user.display_name || user.username
  const links = [
    user.website
      ? { href: user.website, label: '个人主页', icon: Globe2 }
      : null,
    user.google_scholar
      ? { href: user.google_scholar, label: 'Google Scholar', icon: BookOpen }
      : null,
    user.contact_email
      ? { href: `mailto:${user.contact_email}`, label: user.contact_email, icon: Mail }
      : null,
    user.orcid
      ? { href: `https://orcid.org/${user.orcid}`, label: `ORCID ${user.orcid}`, icon: Award }
      : null,
  ].filter(Boolean) as Array<{ href: string; label: string; icon: typeof Globe2 }>

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <div className="relative h-32 sm:h-44" style={{ backgroundColor: `${accent}18` }}>
          {user.banner_url ? (
            <img src={user.banner_url} alt="" className="h-full w-full object-cover" />
          ) : (
            <div
              className="h-full w-full"
              style={{
                background: `radial-gradient(circle at 18% 20%, ${accent}55 0, transparent 38%), linear-gradient(120deg, ${accent}22, ${accent}55)`,
              }}
            />
          )}
          {actions ? <div className="absolute right-3 top-3 sm:right-5 sm:top-5">{actions}</div> : null}
        </div>
        <CardContent className="relative px-4 pb-5 sm:px-6">
          <div className="-mt-10 flex items-end gap-4 sm:-mt-12">
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={`${name} 的头像`}
                className="h-20 w-20 shrink-0 rounded-full border-4 border-card object-cover shadow-sm sm:h-24 sm:w-24"
              />
            ) : (
              <span
                className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-4 border-card text-2xl font-semibold text-white shadow-sm sm:h-24 sm:w-24"
                style={{ backgroundColor: accent }}
              >
                {name.slice(0, 1)}
              </span>
            )}
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-semibold sm:text-2xl">{name}</h1>
                {profile.is_owner ? <Badge variant="outline">我的主页</Badge> : null}
              </div>
              <p className="mt-0.5 text-sm text-muted-foreground">@{user.username}</p>
              {user.bio ? (
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{user.bio}</p>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">这个人很神秘，还没有写简介。</p>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
            {(user.affiliation || user.department || user.academic_title) && (
              <span className="inline-flex items-center gap-1.5">
                <Building2 className="h-4 w-4" />
                {[user.affiliation, user.department, user.academic_title].filter(Boolean).join(' · ')}
              </span>
            )}
            {user.location && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-4 w-4" />
                {user.location}
              </span>
            )}
            {user.created_at && (
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays className="h-4 w-4" />
                加入于 {fmtDate(user.created_at)}
              </span>
            )}
          </div>

          {links.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {links.map((link) => {
                const Icon = link.icon
                return (
                  <a
                    key={link.href}
                    href={link.href}
                    target={link.href.startsWith('mailto:') ? undefined : '_blank'}
                    rel="noreferrer"
                    className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-background px-3 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {link.label}
                  </a>
                )
              })}
            </div>
          )}

          <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {STAT_ITEMS.map((item) => {
              const Icon = item.icon
              return (
                <div key={item.key} className="rounded-xl border bg-muted/20 px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </div>
                  <p className="mt-1 text-xl font-semibold tabular-nums">{profile.stats[item.key]}</p>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {footer}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <Card>
          <CardContent className="pt-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-base font-semibold">
                <BookOpen className="h-4 w-4" /> 作品
                <Badge variant="secondary">{profile.stats.works}</Badge>
              </h2>
            </div>
            {profile.works.length === 0 ? (
              <p className="rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center text-sm text-muted-foreground">
                还没有已发表作品。投稿录用或认领通过后会出现在这里。
              </p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {profile.works.map((work) => (
                  <Link
                    key={work.id}
                    to="/catalog/$resourceId"
                    params={{ resourceId: String(work.id) }}
                    className="group flex gap-3 rounded-xl border p-3 transition-colors hover:border-primary/40 hover:bg-muted/20"
                  >
                    {work.cover_image ? (
                      <img
                        src={work.cover_image}
                        alt=""
                        className="h-16 w-12 shrink-0 rounded-md object-cover"
                      />
                    ) : (
                      <span className="flex h-16 w-12 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                        <BookOpen className="h-4 w-4" />
                      </span>
                    )}
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-sm font-medium group-hover:text-primary">{work.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {work.type} · {work.discipline}
                        {work.published_at ? ` · ${fmtDate(work.published_at)}` : ''}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-3 pt-5 text-sm">
              <h2 className="font-semibold">关于</h2>
              {user.research_interests ? (
                <div>
                  <p className="text-xs text-muted-foreground">研究兴趣</p>
                  <p className="mt-1 leading-relaxed">{user.research_interests}</p>
                </div>
              ) : (
                <p className="text-muted-foreground">还没有填写研究兴趣。</p>
              )}
              {profile.badges.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground">徽章</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {profile.badges.slice(0, 8).map((badge) => (
                      <span
                        key={badge.key}
                        title={badge.description}
                        className={cn(
                          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                          badge.tier === 'gold'
                            ? 'border-amber-300 bg-amber-50 text-amber-800'
                            : badge.tier === 'silver'
                              ? 'border-slate-300 bg-slate-50 text-slate-700'
                              : 'border-emerald-200 bg-emerald-50 text-emerald-800',
                        )}
                      >
                        <Award className="h-3 w-3" />
                        {badge.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              <h2 className="mb-3 flex items-center gap-2 font-semibold">
                <MessageSquareText className="h-4 w-4" /> 最近发帖
              </h2>
              {profile.topics.length === 0 ? (
                <p className="text-sm text-muted-foreground">还没有在论坛发过帖子。</p>
              ) : (
                <ul className="space-y-2">
                  {profile.topics.map((topic) => (
                    <li key={topic.id}>
                      <Link
                        to="/forum/$topicId"
                        params={{ topicId: String(topic.id) }}
                        className="group block rounded-lg border px-3 py-2 transition-colors hover:border-primary/40 hover:bg-muted/20"
                      >
                        <p className="line-clamp-2 text-sm font-medium group-hover:text-primary">{topic.title}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {topic.category} · {topic.reply_count} 回复 · {fmtDate(topic.created_at)}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
