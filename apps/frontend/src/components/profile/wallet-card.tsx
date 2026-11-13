import { Link } from '@tanstack/react-router'
import { Coins, Flame, LockKeyhole, ShoppingBag, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { useCheckin, useUnlockAccent, useWallet } from '@/hooks/api/use-currency'
import { extractError } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function WalletCard() {
  const wallet = useWallet()
  const checkin = useCheckin()
  const unlock = useUnlockAccent()
  const data = wallet.data
  const checkinRule = data?.rules.find((r) => r.reason === 'checkin.daily')

  const doCheckin = async () => {
    try {
      await checkin.mutateAsync()
      toast.success('签到成功，R 币已到账')
    } catch (err) {
      toast.error(extractError(err, '签到失败'))
    }
  }

  const doUnlock = async () => {
    try {
      await unlock.mutateAsync()
      toast.success('已解锁自定义主题色')
    } catch (err) {
      toast.error(extractError(err, 'R 币不足，先签到或发帖攒币'))
    }
  }

  if (wallet.isLoading) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">正在加载 R 币钱包…</CardContent>
      </Card>
    )
  }
  if (!data) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Coins className="h-4 w-4" /> R 币钱包
          </CardTitle>
          <Button
            size="sm"
            onClick={() => void doCheckin()}
            disabled={checkin.isPending || data.checked_in_today}
          >
            <Flame className="h-4 w-4" />
            {data.checked_in_today ? '今日已签到' : `签到 +${checkinRule?.amount ?? 1}`}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl bg-primary/10 px-4 py-3">
            <p className="text-xs text-muted-foreground">当前余额</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-primary">{data.balance}</p>
            <p className="text-xs text-muted-foreground">
              R 币 · 约 ¥{data.balance_yuan.toFixed(2)}（{data.coin_per_yuan} R = ¥1）
            </p>
          </div>
          <div className="rounded-xl border px-4 py-3">
            <p className="text-xs text-muted-foreground">连续签到</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{data.streak} 天</p>
            <p className="text-xs text-muted-foreground">累计 {data.total_checkins} 次</p>
          </div>
          <div className="rounded-xl border px-4 py-3">
            <p className="text-xs text-muted-foreground">累计收入</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{data.total_earned}</p>
            <p className="text-xs text-muted-foreground">不含消费</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 px-3 py-2.5 text-sm">
          {data.accent_unlocked ? (
            <>
              <Sparkles className="h-4 w-4 text-primary" />
              <span>自定义主题色已解锁</span>
              <Link to="/settings" search={{ tab: 'profile' }} className="ml-auto text-xs text-primary hover:underline">
                去换色
              </Link>
            </>
          ) : (
            <>
              <LockKeyhole className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">自定义主题色未解锁（{data.accent_cost} R 币）</span>
              <Button
                size="sm"
                variant="outline"
                className="ml-auto"
                onClick={() => void doUnlock()}
                disabled={unlock.isPending || data.balance < data.accent_cost}
              >
                解锁
              </Button>
            </>
          )}
        </div>

        <div className="grid gap-1.5 sm:grid-cols-2">
          {data.rules.map((rule) => (
            <div key={rule.reason} className="flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-xs">
              <span className="truncate text-muted-foreground">{rule.label}</span>
              <span className="shrink-0 font-medium tabular-nums text-primary">
                {rule.amount > 0 ? `+${rule.amount}` : '暂停'}
              </span>
            </div>
          ))}
        </div>

        {data.recent.length > 0 && (
          <div className="border-t pt-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">最近流水</p>
            <ul className="divide-y text-xs">
              {data.recent.slice(0, 6).map((event, index) => (
                <li key={index} className="flex items-center justify-between gap-3 py-1.5">
                  <span className="min-w-0 truncate text-muted-foreground">{event.label}</span>
                  <span className={event.delta > 0 ? 'shrink-0 tabular-nums text-primary' : 'shrink-0 tabular-nums text-destructive'}>
                    {event.delta > 0 ? `+${event.delta}` : event.delta}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          <span>
            发行锚：{data.coin_per_yuan} R = ¥1；单用户每日最多 {data.daily_earn_cap} R，全站本月已发{' '}
            {data.monthly_issued}/{data.monthly_issue_cap} R。
          </span>
          <Link to="/shop" className="inline-flex items-center gap-1 text-primary hover:underline">
            <ShoppingBag className="h-3.5 w-3.5" /> 去商城
          </Link>
        </div>

        <p className="text-xs text-muted-foreground">
          R 币是站内可消费货币，与等级积分分开：积分只升不降、不换权限；R 币不充值、不提现、不转账，只能买商城货品。
        </p>
      </CardContent>
    </Card>
  )
}
