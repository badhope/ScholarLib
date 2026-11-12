import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface AuthUser {
  id: number
  username: string
  is_admin: boolean
  // 服务端下发的角色名（reviewer/editor/section_editor/author/reader）。
  // 前端只用来决定导航可见性，真正的权限仍由后端 require_* 依赖强制。
  // 可选：旧版会话缓存里没有这个字段，读取方一律 `?? []`。
  roles?: string[]
  // 资料页要显示「邮箱 / 是否已验证」。登录响应里不一定带，缺了就显示占位，
  // 不为了两个只读字段去多打一次接口。
  email?: string
  is_email_verified?: boolean
  // 个人资料（设置页编辑后由 /users/me 回填；旧缓存可能没有）。
  display_name?: string | null
  real_name?: string | null
  affiliation?: string | null
  department?: string | null
  academic_title?: string | null
  research_interests?: string | null
  website?: string | null
  google_scholar?: string | null
  location?: string | null
  bio?: string | null
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  setAuth: (token: string, user: AuthUser) => void
  setUser: (user: AuthUser) => void
  logout: () => void
}

// Cross-tab logout sync via BroadcastChannel (supported natively in all
// modern browsers; more semantic than the storage event). Other tabs post
// a 'logout' message; this tab clears its local state in response.
const authChannel: BroadcastChannel | null =
  typeof window !== 'undefined' && 'BroadcastChannel' in window
    ? new BroadcastChannel('rubbish-auth')
    : null

if (authChannel) {
  authChannel.onmessage = (e) => {
    if (e.data?.type === 'logout') {
      // Clear local state only; do not re-broadcast (would loop forever).
      useAuthStore.setState({ token: null, user: null })
    }
  }
}

// access_token lives in sessionStorage (cleared when the tab closes) rather
// than localStorage, narrowing the XSS exfiltration window. The refresh_token
// is set by the backend as an httpOnly cookie and never touches JS.
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => {
        // 拒绝空 token：M2 2FA 中途态或后端异常时防止清理过的 token 覆盖会话
        if (!token) {
          set({ token: null, user: null })
          return
        }
        set({ token, user })
      },
      setUser: (user) => set({ user }),
      logout: () => {
        set({ token: null, user: null })
        // Broadcast the logout to other tabs.
        authChannel?.postMessage({ type: 'logout' })
      },
    }),
    {
      name: 'rubbish-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ token: state.token }),
    },
  ),
)

// Snapshot reader for non-React contexts (router beforeLoad, axios
// interceptor) — reads the store directly instead of using the hook.
export function getAuthState() {
  const { token, user } = useAuthStore.getState()
  return {
    token,
    user,
    isAuthenticated: !!token,
    isAdmin: user?.is_admin ?? false,
  }
}
