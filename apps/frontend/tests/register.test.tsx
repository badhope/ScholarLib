import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { RegisterPage } from '@/routes/register'

const { navigate, success, capabilities } = vi.hoisted(() => ({
 navigate: vi.fn(),
 success: vi.fn(),
 capabilities: { emailDelivery: false },
}))

vi.mock('@tanstack/react-router', async (importOriginal) => ({
 ...(await importOriginal<typeof import('@tanstack/react-router')>()),
 createFileRoute: () => (options: unknown) => ({ options }),
 Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
 useNavigate: () => navigate,
}))
vi.mock('sonner', () => ({ toast: { success, error: vi.fn() } }))
vi.mock('@/hooks/use-capabilities', () => ({
 useCapabilities: () => ({
  data: { email_delivery: capabilities.emailDelivery },
  isFetched: true,
 }),
}))

describe('registration response', () => {
 beforeEach(() => {
  vi.restoreAllMocks()
  navigate.mockReset()
  success.mockReset()
  capabilities.emailDelivery = false
  useAuthStore.setState({ token: null, user: null })
 })

 it('does not authenticate or claim automatic login for a message response', async () => {
  vi.spyOn(api, 'post').mockResolvedValue({ data: { message: 'generic response' } })
  render(<QueryClientProvider client={new QueryClient()}><RegisterPage /></QueryClientProvider>)
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('邮箱'), 'test@example.com')
  await user.type(screen.getByLabelText('用户名'), 'testuser')
  await user.type(screen.getByLabelText('密码', { exact: true }), 'password123')
  await user.type(screen.getByLabelText('确认密码'), 'password123')
  await user.click(screen.getByRole('button', { name: '注册' }))
  await waitFor(() => expect(success).toHaveBeenCalled())
  expect(success).not.toHaveBeenCalledWith('注册成功，已自动登录')
  expect(navigate).not.toHaveBeenCalledWith({ to: '/dashboard' })
  expect(navigate).toHaveBeenCalledWith({ to: '/login' })
  expect(useAuthStore.getState().token).toBeNull()
  expect(useAuthStore.getState().user).toBeNull()
 })

 it('sends the user to email verification when delivery is configured', async () => {
  capabilities.emailDelivery = true
  vi.spyOn(api, 'post').mockResolvedValue({ data: { message: 'generic response' } })
  render(<QueryClientProvider client={new QueryClient()}><RegisterPage /></QueryClientProvider>)
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('邮箱'), 'test@example.com')
  await user.type(screen.getByLabelText('用户名'), 'testuser')
  await user.type(screen.getByLabelText('密码', { exact: true }), 'password123')
  await user.type(screen.getByLabelText('确认密码'), 'password123')
  await user.click(screen.getByRole('button', { name: '注册' }))
  await waitFor(() =>
   expect(navigate).toHaveBeenCalledWith({
    to: '/verify-email',
    search: { email: 'test@example.com' },
   }),
  )
  expect(useAuthStore.getState().token).toBeNull()
 })

 it('authenticates and navigates when a token is returned', async () => {
  vi.spyOn(api, 'post').mockResolvedValue({ data: { access_token: 'token', user_id:1, username: 'testuser', is_admin: false, roles: [] } })
  render(<QueryClientProvider client={new QueryClient()}><RegisterPage /></QueryClientProvider>)
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('邮箱'), 'test@example.com')
  await user.type(screen.getByLabelText('用户名'), 'testuser')
  await user.type(screen.getByLabelText('密码', { exact: true }), 'password123')
  await user.type(screen.getByLabelText('确认密码'), 'password123')
  await user.click(screen.getByRole('button', { name: '注册' }))
  await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: '/dashboard' }))
  expect(useAuthStore.getState().token).toBe('token')
 })
})
