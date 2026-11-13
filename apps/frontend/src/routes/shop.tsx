import { createFileRoute } from '@tanstack/react-router'
import { Coins, QrCode, ShoppingBag, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { useMyPurchases, usePurchaseItem, useShopExchange, useShopItems } from '@/hooks/api/use-shop'
import { useWallet } from '@/hooks/api/use-currency'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export const Route = createFileRoute('/shop')({
  component: ShopPage,
})

function ShopPage() {
  const items = useShopItems()
  const exchange = useShopExchange()
  const wallet = useWallet()
  const purchases = useMyPurchases()
  const buy = usePurchaseItem()

  const handleBuy = async (id: number, name: string) => {
    try {
      const result = await buy.mutateAsync(id)
      toast.success(`已购买「${name}」${result.note ? `：${result.note}` : ''}`)
    } catch (err) {
      toast.error(extractError(err, '购买失败'))
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="R 币商城"
        description="R 币是稀缺的站内货币，100 R = 1 元购买力。可按主编配置的兑换方式申请兑换，也可以直接兑换下列货品。"
      />

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Coins className="h-5 w-5" />
            </span>
            <div>
              <p className="text-xs text-muted-foreground">当前余额</p>
              <p className="text-xl font-semibold tabular-nums text-primary">
                {wallet.data?.balance ?? 0} R
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  ≈ ¥{wallet.data?.balance_yuan?.toFixed(2) ?? '0.00'}
                </span>
              </p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            日常收入每日最多赚 {wallet.data?.daily_earn_cap ?? 5} R；本月全站已发 {wallet.data?.monthly_issued ?? 0} /
            {wallet.data?.monthly_issue_cap ?? 5000} R
          </p>
        </CardContent>
      </Card>

      {exchange.data?.enabled ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <QrCode className="h-4 w-4" /> R 币兑换
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span className="text-muted-foreground">
                兑换比例 <strong className="text-foreground">{exchange.data.coin_per_yuan} R = ¥1</strong>
              </span>
              <span className="text-muted-foreground">
                最低 <strong className="text-foreground">{exchange.data.min_coin} R</strong> 起兑
              </span>
              {exchange.data.method ? <span className="text-muted-foreground">方式：{exchange.data.method}</span> : null}
            </div>
            {exchange.data.note ? (
              <p className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-sm leading-relaxed">{exchange.data.note}</p>
            ) : null}
            {exchange.data.account ? (
              <p className="text-sm">收款账户 / 联系人：<span className="font-medium">{exchange.data.account}</span></p>
            ) : null}
            {exchange.data.qr_url ? (
              <div className="flex flex-wrap items-start gap-4">
                <img src={exchange.data.qr_url} alt="主编配置的收款码" className="h-40 w-40 rounded-lg border bg-white object-contain p-2" />
                <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
                  这是主编在后台配置的收款码，付款前请核对页面上的方式和账户。不要向任何人提供验证码、密码或银行卡信息。
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {items.isLoading ? <Loading /> : null}
      {!items.isLoading && (items.data?.length ?? 0) === 0 ? (
        <EmptyState title="商城还没有上架货品" description="等主编上架后再来看看。" />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.data?.map((item) => {
          const soldOut = item.stock !== null && item.stock <= 0
          return (
            <Card key={item.id} className="overflow-hidden">
              <div className="h-2 bg-primary/60" />
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">{item.name}</CardTitle>
                  {item.effect === 'accent_unlock' ? (
                    <Badge variant="secondary" className="shrink-0 gap-1">
                      <Sparkles className="h-3 w-3" /> 自动
                    </Badge>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="min-h-12 text-sm text-muted-foreground">{item.description || '暂无说明'}</p>
                <div className="flex items-end justify-between gap-2">
                  <div>
                    <p className="text-lg font-semibold tabular-nums text-primary">{item.price_coin} R</p>
                    <p className="text-xs text-muted-foreground">
                      ≈ ¥{(item.price_coin / (wallet.data?.coin_per_yuan ?? 100)).toFixed(2)}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {item.stock === null ? '不限量' : soldOut ? '已售罄' : `剩 ${item.stock} 件`}
                  </p>
                </div>
                <Button
                  className="w-full"
                  variant={soldOut ? 'outline' : 'default'}
                  disabled={soldOut || buy.isPending || (wallet.data?.balance ?? 0) < item.price_coin}
                  onClick={() => void handleBuy(item.id, item.name)}
                >
                  <ShoppingBag className="h-4 w-4" />
                  {soldOut ? '已售罄' : '用 R 币兑换'}
                </Button>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {(purchases.data?.length ?? 0) > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">我的兑换记录</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {purchases.data?.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
                <span>{p.item_name}</span>
                <span className="text-xs text-muted-foreground">{p.note || p.status}</span>
                <span className="tabular-nums text-primary">-{p.price_coin} R</span>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
