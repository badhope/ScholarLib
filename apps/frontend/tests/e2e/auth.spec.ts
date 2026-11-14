import { test, expect } from '@playwright/test'
import {
  ADMIN,
  nextTestUser,
  registerAndVerifyViaUi,
  loginViaUi,
  logoutViaUi,
  forceVerifyEmail,
  fetchEmailOutbox,
  resetEmailOutbox,
  fillCaptcha,
} from './helpers'

// 鉴权全流程:注册 → 邮件验证 → 登录 → 退出。
// 还覆盖密码不一致 / 短密码等客户端校验。

test.describe('auth: register + verify + login + logout', () => {
  test('register flow with email verification, then login', async ({ page }) => {
    const user = nextTestUser('auth')

    // 1) 注册
    await resetEmailOutbox()
    await page.goto('/register')
    // CardTitle 不是 h1/h2，用 text 断言
    await expect(page.getByText('注册', { exact: true }).first()).toBeVisible()
    await page.getByLabel('邮箱').fill(user.email)
    await page.getByLabel('用户名').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByLabel('确认密码').fill(user.password)
    await fillCaptcha(page)
    await page.getByRole('button', { name: '注册' }).click()

    // 跳转到 verify-email
    await expect(page).toHaveURL(/\/verify-email/, { timeout: 10_000 })
    await expect(page.getByText('注册成功，请查收邮件完成验证')).toBeVisible()

    // 2) 抓验证邮件
    const emails = await fetchEmailOutbox(3)
    const mine = emails.find((e) => e.to === user.email)
    expect(mine).toBeTruthy()
    const token = mine!.body.match(/token=([A-Za-z0-9._-]+)/)?.[1]
    expect(token).toBeTruthy()

    // 3) 通过 URL 带 token 进入 verify-email 页面：1.5.0 起带 token 即自动验证，
    //    页面直接渲染结果卡（不再有「验证」按钮）。
    await page.goto(`/verify-email?token=${token}`)
    await expect(page.getByText('验证成功', { exact: true })).toBeVisible({ timeout: 20_000 })

    // 4) 去登录页登录
    await page.getByRole('button', { name: '前往登录' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.getByLabel('用户名或邮箱').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByRole('button', { name: '登录' }).click()

    // 登录成功跳 /dashboard
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 })
    await expect(page.getByRole('heading', { name: '概览' })).toBeVisible()
  })

  test('register rejects mismatched passwords', async ({ page }) => {
    const user = nextTestUser('auth2')
    await page.goto('/register')
    await page.getByLabel('邮箱').fill(user.email)
    await page.getByLabel('用户名').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByLabel('确认密码').fill('Different123')
    await page.getByRole('button', { name: '注册' }).click()
    await expect(page.getByText('两次输入的密码不一致')).toBeVisible({ timeout: 5_000 })
    // 应该还在注册页
    await expect(page).toHaveURL(/\/register$/)
  })

  test('register rejects short password (<8 chars)', async ({ page }) => {
    const user = nextTestUser('auth3')
    await page.goto('/register')
    await page.getByLabel('邮箱').fill(user.email)
    await page.getByLabel('用户名').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill('short1')
    await page.getByLabel('确认密码').fill('short1')
    await page.getByRole('button', { name: '注册' }).click()
    // Input 上设置了 minLength=8，浏览器原生表单校验会先拦截，
    // 根本不会触发 onSubmit 里的 toast('密码至少 8 位')。
    // 因此断言：页面仍停留在 /register，未跳转到 /verify-email。
    await page.waitForTimeout(500)
    await expect(page).toHaveURL(/\/register$/)
  })

  test('cannot login before email is verified', async ({ page }) => {
    const user = nextTestUser('auth4')
    await resetEmailOutbox()
    // 注册但不验证邮箱
    await page.goto('/register')
    await page.getByLabel('邮箱').fill(user.email)
    await page.getByLabel('用户名').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByLabel('确认密码').fill(user.password)
    await fillCaptcha(page)
    await page.getByRole('button', { name: '注册' }).click()
    await expect(page).toHaveURL(/\/verify-email/, { timeout: 10_000 })

    // 直接登录（未验证）—— 期望失败
    await page.goto('/login')
    await page.getByLabel('用户名或邮箱').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByRole('button', { name: '登录' }).click()
    // toast 错误出现（具体文案 backend 决定）
    await expect(page.locator('[data-sonner-toast]')).toBeVisible({ timeout: 5_000 })
  })

  test('admin login + logout cycle', async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await expect(page).toHaveURL(/\/dashboard/)
    // 侧边栏默认只展开当前组；后台入口收在「站点管理」手风琴里。
    await page.getByRole('button', { name: /站点管理/ }).click()
    await page.getByRole('button', { name: /用户与权限/ }).click()
    await expect(page.getByRole('link', { name: /用户管理/ })).toBeVisible()
    await page.getByRole('button', { name: /系统与安全/ }).click()
    await expect(page.getByRole('link', { name: /审计日志/ })).toBeVisible()

    // 退出
    await logoutViaUi(page)
    await expect(page).toHaveURL(/\/login$/)
    // 退出后落在登录页：表单上的「登录」按钮可见（登录页不套顶部栏）
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
    await expect(page.getByRole('link', { name: '注册' }).first()).toBeVisible()
  })

  test('can verify email via resend + verify-email page', async ({ page }) => {
    const user = nextTestUser('auth5')
    // 用 helper 走完整流程，确认 helper 函数本身可用
    await registerAndVerifyViaUi(page, user)
    // 注册 + 验证成功后，应能登录
    await loginViaUi(page, user)
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('forceVerifyEmail backend shortcut also enables login', async ({ page }) => {
    const user = nextTestUser('auth6')
    await resetEmailOutbox()
    // 注册但不通过 UI 验证，改用 backend dev 端点直接置 verified
    await page.goto('/register')
    await page.getByLabel('邮箱').fill(user.email)
    await page.getByLabel('用户名').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByLabel('确认密码').fill(user.password)
    await fillCaptcha(page)
    await page.getByRole('button', { name: '注册' }).click()
    await expect(page).toHaveURL(/\/verify-email/, { timeout: 10_000 })
    await forceVerifyEmail(user.email)

    // 现在应该能登录
    await loginViaUi(page, user)
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
