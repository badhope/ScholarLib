import { createFileRoute, Link } from '@tanstack/react-router'
import { Loader2, UserPlus, UserMinus } from 'lucide-react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { usePublicProfile } from '@/hooks/api/use-profile'
import { useFollowAuthor, useUnfollowAuthor } from '@/hooks/api/use-modules'
import { PublicProfileView } from '@/components/profile/public-profile-view'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { extractError } from '@/lib/utils'

export const Route = createFileRoute('/u/$username')({
  component: PublicProfilePage,
})

function PublicProfilePage() {
  const { username } = Route.useParams()
  const qc = useQueryClient()
  const profile = usePublicProfile(username)
  const follow = useFollowAuthor()
  const unfollow = useUnfollowAuthor()

  if (profile.isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在加载主页…
      </div>
    )
  }

  if (profile.isError || !profile.data) {
    return (
      <Card className="mx-auto max-w-lg">
        <CardContent className="space-y-3 py-10 text-center">
          <h1 className="text-lg font-semibold">这个主页不存在或未公开</h1>
          <p className="text-sm text-muted-foreground">
            用户可能设置了“仅自己可见”，或者这个用户名还没有注册。
          </p>
          <Button asChild variant="outline" size="sm">
            <Link to="/forum">去论坛逛逛</Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  const data = profile.data
  const followName = data.user.display_name || data.user.username
  const toggle = async () => {
    try {
      if (data.following) {
        await unfollow.mutateAsync(followName)
      } else {
        await follow.mutateAsync(followName)
      }
      await qc.invalidateQueries({ queryKey: ['public-profile', username] })
      toast.success(data.following ? '已取消关注' : '已关注，新作品会出现在关注流')
    } catch (err) {
      toast.error(extractError(err, '关注失败'))
    }
  }

  return (
    <PublicProfileView
      profile={data}
      actions={
        data.is_owner ? (
          <Button asChild size="sm" variant="outline">
            <Link to="/me">编辑我的主页</Link>
          </Button>
        ) : (
          <Button
            size="sm"
            variant={data.following ? 'outline' : 'default'}
            onClick={() => void toggle()}
            disabled={follow.isPending || unfollow.isPending}
          >
            {data.following ? <UserMinus className="h-4 w-4" /> : <UserPlus className="h-4 w-4" />}
            {data.following ? '已关注' : '关注'}
          </Button>
        )
      }
    />
  )
}
