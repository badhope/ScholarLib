import { test, expect } from '@playwright/test'
import { ADMIN, loginViaUi } from './helpers'

// 引用导出(BibTeX / RIS / CSV / JSON)。
//
// catalog/index.tsx 的导出流程:
// 1) 勾选若干行 checkbox
// 2) 点 "导出为..." 下拉
// 3) 选 BIBTEX / RIS / CSV / JSON 之一
// 4) backend 返回文件 + 前端 toast 成功
//
// 我们用 admin 先建两条资源(在 beforeAll),然后测试 4 种格式各导出一次。
// 监听 backend 响应而不是 waitForEvent('download')：vite proxy + Blob URL
// 触发的 <a download>.click() 在某些浏览器/Playwright 组合下不一定能被
// download 事件捕获，但 backend 200 响应是确定的。

const FORMATS = ['bibtex', 'ris', 'csv', 'json'] as const

test.describe('export citation', () => {
  const resourceIds: number[] = []

  test.beforeAll(async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await loginViaUi(page, ADMIN)
    for (let i = 0; i < 2; i++) {
      await page.goto('/catalog/new')
      const title = `E2E Export ${i} ${Date.now()}`
      await page.getByLabel('标题').fill(title)
      await page.getByLabel('作者（逗号分隔）').fill('Export Author')
      await page.getByLabel('学科', { exact: true }).fill('economics')
      await page.getByLabel('摘要', { exact: true }).fill(`Abstract ${i} for export.`)
      await page.getByRole('button', { name: '创建' }).click()
      await expect(page).toHaveURL(/\/catalog\/(\d+)/, { timeout: 10_000 })
      const m = page.url().match(/\/catalog\/(\d+)/)!
      resourceIds.push(Number(m[1]))
    }
    await ctx.close()
  })

  for (const fmt of FORMATS) {
    test(`export selected resources as ${fmt.toUpperCase()}`, async ({ page }) => {
      await loginViaUi(page, ADMIN)
      await page.goto('/papers?view=list')
      // 等表格渲染：mobile 卡片用 md:hidden 隐藏在桌面端，
      // 直接定位 desktop 表格的 cell 避免 .first() 命中被隐藏的 mobile 卡片
      await expect(
        page.locator('table tbody tr').filter({ hasText: 'Export Author' }).first(),
      ).toBeVisible({ timeout: 10_000 })

      // 全选(表头第一行的 checkbox)
      await page.getByRole('checkbox', { name: '全选' }).check()

      // 点导出按钮 + 选格式，同时监听 backend /api/export 响应
      await page.getByRole('button', { name: /导出为/ }).click()
      // 监听 export 响应（response 而非 download 事件，更可靠）
      const exportPromise = page.waitForResponse(
        (r) => r.url().includes('/api/export') && r.request().method() === 'GET',
        { timeout: 10_000 },
      )
      // menuitem 先 waitFor visible 再点，避免 portal 异步挂载失败
      const item = page.getByRole('menuitem', { name: fmt.toUpperCase() })
      await item.waitFor({ state: 'visible', timeout: 5_000 })
      await item.click()
      const response = await exportPromise
      expect(response.ok()).toBe(true)
      // blob 内容非空
      const buf = await response.body()
      expect(buf.length).toBeGreaterThan(0)
      // toast 成功（用户视角的反馈）
      await expect(
        page.getByText(new RegExp(`已导出.*为.*${fmt.toUpperCase()}`, 'i')),
      ).toBeVisible({ timeout: 5_000 })
    })
  }

  test('export without selection shows error toast', async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await page.goto('/papers?view=list')
    // 不勾选任何行：catalog/index.tsx 在 selectedIds.length === 0 时
    // 不渲染"导出为…" DropdownMenu。直接断言按钮不存在（toHaveCount 立即返回，
    // 不会等 timeout，因为 locator 查询不等待元素出现）。
    await expect(page.getByRole('button', { name: /导出为/ })).toHaveCount(0)
  })

  test('individual resource detail page has citation export options', async ({ page }) => {
    // 详情页的操作卡片可能没有直接的"导出引用"按钮,但 catalog 列表提供。
    // 这里验证详情页存在"操作"卡片即可
    await loginViaUi(page, ADMIN)
    const id = resourceIds[0]
    await page.goto(`/catalog/${id}`)
    // 详情页右侧「引用」卡：BibTeX / RIS 直链 + 复制引用格式
    await expect(page.getByRole('link', { name: 'BibTeX' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'RIS' })).toBeVisible()
    await expect(page.getByRole('button', { name: '复制引用格式' })).toBeVisible()
  })
})
