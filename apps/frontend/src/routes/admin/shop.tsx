import { useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Coins, Package, Plus, Save, ShoppingBag } from 'lucide-react'
import { toast } from 'sonner'
import { requireShopManagerGuard } from '@/lib/route-guards'
import {
  useAdminShopItems,
  useCoinConfig,
  useCreateShopItem,
  useUpdateCoinPolicy,
  useUpdateCoinRule,
  useUpdateShopItem,
  type ShopItem,
} from '@/hooks/api/use-shop'
import { extractError } from '@/lib/utils'
import { PageHeader } from '@/components/common/page-header'
import { Loading } from '@/components/common/state'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export const Route = createFileRoute('/admin/shop')({
  beforeLoad: () => requireShopManagerGuard(),
  component: AdminShopPage,
})

const emptyItem = {
  name: '',
  description: '',
  price_coin: 100,
  stock: '' as string,
  effect: 'none' as 'none' | 'accent_unlock',
  sort_order: 0,
}

function AdminShopPage() {
  const config = useCoinConfig()
  const items = useAdminShopItems()
  const createItem = useCreateShopItem()
  const updateItem = useUpdateShopItem()
  const updateRule = useUpdateCoinRule()
  const updatePolicy = useUpdateCoinPolicy()

  const [policy, setPolicy] = useState({ coin_per_yuan: 100, daily_earn_cap: 5, monthly_issue_cap: 5000 })
  const [ruleEdits, setRuleEdits] = useState<Record<string, { amount: number; daily_cap: number; is_active: boolean }>>({})
  const [newItem, setNewItem] = useState(emptyItem)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editItem, setEditItem] = useState(emptyItem)

  useEffect(() => {
    if (!config.data) return
    setPolicy(config.data.policy)
    const next: Record<string, { amount: number; daily_cap: number; is_active: boolean }> = {}
    for (const rule of config.data.rules) {
      next[rule.reason] = { amount: rule.amount, daily_cap: rule.daily_cap, is_active: rule.is_active }
    }
    setRuleEdits(next)
  }, [config.data])

  const savePolicy = async () => {
    try {
      await updatePolicy.mutateAsync(policy)
      toast.success('发行口径已保存')
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  const saveRule = async (reason: string) => {
    const value = ruleEdits[reason]
    if (!value) return
    try {
      await updateRule.mutateAsync({ reason, ...value })
      toast.success('发放规则已保存')
    } catch (err) {
      toast.error(extractError(err, '保存失败'))
    }
  }

  const submitNewItem = async () => {
    if (!newItem.name.trim()) {
      toast.error('货品名称不能为空')
      return
    }
    try {
      await createItem.mutateAsync({
        name: newItem.name,
        description: newItem.description,
        price_coin: newItem.price_coin,
        stock: newItem.stock === '' ? null : Number(newItem.stock),
        is_active: true,
        sort_order: newItem.sort_order,
        effect: newItem.effect,
        cover_url: null,
      })
      setNewItem(emptyItem)
      toast.success('货品已上架')
    } catch (err) {
      toast.error(extractError(err, '上架失败'))
    }
  }

  const beginEdit = (item: ShopItem) => {
    setEditingId(item.id)
    setEditItem({
      name: item.name,
      description: item.description,
      price_coin: item.price_coin,
      stock: item.stock === null ? '' : String(item.stock),
      effect: item.effect,
      sort_order: item.sort_order,
    })
  }

  const saveEdit = async () => {
    if (editingId === null) return
    try {
      await updateItem.mutateAsync({
        id: editingId,
        name: editItem.name,
        description: editItem.description,
        price_coin: editItem.price_coin,
        stock: editItem.stock === '' ? null : Number(editItem.stock),
        effect: editItem.effect,
        sort_order: editItem.sort_order,
      })
      setEditingId(null)
      toast.success('货品已更新')
    } catch (err) {
      toast.error(extractError(err, '更新失败'))
    }
  }

  const toggleActive = async (item: ShopItem) => {
    try {
      await updateItem.mutateAsync({ id: item.id, is_active: !item.is_active })
      toast.success(item.is_active ? '已下架' : '已上架')
    } catch (err) {
      toast.error(extractError(err, '操作失败'))
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="R 币商城与发行"
        description="R 币是本位稀缺的站内货币：100 R = 1 元购买力。你可以在这里改汇率、每日/月度发行上限、每个动作发多少，以及上架/下架货品。"
      />

      {config.isLoading ? <Loading /> : null}

      {config.data ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Coins className="h-4 w-4" /> 发行口径
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>多少 R = 1 元</Label>
                <Input type="number" min={1} value={policy.coin_per_yuan} onChange={(e) => setPolicy({ ...policy, coin_per_yuan: Number(e.target.value) })} />
              </div>
              <div className="space-y-1.5">
                <Label>日常收入每日上限（R）</Label>
                <Input type="number" min={1} value={policy.daily_earn_cap} onChange={(e) => setPolicy({ ...policy, daily_earn_cap: Number(e.target.value) })} />
              </div>
              <div className="space-y-1.5">
                <Label>全站每月发行上限（R）</Label>
                <Input type="number" min={1} value={policy.monthly_issue_cap} onChange={(e) => setPolicy({ ...policy, monthly_issue_cap: Number(e.target.value) })} />
              </div>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              每日上限只约束签到、发帖等日常收入；审稿、录用、认领、裁决等一次性劳务奖励另计，但仍计入全站月发行上限。
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                本月已发 {config.data.monthly_issued} R（约 ¥{(config.data.monthly_issued / policy.coin_per_yuan).toFixed(2)}）。
                超过月度上限后所有发放自动暂停。
              </p>
              <Button size="sm" onClick={() => void savePolicy()} disabled={updatePolicy.isPending}>
                <Save className="h-4 w-4" /> 保存发行口径
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {config.data ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Coins className="h-4 w-4" /> 每个动作发多少
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {config.data.rules.map((rule) => {
              const edit = ruleEdits[rule.reason] ?? rule
              return (
                <div key={rule.reason} className="grid items-end gap-3 rounded-lg border p-3 sm:grid-cols-[1.4fr_0.8fr_0.8fr_auto]">
                  <div>
                    <p className="text-sm font-medium">{rule.label}</p>
                    <p className="text-xs text-muted-foreground">{rule.reason}</p>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">每次发放</Label>
                    <Input type="number" min={0} value={edit.amount} onChange={(e) => setRuleEdits({ ...ruleEdits, [rule.reason]: { ...edit, amount: Number(e.target.value) } })} />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">每日上限（0 = 不单限）</Label>
                    <Input type="number" min={0} value={edit.daily_cap} onChange={(e) => setRuleEdits({ ...ruleEdits, [rule.reason]: { ...edit, daily_cap: Number(e.target.value) } })} />
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <input type="checkbox" checked={edit.is_active} onChange={(e) => setRuleEdits({ ...ruleEdits, [rule.reason]: { ...edit, is_active: e.target.checked } })} />
                      启用
                    </label>
                    <Button size="sm" variant="outline" onClick={() => void saveRule(rule.reason)} disabled={updateRule.isPending}>
                      保存
                    </Button>
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4" /> 上架新货品
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>名称</Label>
              <Input value={newItem.name} onChange={(e) => setNewItem({ ...newItem, name: e.target.value })} placeholder="例如：主页封面模板" />
            </div>
            <div className="space-y-1.5">
              <Label>价格（R）</Label>
              <Input type="number" min={1} value={newItem.price_coin} onChange={(e) => setNewItem({ ...newItem, price_coin: Number(e.target.value) })} />
            </div>
            <div className="space-y-1.5">
              <Label>库存（留空 = 不限量）</Label>
              <Input type="number" min={0} value={newItem.stock} onChange={(e) => setNewItem({ ...newItem, stock: e.target.value })} placeholder="不限量" />
            </div>
            <div className="space-y-1.5">
              <Label>排序（越小越前）</Label>
              <Input type="number" min={0} value={newItem.sort_order} onChange={(e) => setNewItem({ ...newItem, sort_order: Number(e.target.value) })} />
            </div>
            <div className="space-y-1.5">
              <Label>效果</Label>
              <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={newItem.effect} onChange={(e) => setNewItem({ ...newItem, effect: e.target.value as 'none' | 'accent_unlock' })}>
                <option value="none">人工发货（下单后主编处理）</option>
                <option value="accent_unlock">自动解锁主页主题色</option>
              </select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>说明</Label>
            <Textarea rows={3} value={newItem.description} onChange={(e) => setNewItem({ ...newItem, description: e.target.value })} placeholder="写清买家能得到什么、怎么履约。" />
          </div>
          <Button onClick={() => void submitNewItem()} disabled={createItem.isPending}>
            <ShoppingBag className="h-4 w-4" /> 上架
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Package className="h-4 w-4" /> 在售 / 已下架货品
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {items.isLoading ? <Loading /> : null}
          {items.data?.map((item) => (
            <div key={item.id} className="space-y-3 rounded-xl border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {item.name}
                    <Badge variant={item.is_active ? 'secondary' : 'outline'}>{item.is_active ? '在售' : '已下架'}</Badge>
                    {item.effect === 'accent_unlock' ? <Badge variant="outline">自动发货</Badge> : null}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{item.description || '暂无说明'}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold tabular-nums text-primary">{item.price_coin} R</span>
                  <Button size="sm" variant="outline" onClick={() => beginEdit(item)}>编辑</Button>
                  <Button size="sm" variant="ghost" onClick={() => void toggleActive(item)}>
                    {item.is_active ? '下架' : '上架'}
                  </Button>
                </div>
              </div>

              {editingId === item.id ? (
                <div className="grid gap-3 rounded-lg bg-muted/30 p-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>名称</Label>
                    <Input value={editItem.name} onChange={(e) => setEditItem({ ...editItem, name: e.target.value })} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>价格（R）</Label>
                    <Input type="number" min={1} value={editItem.price_coin} onChange={(e) => setEditItem({ ...editItem, price_coin: Number(e.target.value) })} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>库存（留空 = 不限量）</Label>
                    <Input type="number" min={0} value={editItem.stock} onChange={(e) => setEditItem({ ...editItem, stock: e.target.value })} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>排序</Label>
                    <Input type="number" min={0} value={editItem.sort_order} onChange={(e) => setEditItem({ ...editItem, sort_order: Number(e.target.value) })} />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label>说明</Label>
                    <Textarea rows={2} value={editItem.description} onChange={(e) => setEditItem({ ...editItem, description: e.target.value })} />
                  </div>
                  <div className="flex gap-2 sm:col-span-2">
                    <Button size="sm" onClick={() => void saveEdit()} disabled={updateItem.isPending}>保存</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>取消</Button>
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
