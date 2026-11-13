import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface PublicProfileUser {
  id: number
  username: string
  display_name: string | null
  avatar_url: string | null
  banner_url: string | null
  accent_color: string
  bio: string | null
  affiliation: string | null
  department: string | null
  academic_title: string | null
  research_interests: string | null
  location: string | null
  website: string | null
  google_scholar: string | null
  orcid: string | null
  contact_email: string | null
  created_at: string | null
}

export interface PublicProfileWork {
  id: number
  title: string
  type: string
  cover_image: string | null
  published_at: string | null
  authors: string[]
  discipline: string
}

export interface PublicProfileTopic {
  id: number
  title: string
  category: string
  reply_count: number
  created_at: string
}

export interface PublicProfileBadge {
  key: string
  name: string
  tier: string
  category: string
  description: string
}

export interface PublicProfile {
  user: PublicProfileUser
  is_owner: boolean
  following: boolean
  stats: {
    works: number
    forum_topics: number
    forum_replies: number
    followers: number
    following: number
    badges: number
  }
  works: PublicProfileWork[]
  topics: PublicProfileTopic[]
  badges: PublicProfileBadge[]
}

export function profileKey(username: string) {
  return ['public-profile', username] as const
}

export function usePublicProfile(username: string, enabled = true) {
  return useQuery({
    queryKey: profileKey(username),
    queryFn: async () => (
      await api.get<PublicProfile>(`/users/${encodeURIComponent(username)}/public`)
    ).data,
    enabled: enabled && Boolean(username),
    // 主页资料是“活的”：别人刚改完头像/名字，公开页不能靠 30 秒缓存装看不见。
    // 本页打开期间 15 秒轻量轮询一次；保存后还会主动失效，本人立即看到。
    staleTime: 5_000,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    retry: false,
  })
}
