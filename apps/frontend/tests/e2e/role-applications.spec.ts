import { test, expect } from '@playwright/test'
import {
  ADMIN,
  loginViaUi,
  nextTestUser,
  registerAndVerifyViaUi,
  openSubmissionForm,
  fillSubmissionWizard,
} from './helpers'

// 1.7.0 — 个人简介（settings → 资料）与职员角色申请（L5/L6）通道。
//
// 断言范围刻意不依赖「已录用稿件 + RQS」这类需要跨角色造的数据：
// 资格门槛的完整判定由后端 tests/test_role_applications.py 覆盖，
// 这里只验证前端能否把资格状态、申请入口、审批队列、拒绝弹窗正确渲染。

test.describe('profile bio', () => {
  test('user can save a bio and see it on the profile card', async ({ page }) => {
    const user = nextTestUser('bio')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto('/settings')
    await page.getByRole('tab', { name: '资料' }).click()
    const textarea = page.locator('#profile-bio')
    await textarea.fill('荒诞现象业余观测者，正经赛道在读研究生。')
    await page.getByRole('button', { name: '保存主页' }).click()
    await expect(page.getByText('主页资料已保存')).toBeVisible({ timeout: 5_000 })

    // 刷新后仍能读到：说明落库，而不是只活在前端 state
    await page.reload()
    await expect(textarea).toHaveValue('荒诞现象业余观测者，正经赛道在读研究生。')

    await page.goto('/me')
    await expect(page.getByText('荒诞现象业余观测者，正经赛道在读研究生。')).toBeVisible({ timeout: 10_000 })
  })

  test('clearing the bio removes it from the profile card', async ({ page }) => {
    const user = nextTestUser('bioclr')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto('/settings')
    const textarea = page.locator('#profile-bio')
    await textarea.fill('先写一句。')
    await page.getByRole('button', { name: '保存主页' }).click()
    await expect(page.getByText('主页资料已保存')).toBeVisible({ timeout: 5_000 })

    await textarea.fill('')
    await page.getByRole('button', { name: '保存主页' }).click()
    await expect(page.getByText('主页资料已保存')).toBeVisible({ timeout: 5_000 })

    await page.goto('/me')
    await expect(page.getByText('先写一句。')).toHaveCount(0)
  })
})

test.describe('role applications', () => {
  test('new user sees the frozen L5/L6 criteria as not yet eligible', async ({ page }) => {
    const user = nextTestUser('roleapp')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto('/levels')
    await expect(page.getByRole('heading', { name: '申请审稿人' })).toBeVisible()
    // 两条通道都在，且都显示未达标（新账号没有录用稿 / 审稿记录）
    await expect(page.getByText('审稿人（L5）')).toBeVisible()
    await expect(page.getByText('资深审稿人（L6）')).toBeVisible()
    await expect(page.getByRole('button', { name: '资格未达标' }).first()).toBeDisabled()
  })

  test('guest sees a login prompt instead of the application form', async ({ page }) => {
    await page.goto('/levels')
    const section = page.locator('section', {
      has: page.getByRole('heading', { name: '申请审稿人' }),
    })
    await expect(section).toBeVisible()
    // 页面上有多处「去登录」（签到区 + 申请区），锚定申请区内那一个
    await expect(section.getByRole('link', { name: '去登录' })).toBeVisible()
    await expect(page.getByRole('button', { name: '资格未达标' })).toHaveCount(0)
  })

  test('admin queue renders Chinese status chips and the reject dialog', async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await page.goto('/admin/role-applications')
    await expect(page.getByRole('heading', { name: '角色申请审批' })).toBeVisible()
    // 状态筛选按钮用中文标签，而不是原始 status 值
    await expect(page.getByRole('button', { name: '待审' })).toBeVisible()
    await expect(page.getByRole('button', { name: '已通过' })).toBeVisible()
    await expect(page.getByRole('button', { name: '未通过' })).toBeVisible()
    await expect(page.getByRole('button', { name: '全部' })).toBeVisible()
  })

  test('non-admin is redirected away from the queue page', async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    const user = nextTestUser('noqueue')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)
    await page.goto('/admin/role-applications')
    // 已登录但无权 → /403（requireAdminGuard 的既有约定）
    await expect(page).toHaveURL(/\/403/, { timeout: 10_000 })
    await ctx.close()
  })
})

test.describe('1.8.0 投稿零门槛', () => {
  test('fresh L1 user can submit directly after rules ack', async ({ page }) => {
    const user = nextTestUser('opencall')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user) // loginViaUi 里的 ensureAuthorReady = 确认《投稿规范》

    await page.goto('/submissions')
    await openSubmissionForm(page)
    const title = `Open Call ${Date.now()}`
    await fillSubmissionWizard(page, {
      title,
      discipline: 'computer science',
      abstract: '零门槛投稿链路的 E2E 验证摘要。',
      authors: 'Open Call Author',
    })
    await page.getByRole('button', { name: '确认提交' }).click()
    await expect(page.getByText('已提交，等待编辑处理')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(title).first()).toBeVisible()
  })
})
