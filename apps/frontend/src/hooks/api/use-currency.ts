import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export interface CurrencyEvent {
  reason: string
  label: string
  delta: number
  note: string | null
  created_at: string
}

export interface CoinRuleView {
  reason: string
  label: string
  amount: number
  daily_cap: number
  is_active: boolean
}

export interface CurrencySummary {
  balance: number
  balance_yuan: number
  coin_per_yuan: number
  daily_earn_cap: number
  monthly_issue_cap: number
  monthly_issued: number
  checked_in_today: boolean
  streak: number
  total_checkins: number
  total_earned: number
  accent_unlocked: boolean
  accent_cost: number
  rules: CoinRuleView[]
  recent: CurrencyEvent[]
}

export function useWallet() {
  return useQuery({
    queryKey: ['gamification', 'wallet'],
    queryFn: async () => (await api.get<CurrencySummary>('/gamification/wallet')).data,
    staleTime: 15_000,
  })
}

export function useCheckin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<CurrencySummary>('/gamification/wallet/checkin')).data,
    onSuccess: (data) => {
      qc.setQueryData(['gamification', 'wallet'], data)
      void qc.invalidateQueries({ queryKey: ['gamification'] })
    },
  })
}

export function useUnlockAccent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (await api.post<{ unlocked: boolean; balance: number }>(
        '/gamification/wallet/unlock-accent',
      )).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['gamification', 'wallet'] })
      void qc.invalidateQueries({ queryKey: ['auth'] })
    },
  })
}
