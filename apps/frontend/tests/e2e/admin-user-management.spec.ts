import { test, expect } from '@playwright/test'
import {
  ADMIN,
  nextTestUser,
  registerAndVerifyViaUi,
  loginViaUi,
} from './helpers'

// admin 用户管理 + 审计日志。
//
// admin/users.tsx 提供:
// - 搜索框
// - 用户表格(用户名/邮箱/角色/管理员/状态/邮箱验证/注册时间)
// - 每行 dropdown: 启用/禁用账号 + 角色分配 checkbox
//
// admin/audit-logs.tsx 显示管理员操作记录。

test.describe('admin: user management', () => {
  test('admin can search users by username', async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await page.goto('/admin/users')
    await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
    // admin 是 bootstrap 建的最老账号，列表按注册时间倒序分页——
    // E2E 库累积用户后会掉出第一页，所以直接搜索而不是断言首屏可见。
    await page.getByPlaceholder('搜索用户名或邮箱').fill('admin')
    await expect(page.getByText('admin@e2e.test')).toBeVisible()
    // 搜索不存在的用户
    await page.getByPlaceholder('搜索用户名或邮箱').fill('zzz-not-exist-zzz')
    await expect(page.getByText('暂无用户')).toBeVisible()
  })

  test('admin can assign reviewer role to a user and revoke it', async ({ browser }) => {
  test.setTimeout(120_000)
    // 注册一个新用户作为被操作对象
    const targetCtx = await browser.newContext()
    const target = nextTestUser('target')
    const targetPage = await targetCtx.newPage()
    await registerAndVerifyViaUi(targetPage, target)
    await targetCtx.close()

    // admin 登录
    const adminCtx = await browser.newContext()
    const adminPage = await adminCtx.newPage()
    await loginViaUi(adminPage, ADMIN)
    await adminPage.goto('/admin/users')

    // 搜索目标用户
    await adminPage.getByPlaceholder('搜索用户名或邮箱').fill(target.username)
    await expect(adminPage.getByText(target.email)).toBeVisible({ timeout: 5_000 })

    // 打开角色分配 dropdown：用 data-slot 精确定位 trigger，避免 getByRole('')
    // 误匹配其它无 accessible-name 的按钮
    const trigger = adminPage
      .locator('tr', { hasText: target.username })
      .first()
      .getByRole('button', { name: '用户操作' })
    await trigger.click()
    // 点 "审稿人" checkbox item(未选中 → 选中)
    const reviewerItem = adminPage.getByRole('menuitemcheckbox', { name: '审稿人', exact: true })
    await reviewerItem.waitFor({ state: 'visible', timeout: 5_000 })
    await reviewerItem.focus()
    await expect(reviewerItem).toBeFocused()
    await adminPage.keyboard.press('Space')
    await expect(adminPage.getByText('已分配 审稿人 角色')).toBeVisible({ timeout: 5_000 })

    // 等表格刷新,验证 reviewer badge 出现在该行
    await expect(
      adminPage.locator('tr', { hasText: target.username }).getByText('审稿人', { exact: true }),
    ).toBeVisible({ timeout: 5_000 })

    // 撤销角色（重新定位 row + trigger，避免表格 rerender 后旧引用失效）
    // 注意：DropdownMenuCheckboxItem 的 onSelect 调用了 e.preventDefault()
    // 保持 menu 打开，所以第一次 assign 后 menu 仍然在 portal 中渲染并拦截
    // 后续对 trigger 的 pointer events。这里先按 Escape 关闭 menu，再点 trigger2。
    await adminPage.keyboard.press('Escape')
    await expect(reviewerItem).toHaveCount(0, { timeout: 5_000 })

    const trigger2 = adminPage
      .locator('tr', { hasText: target.username })
      .first()
      .getByRole('button', { name: '用户操作' })
    await expect(trigger2).toBeEnabled()
    await trigger2.press('Enter')
    const reviewerItem2 = adminPage.getByRole('menuitemcheckbox', { name: '审稿人', exact: true })
    await reviewerItem2.waitFor({ state: 'visible', timeout: 5_000 })
    await reviewerItem2.focus()
    await expect(reviewerItem2).toBeFocused()
    await adminPage.keyboard.press('Space')
    await expect(adminPage.getByText('已撤销 审稿人 角色')).toBeVisible({ timeout: 5_000 })

    await adminCtx.close()
  })

  test('admin can disable and re-enable a user account', async ({ browser }) => {
  test.setTimeout(120_000)
    const targetCtx = await browser.newContext()
    const target = nextTestUser('disable')
    const targetPage = await targetCtx.newPage()
    await registerAndVerifyViaUi(targetPage, target)
    await targetCtx.close()

    const adminCtx = await browser.newContext()
    const adminPage = await adminCtx.newPage()
    await loginViaUi(adminPage, ADMIN)
    await adminPage.goto('/admin/users')
    await adminPage.getByPlaceholder('搜索用户名或邮箱').fill(target.username)
    await expect(adminPage.getByText(target.email)).toBeVisible()

    const row = adminPage.locator('tr', { hasText: target.username }).first()
    // 初始状态:启用
    await expect(row.getByText('启用')).toBeVisible()

    // 禁用：用 data-slot 精确定位 trigger
    const trigger1 = row.getByRole('button', { name: '用户操作' })
    await trigger1.click()
    const disableItem = adminPage.getByRole('menuitem', { name: '禁用账号' })
    await disableItem.waitFor({ state: 'visible', timeout: 5_000 })
    await disableItem.press('Enter')
    await expect(adminPage.getByText('已禁用')).toBeVisible({ timeout: 5_000 })
    await expect(row.getByText('禁用')).toBeVisible()

    // 禁用后 Radix 菜单已自动关闭，但显式按 Escape + 确认菜单项消失，
    // 避免与同文件 assign-role 测试一致地出现"重新打开时 Radix 内部状态残留"
    // 导致 trigger2.click() 行为异常（实测会导航到 /verify-email 页面）。
    // 参考 assign-role 测试 line 73–74 的稳健写法。
    await adminPage.keyboard.press('Escape')
    await expect(disableItem).toHaveCount(0, { timeout: 5_000 })

    // 再启用（重新定位 row 避免 stale）。
    // trigger2.click() 可能恰好撞上 mutation 触发的表格 refetch 重渲染，
    // 菜单刚打开就随行卸载而关闭（真实用户会自然再点一次）。
    // 用 toPass 重试「点 trigger → 菜单项可见」这一整段，对齐 Playwright
    // 官方对 flaky interaction 的推荐写法。
    const row2 = adminPage.locator('tr', { hasText: target.username }).first()
    const trigger2 = row2.getByRole('button', { name: '用户操作' })
    const enableItem = adminPage.getByRole('menuitem', { name: '启用账号' })
    await expect(async () => {
      await trigger2.click()
      await expect(enableItem).toBeVisible({ timeout: 1_500 })
    }).toPass({ timeout: 15_000 })
    await enableItem.press('Enter')
    await expect(adminPage.getByText('已启用')).toBeVisible({ timeout: 5_000 })
    await expect(row2.getByText('启用')).toBeVisible()

    await adminCtx.close()
  })

  test('admin cannot disable own account (button disabled for self)', async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await page.goto('/admin/users')
    await page.getByPlaceholder('搜索用户名或邮箱').fill('admin')
    // admin 自己那行的操作按钮 disabled
    const row = page.locator('tr', { hasText: 'admin@e2e.test' }).first()
    await expect(row.getByRole('button', { name: '用户操作' })).toBeDisabled()
  })

  test('audit logs page lists recent admin actions', async ({ browser }) => {
  test.setTimeout(120_000)
    // bootstrap 不会写 audit_logs（只有 admin 主动操作才会写），
    // 所以先注册一个目标用户 + admin 给它分配角色，制造一条 audit log。
    const targetCtx = await browser.newContext()
    const target = nextTestUser('audit')
    const targetPage = await targetCtx.newPage()
    await registerAndVerifyViaUi(targetPage, target)
    await targetCtx.close()

    const adminCtx = await browser.newContext()
    const page = await adminCtx.newPage()
    await loginViaUi(page, ADMIN)
    await page.goto('/admin/users')
    await page.getByPlaceholder('搜索用户名或邮箱').fill(target.username)
    await expect(page.getByText(target.email)).toBeVisible({ timeout: 5_000 })

    // 分配审稿人角色 → backend 写一条 audit log (action=user.assign_role)
    const trigger = page
      .locator('tr', { hasText: target.username })
      .first()
      .getByRole('button', { name: '用户操作' })
    await trigger.click()
    const reviewerItem = page.getByRole('menuitemcheckbox', { name: '审稿人', exact: true })
    await reviewerItem.waitFor({ state: 'visible', timeout: 5_000 })
    await reviewerItem.focus()
    await expect(reviewerItem).toBeFocused()
    await page.keyboard.press('Space')
    await expect(page.getByText('已分配 审稿人 角色')).toBeVisible({ timeout: 5_000 })

    // 访问 audit-logs，应该能看到刚产生的 action
    await page.goto('/admin/audit-logs')
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible()
    await expect(page.getByText('user.assign_role').first()).toBeVisible({
      timeout: 10_000,
    })

    await adminCtx.close()
  })

  test('audit logs not accessible to non-admin', async ({ browser }) => {
    const ctx = await browser.newContext()
    const user = nextTestUser('noaudit')
    const page = await ctx.newPage()
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)
    await page.goto('/admin/audit-logs')
    // 已登录但无权 → /403（requireAdminGuard 0.8 起把"未登录"和"越权"分开）
    await expect(page).toHaveURL(/\/403/)
    await ctx.close()
  })
})
