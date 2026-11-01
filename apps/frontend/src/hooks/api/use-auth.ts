import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { isTwoFactorRequired } from '@/lib/types'
import type {
  ForgotPasswordRequest,
  LoginResponse,
  MessageResponse,
  ResetPasswordRequest,
  ResendVerificationRequest,
  TokenResponse,
  TwoFactorLoginRequest,
  UserCreate,
  UserLogin,
  UserResponse,
  VerifyEmailRequest,
} from '@/lib/types'

export const AUTH_KEY = ['auth'] as const

// 登录后拉一次 /auth/me 拿完整 user（含 is_email_verified）
export function useLogin() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const qc = useQueryClient()
  return useMutation<LoginResponse, Error, UserLogin>({
    mutationFn: async (body) => (await api.post<LoginResponse>('/auth/login', body)).data,
    onSuccess: (data) => {
      // 2FA 账号：这里只拿到 pending_token，真正的 token 由
      // useTwoFactorLogin 在第二步写入。
      if (isTwoFactorRequired(data)) return
      setAuth(data.access_token, {
        id: data.user_id,
        username: data.username,
        is_admin: data.is_admin,
        roles: data.roles ?? [],
      })
      void qc.invalidateQueries({ queryKey: [...AUTH_KEY, 'me'] })
    },
  })
}

// 2FA 第二步：pending token + TOTP/恢复码 → 正式 token
export function useTwoFactorLogin() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const qc = useQueryClient()
  return useMutation<TokenResponse, Error, TwoFactorLoginRequest>({
    mutationFn: async (body) =>
      (await api.post<TokenResponse>('/auth/login/2fa', body)).data,
    onSuccess: (data) => {
      // 2FA 中途态不存 token，留给 /auth/2fa/authenticate 处理
      if (data.requires_2fa) return
      setAuth(data.access_token, {
        id: data.user_id,
        username: data.username,
        is_admin: data.is_admin,
        roles: data.roles ?? [],
      })
      void qc.invalidateQueries({ queryKey: [...AUTH_KEY, 'me'] })
    },
  })
}

export function useRegister() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const qc = useQueryClient()
  return useMutation<TokenResponse | MessageResponse, Error, UserCreate>({
    mutationFn: async (body) =>
      (await api.post<TokenResponse | MessageResponse>('/auth/register', body)).data,
    onSuccess: (data) => {
      if (!('access_token' in data) || !data.access_token) return
      setAuth(data.access_token, {
        id: data.user_id,
        username: data.username,
        is_admin: data.is_admin,
        roles: data.roles ?? [],
      })
      void qc.invalidateQueries({ queryKey: [...AUTH_KEY, 'me'] })
    },
  })
}

export function useLogout() {
  const logout = useAuthStore((s) => s.logout)
  const qc = useQueryClient()
  return useMutation<void, Error, void>({
    mutationFn: async () => {
      await api.post('/auth/logout')
    },
    onSettled: () => {
      logout()
      // 清空所有缓存，避免上一个用户的数据残留
      void qc.clear()
    },
  })
}

export function useVerifyEmail() {
  return useMutation<MessageResponse, Error, VerifyEmailRequest>({
    mutationFn: async (body) =>
      (await api.post<MessageResponse>('/auth/verify-email', body)).data,
  })
}

export function useResendVerification() {
  return useMutation<MessageResponse, Error, ResendVerificationRequest>({
    mutationFn: async (body) =>
      (await api.post<MessageResponse>('/auth/resend-verification', body)).data,
  })
}

export function useForgotPassword() {
  return useMutation<MessageResponse, Error, ForgotPasswordRequest>({
    mutationFn: async (body) =>
      (await api.post<MessageResponse>('/auth/forgot-password', body)).data,
  })
}

export function useResetPassword() {
  return useMutation<MessageResponse, Error, ResetPasswordRequest>({
    mutationFn: async (body) =>
      (await api.post<MessageResponse>('/auth/reset-password', body)).data,
  })
}

export function useChangePassword() {
  return useMutation<void, Error, { oldPassword: string; newPassword: string }>({
    mutationFn: async ({ oldPassword, newPassword }) => {
      await api.post('/users/me/password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
    },
  })
}

// 完整个人资料（含 bio 简介）：设置页与个人中心共用。
export function useMe(enabled = true) {
  return useQuery({
    queryKey: [...AUTH_KEY, 'me', 'profile'],
    queryFn: async () => (await api.get<UserResponse>('/users/me')).data,
    enabled,
    staleTime: 60_000,
  })
}

// 一句话简介：PATCH /users/me 的 bio 字段（空串 = 清除）。
export function useUpdateBio() {
  const qc = useQueryClient()
  return useMutation<UserResponse, Error, { bio: string | null }>({
    mutationFn: async (body) => (await api.patch<UserResponse>('/users/me', body)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...AUTH_KEY, 'me'] })
    },
  })
}
