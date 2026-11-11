import { test as base, expect, type ConsoleMessage, type Page } from '@playwright/test'
import { ADMIN, loginViaUi } from './helpers'

// 移动端专用 E2E（390×844）：验证移动端外壳与五入口信息架构。
const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: async ({ page }, run) => {
    const errors: string[] = []
    const onConsole = (msg: ConsoleMessage) => {
      if (msg.type() === 'error') errors.push(msg.text())
    }
    const onPageError = (err: Error) => errors.push(`pageerror: ${err.message}`)
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    await run(errors)
    const meaningful = errors.filter(
      (e) => !/favicon|Failed to load resource|net::ERR|404 \(Not Found\)/i.test(e),
    )
    expect(meaningful, `移动端 console error: ${meaningful.join(' | ')}`).toEqual([])
  },
})

async function expectDesktopShellAbsent(page: Page) {
  await expect(page.getByRole('button', { name: '打开菜单' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '资源目录', exact: true })).toHaveCount(0)
}

async function createResourceViaUi(page: Page, title: string) {
  await page.goto('/catalog/new')
  await page.getByLabel('标题').fill(title)
  await page.getByLabel('作者（逗号分隔）').fill('Mobile Author')
  await page.getByLabel('学科', { exact: true }).fill('computer science')
  await page.getByLabel('摘要', { exact: true }).fill('Mobile e2e abstract.')
  await page.getByRole('button', { name: '创建' }).click()
  await expect(page).toHaveURL(/\/catalog\/\d+/, { timeout: 10_000 })
}

test.describe('mobile shell · 访客', () => {
  test('公开目录：五个底部 Tab 可见，桌面侧边栏/汉堡不渲染', async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.goto('/catalog')
    await expect(page).toHaveURL(/\/catalog$/)

    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    for (const name of ['首页', '论文', '副刊', '讨论', '我的']) {
      await expect(page.getByRole('button', { name })).toBeVisible()
    }
    await expectDesktopShellAbsent(page)
  })

  test('访客点击“我的”跳转登录页', async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.goto('/catalog')
    await page.getByRole('button', { name: '我的' }).click()
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('mobile shell · 已登录', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, ADMIN)
  })

  test('中心 FAB 可见并跳转到 /ingest', async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.goto('/dashboard')
    const fab = page.getByRole('button', { name: '导入' })
    await expect(fab).toBeVisible()
    await fab.click()
    await expect(page).toHaveURL(/\/ingest/)
    await expectDesktopShellAbsent(page)
  })

  test('仪表盘呈移动 2 列大块 + 快捷操作（非桌面 5 列小卡）', async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.goto('/dashboard')
    await expect(page.getByText('资源总数')).toBeVisible()
    await expect(page.getByText('待审稿件')).toBeVisible()
    const quick = page.getByTestId('mobile-quick-actions')
    await expect(quick.getByRole('link', { name: '浏览目录' })).toBeVisible()
    await expect(quick.getByRole('link', { name: '我的提交' })).toBeVisible()
    await expect(quick.getByRole('link', { name: '推荐' })).toBeVisible()
    await expectDesktopShellAbsent(page)
  })

  test('论文卡片→详情底部操作栏，旧 reader 路由回退到详情页', async ({ page, consoleErrors }) => {
    void consoleErrors
    const title = `E2E Mobile ${Date.now()}`
    await createResourceViaUi(page, title)

    await page.goto(`/papers?q=${encodeURIComponent(title)}`)
    await expect(page.getByRole('heading', { name: '搜索结果' })).toBeVisible()
    await expect(page.getByRole('table')).toHaveCount(0)
    const card = page.getByTestId('catalog-resource-list').getByRole('link', { name: title })
    await expect(card).toBeVisible()
    await card.click()
    await expect(page).toHaveURL(/\/catalog\/\d+/)

    await expect(page.getByRole('button', { name: '收藏' })).toBeVisible()
    await expect(page.getByRole('button', { name: '更多操作' })).toBeVisible()
    await page.getByRole('button', { name: '更多操作' }).click()
    const sheet = page.getByRole('dialog', { name: '更多操作' })
    await expect(sheet).toBeVisible()
    await expect(sheet.getByRole('button', { name: '复制分享链接' })).toBeVisible()
    const sheetBox = await sheet.boundingBox()
    expect(sheetBox!.height).toBeGreaterThan(120)
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()

    const id = page.url().match(/\/catalog\/(\d+)/)?.[1]
    await page.goto(`/reader/${id}`)
    await expect(page).toHaveURL(new RegExp(`/catalog/${id}#article`))
    await expect(page.getByRole('button', { name: '更多操作' })).toBeVisible()
    await expectDesktopShellAbsent(page)
  })
})
