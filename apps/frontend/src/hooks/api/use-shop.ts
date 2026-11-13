import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface ShopItem {
  id: number
  name: string
  description: string
  price_coin: number
  stock: number | null
  is_active: boolean
  sort_order: number
  effect: 'none' | 'accent_unlock'
  cover_url: string | null
}

export interface ShopPurchase {
  id: number
  item_name: string
  price_coin: number
  status: string
  note: string | null
  created_at: string
}

export interface CoinConfig {
  policy: { coin_per_yuan: number; daily_earn_cap: number; monthly_issue_cap: number }
  rules: Array<{ reason: string; label: string; amount: number; daily_cap: number; is_active: boolean }>
  monthly_issued: number
}

export function useShopItems() {
  return useQuery({
    queryKey: ['shop', 'items'],
    queryFn: async () => (await api.get<{ data: ShopItem[] }>('/gamification/shop/items')).data.data,
    staleTime: 15_000,
  })
}

export function useMyPurchases() {
  return useQuery({
    queryKey: ['shop', 'purchases'],
    queryFn: async () => (await api.get<{ data: ShopPurchase[] }>('/gamification/shop/purchases')).data.data,
  })
}

export function usePurchaseItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<{ balance: number; status: string; note: string }>(`/gamification/shop/items/${id}/purchase`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['gamification', 'wallet'] })
      void qc.invalidateQueries({ queryKey: ['gamification'] })
      void qc.invalidateQueries({ queryKey: ['auth'] })
      void qc.invalidateQueries({ queryKey: ['shop'] })
    },
  })
}

export function useAdminShopItems() {
  return useQuery({
    queryKey: ['shop', 'admin', 'items'],
    queryFn: async () => (await api.get<{ data: ShopItem[] }>('/gamification/admin/shop/items')).data.data,
  })
}

export function useCreateShopItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: Omit<ShopItem, 'id'>) =>
      (await api.post<ShopItem>('/gamification/admin/shop/items', payload)).data,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['shop'] }),
  })
}

export function useUpdateShopItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: Partial<ShopItem> & { id: number }) =>
      (await api.patch<ShopItem>(`/gamification/admin/shop/items/${id}`, payload)).data,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['shop'] }),
  })
}

export function useCoinConfig() {
  return useQuery({
    queryKey: ['shop', 'admin', 'config'],
    queryFn: async () => (await api.get<CoinConfig>('/gamification/admin/coin/config')).data,
  })
}

export function useUpdateCoinRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ reason, ...payload }: { reason: string; amount: number; daily_cap: number; is_active: boolean }) =>
      (await api.patch(`/gamification/admin/coin/rules/${reason}`, payload)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['shop', 'admin', 'config'] })
      void qc.invalidateQueries({ queryKey: ['gamification', 'wallet'] })
    },
  })
}

export function useUpdateCoinPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { coin_per_yuan: number; daily_earn_cap: number; monthly_issue_cap: number }) =>
      (await api.patch('/gamification/admin/coin/policy', payload)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['shop', 'admin', 'config'] })
      void qc.invalidateQueries({ queryKey: ['gamification', 'wallet'] })
    },
  })
}
