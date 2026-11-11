import { test, expect } from '@playwright/test'
import {
  ADMIN,
  nextTestUser,
  registerAndVerifyViaUi,
  loginViaUi,
} from './helpers'

// 阅读器 + 阅读列表 + 关注订阅 完整流程。
//
// 流程:
// 1) admin 创建一条带 download_url 的资源(PDF 视图用 iframe 加载)
// 2) 普通用户注册并验证邮箱
// 3) 进 reader 调进度并保存
// 4) 刷新页面验证进度同步成功(跨设备模拟)
// 5) 跳详情页关注作者 + 订阅学科,在 /follows 页面验证出现
// 6) 创建阅读列表 → 编辑 → 删除

test.describe('reader + library + follows', () => {
  let resourceId: number
  let resourceTitle: string

  test.beforeAll(async ({ browser }) => {
    // admin 一次性建好资源,后续测试复用 resourceId
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await loginViaUi(page, ADMIN)
    await page.goto('/catalog/new')
    resourceTitle = `E2E Reader ${Date.now()}`
    await page.getByLabel('标题').fill(resourceTitle)
    await page.getByLabel('作者（逗号分隔）').fill('Reader Author, Co-Author')
    await page.getByLabel('学科', { exact: true }).fill('computer science')
    await page.getByLabel('子学科').fill('machine learning')
    await page.getByLabel('摘要', { exact: true }).fill('Reader progress sync test.')
    await page.getByLabel('下载链接').fill('https://arxiv.org/pdf/2401.00001')
    await page.getByRole('button', { name: '创建' }).click()
    await expect(page).toHaveURL(/\/catalog\/(\d+)/, { timeout: 10_000 })
    const m = page.url().match(/\/catalog\/(\d+)/)!
    resourceId = Number(m[1])
    await ctx.close()
  })

  test('user can record and persist reading progress', async ({ page }) => {
    test.setTimeout(120_000)
    const user = nextTestUser('reader')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    // 进入阅读页
    await page.goto(`/catalog/${resourceId}#article`)
    await expect(page.getByText(resourceTitle).first()).toBeVisible()
    // 等 progress query 加载完成，避免 useEffect 把 page 覆盖回 1
    await expect(page.getByLabel('页码')).toHaveValue('1')

    // 改页码 + 进度。PDF 以 iframe 加载（E2E 里是远端 arXiv，CI 网络时好时坏），
    // 文档加载完成回调可能把页码钳回真实页数；因此填写改为「填完即断言」，
    // 若被钳回则重填一次，避免把外部网络抖动当成进度功能坏掉。
    const pageInput = page.getByLabel('页码')
    await pageInput.fill('5')
    if ((await pageInput.inputValue()) !== '5') {
      await pageInput.fill('5')
    }
    await page.locator('input[type="range"]').fill('42')
    // 等自动 flush（每 30s）太慢,直接点保存进度按钮
    await page.getByRole('button', { name: '保存进度' }).click()
    await expect(page.getByText('进度已保存')).toBeVisible({ timeout: 5_000 })

    // 刷新页面,验证进度同步
    await page.reload()
    await expect(page.getByLabel('页码')).toHaveValue('5')
    // range input value
    const progressVal = await page.locator('input[type="range"]').inputValue()
    expect(Number(progressVal)).toBe(42)
    // 总时长应该 >0(因为自动累加 + flush)
    const totalMin = await page.getByText('分钟', { exact: false }).first().textContent()
    // 至少有"0 分钟"或更多
    expect(totalMin).toBeTruthy()
  })

  test('detail page shows follow + subscribe buttons for logged-in user', async ({ page }) => {
    test.setTimeout(120_000)
    const user = nextTestUser('follow')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto(`/catalog/${resourceId}`)
    // 关注卡片（CardTitle 非 heading role，用 text 断言）
    await expect(page.getByText('关注', { exact: true }).first()).toBeVisible()
    // exact:true：避免同时匹配到顶部 "Reader Author, Co-Author" 那行作者列表
    await expect(page.locator('#article').getByText('Reader Author', { exact: true })).toBeVisible()
    // 关注 + 订阅按钮
    const followBtn = page.getByRole('button', { name: /^关注$/ }).first()
    await expect(followBtn).toBeVisible()
  })

  test('user can follow author and subscribe discipline, then see them in /follows', async ({ page }) => {
    test.setTimeout(120_000)
    const user = nextTestUser('follow2')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto(`/catalog/${resourceId}`)
    // 关注作者
    const followBtn = page.getByRole('button', { name: /^关注$/ }).first()
    await followBtn.click()
    await expect(page.getByText(/已关注 Reader Author/)).toBeVisible({ timeout: 5_000 })

    // 订阅学科
    const subBtn = page.getByRole('button', { name: /^订阅$/ }).first()
    await subBtn.click()
    await expect(page.getByText(/已订阅 computer science/)).toBeVisible({ timeout: 5_000 })

    // 跳 /follows 验证
    await page.goto('/follows')
    await expect(page.getByText('Reader Author', { exact: true })).toBeVisible()
    // 切换到学科 tab
    await page.getByRole('tab', { name: '我订阅的学科' }).click()
    await expect(page.getByText('computer science', { exact: false })).toBeVisible()

    // 取消关注(回到 authors tab)
    await page.getByRole('tab', { name: '我关注的作者' }).click()
    await page.getByRole('button', { name: /取消关注/ }).click()
    await expect(page.getByText(/已取消关注 Reader Author/)).toBeVisible({ timeout: 5_000 })
  })

  test('reading list CRUD', async ({ page }) => {
    test.setTimeout(120_000)
    const user = nextTestUser('list')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    await page.goto('/library')
    // 初始为空
    await expect(page.getByText('暂无阅读列表')).toBeVisible()

    // 新建
    await page.getByRole('button', { name: /新建列表/ }).first().click()
    // DialogTitle 是 h2，用 heading role 精确匹配避免和按钮文本冲突
    await expect(page.getByRole('heading', { name: '新建列表' })).toBeVisible()
    const listName = `My List ${Date.now()}`
    await page.getByLabel('名称').fill(listName)
    await page.getByLabel('描述（选填）').fill('Created by E2E')
    await page.getByRole('button', { name: '创建' }).click()
    await expect(page.getByText('已创建')).toBeVisible({ timeout: 5_000 })

    // 列表出现
    await expect(page.getByRole('link', { name: listName })).toBeVisible()
    await expect(page.getByText('Created by E2E')).toBeVisible()

    // 编辑：用 aria-label 精确定位到列表卡片上的 dropdown trigger
    // （AppShell 的用户菜单也用 data-slot="dropdown-menu-trigger"，会先匹配到）
    await page.getByRole('button', { name: `列表操作：${listName}` }).click()
    await page.getByRole('menuitem', { name: '编辑' }).click()
    const newName = `${listName} v2`
    await page.getByLabel('名称').fill(newName)
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('已更新')).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('link', { name: newName })).toBeVisible()

    // 删除（重新定位 trigger，新名字会改变 aria-label）
    await page.getByRole('button', { name: `列表操作：${newName}` }).click()
    await page.getByRole('menuitem', { name: '删除' }).click()
    // ConfirmDialog
    await page.getByRole('button', { name: '删除', exact: true }).click()
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('暂无阅读列表')).toBeVisible()
  })

  test('reader remove history button clears the reading record', async ({ page }) => {
    test.setTimeout(120_000)
    const user = nextTestUser('reader2')
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    // 先记一条进度
    await page.goto(`/catalog/${resourceId}#article`)
    await page.getByLabel('页码').fill('1')
    await page.getByRole('button', { name: '保存进度' }).click()
    await expect(page.getByText('进度已保存')).toBeVisible({ timeout: 5_000 })

    // 移除阅读历史：当前按钮直接执行并导航到 /library
    await page.getByRole('button', { name: '移除阅读历史' }).click()
    await expect(page.getByText('已从阅读历史移除')).toBeVisible({ timeout: 5_000 })
    await expect(page).toHaveURL(/\/library$/, { timeout: 10_000 })
  })
})
