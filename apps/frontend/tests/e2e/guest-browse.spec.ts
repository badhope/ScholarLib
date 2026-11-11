import { test, expect } from '@playwright/test'
import { ADMIN } from './helpers'

// 未登录访客的浏览体验。
// 校验:
// - 根路径 / 未登录时展示公开门面页（不重定向，访客可先逛再看）
// - /catalog 与 /catalog/$resourceId 未登录可访问（公开目录 + 公开详情）
// - 详情页对访客开放阅读（0.6.1 起取消登录墙），不显示鉴权专属能力
// - /reader/* 未登录也可直接阅读（进度存本机，登录后跨设备同步）
// - 顶部菜单对未登录用户显示「登录」「注册」按钮

test.describe('guest browse', () => {
  test('root shows public landing page without login', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/$/)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Rubbish', exact: true }),
    ).toBeVisible()
    // 首页有两处「登录」（顶部横幅 + 门面区快捷入口），限定到横幅避免歧义
    await expect(page.getByRole('banner').getByRole('link', { name: '登录' })).toBeVisible()
    await expect(
      page.getByRole('banner').getByRole('link', { name: '注册' }),
    ).toBeVisible()
  })

  test('catalog is publicly visible without login', async ({ page }) => {
    await page.goto('/catalog')
    await expect(page).toHaveURL(/\/catalog$/)
    // 页面 header
    await expect(page.getByRole('heading', { name: '目录', exact: true })).toBeVisible()
    // /catalog 是双轨入口页；论文列表在 /papers。筛选默认收起，
    // 点开后才出现搜索框（1.3.0 起的「先看到一面筛选墙」治理）。
    await page.getByRole('link', { name: '进入论文区' }).click()
    await expect(page).toHaveURL(/\/papers$/)
    await page.getByRole('button', { name: '筛选' }).click()
    await expect(page.getByPlaceholder('标题/作者/摘要')).toBeVisible()
  })

  test('catalog detail is publicly readable for guests without a login wall', async ({
    page,
    request,
  }) => {
    // 用 admin API 造一条资源（详情页需要真实数据；E2E 库启动时为空）
    const apiBase = process.env.E2E_BACKEND_URL ?? 'http://localhost:8000'
    const loginRes = await request.post(`${apiBase}/api/auth/login`, {
      data: { username: ADMIN.username, password: ADMIN.password },
    })
    expect(loginRes.ok()).toBeTruthy()
    const { access_token } = (await loginRes.json()) as { access_token: string }
    const createRes = await request.post(`${apiBase}/api/catalog`, {
      headers: { Authorization: `Bearer ${access_token}` },
      data: {
        slug: `guest-detail-${Date.now().toString(36)}`,
        type: 'paper',
        title: '访客可见的公开论文',
        authors: ['Guest Author'],
        year: 2024,
        discipline: 'Computer Science',
        abstract: '这是一篇用于验证访客可以直接查看目录详情页的测试论文摘要。',
      },
    })
    expect(createRes.ok()).toBeTruthy()
    const { id } = (await createRes.json()) as { id: number }

    // 访客直接访问详情页：不再被挡回 /login
    await page.goto(`/catalog/${id}`)
    await expect(page).toHaveURL(new RegExp(`/catalog/${id}$`))
    await expect(
      page.getByRole('heading', { name: '访客可见的公开论文' }),
    ).toBeVisible()
    // 摘要/元数据可见（preview 会由后端从 abstract 自动填充，文本出现两次，取首个）
    await expect(
      page.getByText('这是一篇用于验证访客可以直接查看目录详情页').first(),
    ).toBeVisible()
    // 0.6.1 起阅读无登录墙：没有 markdown 正文时给出原件/扫描件入口，
    // 有正文时给「在线阅读」；两种都不得出现登录墙文案。
    await expect(
      page.getByText('游客模式：可阅读与下载全部已刊内容。'),
    ).toBeVisible()
    await expect(page.getByText('登录后阅读全文')).toHaveCount(0)
    // 鉴权专属能力（关注/订阅）对访客隐藏
    await expect(page.getByText('关注', { exact: true })).toHaveCount(0)
  })

  test('reader is readable by guests (no login wall)', async ({ page }) => {
    // v5 起 /reader/:id 收敛到文章页 #article 锚点，不再单独保留阅读壳。
    await page.goto('/reader/1')
    await expect(page).toHaveURL(/\/catalog\/1(?:#article)?$/)
  })

  test('dashboard requires login and bounces to /login', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })

  test('library / follows / notifications / submissions / ingest / recommendations require login', async ({ page }) => {
    for (const path of [
      '/library',
      '/follows',
      '/notifications',
      '/submissions',
      '/ingest',
      '/recommendations',
      '/review/assignments',
    ] as const) {
      await page.goto(path)
      await expect(page, `${path} should bounce to /login`).toHaveURL(/\/login/)
    }
  })

  test('admin pages bounce to /login for guests', async ({ page }) => {
    await page.goto('/admin/users')
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/admin/audit-logs')
    await expect(page).toHaveURL(/\/login/)
  })

  test('header shows 登录 + 注册 buttons when not logged in', async ({ page }) => {
    await page.goto('/catalog')
    await expect(page.getByRole('link', { name: '登录' }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: '注册' }).first()).toBeVisible()
  })

  test('login page renders email + password fields and submit button', async ({ page }) => {
    await page.goto('/login')
    // 登录页标题是 CardTitle（非 h1/h2），用 text 断言即可
    await expect(page.getByText('登录', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('选择一种方式登录 Rubbish。')).toBeVisible()
    await expect(page.getByLabel('用户名或邮箱')).toBeVisible()
    await expect(page.getByLabel('密码', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
    // 顶部 header + 卡片底部各有一个"注册"链接，取 first 即卡片里的那个
    await expect(page.getByRole('link', { name: '注册' }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: '忘记密码？' })).toBeVisible()
  })

  test('login with wrong password shows error toast', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('用户名或邮箱').fill(ADMIN.username)
    await page.getByLabel('密码', { exact: true }).fill('totally-wrong-password')
    await page.getByRole('button', { name: '登录' }).click()
    // toast.error 出现（具体文案由 backend 决定，断言部分关键字）
    await expect(page.locator('[data-sonner-toast]')).toBeVisible({ timeout: 5_000 })
  })
})
