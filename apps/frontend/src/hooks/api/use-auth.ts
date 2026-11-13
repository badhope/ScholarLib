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
  UserProfileUpdate,
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
    onSuccess: (data) => {
      syncProfileCaches(qc, data)
    },
  })
}

/** 资料保存后，把 /me、公开主页和全局侧栏身份卡一起刷新，避免“只有自己看得到”。 */
function syncProfileCaches(
  qc: ReturnType<typeof useQueryClient>,
  data: UserResponse,
) {
  qc.setQueryData([...AUTH_KEY, 'me', 'profile'], data)
  void qc.invalidateQueries({ queryKey: [...AUTH_KEY, 'me'] })
  void qc.invalidateQueries({ queryKey: ['public-profile'] })
  const current = useAuthStore.getState().user
  if (current) {
    useAuthStore.getState().setUser({
      ...current,
      username: data.username,
      display_name: data.display_name ?? null,
      avatar_url: data.avatar_url ?? null,
    })
  }
}

// 完整资料：PATCH /users/me。仅提交本次改动的字段，未提交的字段保持原值。
export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation<UserResponse, Error, UserProfileUpdate>({
    mutationFn: async (body) => (await api.patch<UserResponse>('/users/me', body)).data,
    onSuccess: (data) => {
      syncProfileCaches(qc, data)
    },
  })
}

// --- 邮箱验证码登录 ---

export interface EmailCodeRequestResponse {
  message: string
}

/** 请求 6 位邮箱登录验证码（60 秒节流由后端强制，前端只做倒计时 UX）。 */
export function useRequestEmailCode() {
  return useMutation<EmailCodeRequestResponse, Error, string>({
    mutationFn: async (email) =>
      (await api.post<EmailCodeRequestResponse>('/auth/email-code/request', { email })).data,
  })
}

/** 邮箱 + 验证码换取登录凭据；2FA 账户返回 pending_token 走第二步。 */
export function useVerifyEmailCode() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const qc = useQueryClient()
  return useMutation<LoginResponse, Error, { email: string; code: string }>({
    mutationFn: async ({ email, code }) =>
      (await api.post<LoginResponse>('/auth/email-code/verify', { email, code })).data,
    onSuccess: (data) => {
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
