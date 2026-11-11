import { expect, type Page, type Request } from '@playwright/test'

// E2E 测试共享的辅助函数。每个测试自己通过 UI 登录，避免依赖
// sessionStorage 持久化（zustand persist 的 partialize 只存 token，
// Playwright 的 storageState 不会自动捕获 sessionStorage）。

// F7：per-worker DB 分片后，各 worker 可指向不同后端的 dev-only 端点。
// 默认 :8000（单 lane 兼容）；多 lane 时由 playwright.config.ts 按 worker
// index 注入 E2E_BACKEND_URL 覆盖。
const E2E_BACKEND_URL =
  process.env.E2E_BACKEND_URL ?? 'http://localhost:8000'

// 注意：example.org / example.com 是 RFC 2606 保留域名，但 email-validator
// 默认允许；.test / .example / .invalid / .localhost 会被它拒绝。
const E2E_DOMAIN = 'example.org'

export const ADMIN = {
  username: 'admin',
  password: 'e2e_admin_pw_12345678',
  email: 'admin@e2e.test',
} as const

export interface TestUser {
  email: string
  username: string
  password: string
}

// 用一个全局递增计数器避免多次运行重名冲突
let userCounter = 0
export function nextTestUser(prefix = 'e2e'): TestUser {
  userCounter += 1
  const stamp = `${Date.now().toString(36)}${userCounter}`
  return {
    email: `${prefix}.${stamp}@${E2E_DOMAIN}`,
    username: `${prefix}_${stamp}`.slice(0, 30),
    password: 'Passw0rd!e2e',
  }
}

// 通过 UI 登录。等待 toast.success('登录成功') 或路由跳转。
export async function loginViaUi(
  page: Page,
  creds: { username: string; password: string },
): Promise<void> {
  await primeCookieConsent(page)
  await page.goto('/login')
  await page.getByLabel('用户名或邮箱').fill(creds.username)
  // exact:true 避免"确认密码"等带子串的 label 干扰（注册页就有两个密码框）
  await page.getByLabel('密码', { exact: true }).fill(creds.password)
  await page.getByRole('button', { name: '登录' }).click()
  // 等 dashboard 出现（admin 普通用户都会跳过去）
  await page.waitForURL(/\/dashboard/, { timeout: 15_000 })
  await ensureAuthorReady(page)
  await dismissOnboarding(page)
}

export async function dismissOnboarding(page: Page): Promise<void> {
  const skip = page.getByRole('button', { name: '跳过引导' })
  if (await skip.count()) {
    await skip.click({ timeout: 3_000 })
  }
}

/**
 * 等级体系上线后，新注册用户是 L1：不能评论、不能投稿。
 * E2E 里的"作者"用例假定账号已具备投稿权限，这里直接用页面内
 * sessionStorage 里的 access token 调一次作者引导（幂等，admin 调也无害），
 * 避免每个 spec 都去点个人中心的两步按钮。
 */
export async function ensureAuthorReady(page: Page): Promise<void> {
  const awarded = await page.evaluate(async () => {
    const raw = window.sessionStorage.getItem('rubbish-auth')
    if (!raw) return false
    const token = JSON.parse(raw)?.state?.token
    if (!token) return false
    const res = await fetch('/api/gamification/onboarding/author', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ accept_rules: true }),
    }).catch(() => null)
    return res?.ok ?? false
  })
  // 引导是绕过 UI 直接打 API 的：仪表盘的等级/统计卡把等级当判据，
  // 而 react-query 里的 profile 仍是引导前的 L1 快照。这里刷新一次让
  // 缓存失效，否则「我的投稿」这类按身份渲染的卡片不会出现。
  if (awarded) await page.reload({ waitUntil: 'domcontentloaded' })
}

export async function logoutViaUi(page: Page): Promise<void> {
  // AppShell header 右侧的用户菜单触发按钮：按 aria-label 精确定位。
  // 不能再用「header 里第一个 aria-haspopup=menu」——外观菜单（配色/明暗）
  // 也满足该选择器且排在前面，点开的是调色盘而不是账号菜单。
  // 不用 force:true：Radix DropdownMenuTrigger 依赖 pointerdown 事件，actionability
  // 检查通过才能正确触发打开；force 会绕过部分事件派发。
  const trigger = page.getByRole('button', { name: '账号菜单' })
  await trigger.waitFor({ state: 'visible', timeout: 10_000 })
  await trigger.click()
  // DropdownMenu 是 Radix，渲染 portal 后 menuitem 才出现；
  // waitFor visible 一下再点，避免 menuitem 异步挂载时 click 失败
  const item = page.getByRole('menuitem', { name: '退出登录' })
  await item.waitFor({ state: 'visible', timeout: 10_000 })
  await item.click()
  await page.waitForURL(/\/login/, { timeout: 10_000 })
}

interface OutboxEmail {
  to: string
  subject: string
  body: string
  html: string
}

// E2E 后端在 e2e_run_server.py 中注入了 dev-only /api/dev/email-outbox。
// 该接口返回最近 N 封内存邮件（不持久化、不污染 production）。
export async function fetchEmailOutbox(limit = 5): Promise<OutboxEmail[]> {
  const res = await fetch(
    `${E2E_BACKEND_URL}/api/dev/email-outbox?limit=${limit}`,
  )
  if (!res.ok) throw new Error(`outbox fetch failed: ${res.status}`)
  const json = (await res.json()) as { emails: OutboxEmail[] }
  return json.emails
}

export async function resetEmailOutbox(): Promise<void> {
  await fetch(`${E2E_BACKEND_URL}/api/dev/email-outbox/reset`, {
    method: 'POST',
  }).catch(() => {})
}

// 从邮件正文里提取验证 token，对应 verify-email 路由的 ?token=... 参数。
export function extractVerifyToken(body: string): string | null {
  const m = body.match(/token=([A-Za-z0-9._-]+)/)
  return m ? m[1] : null
}

// 通过 backend dev-only 接口直接置 is_email_verified=true。
// 用于"绕过邮件链接点击"的场景：比如我们只想测登录后的体验，
// 不必每次都走完整的"注册→邮件→点链接"流程。
export async function forceVerifyEmail(email: string): Promise<void> {
  await fetch(`${E2E_BACKEND_URL}/api/dev/verify-email-by-email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
}

// 预置 cookie 同意，让 CookieConsent 横幅在后续所有导航中都不再渲染。
// 横幅本身是 role="dialog"（aria-label="Cookie consent"），若留在页面上，
// 任何 `getByRole('dialog')` 断言都会因 strict mode 命中两个元素而误报。
// E2E 关心的是业务功能，不是 Cookie 同意交互；想测横幅自身时用
// data-testid="cookie-banner" 精确选择器。
export async function primeCookieConsent(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem('rubbish_cookie_consent', 'accepted')
  })
}

// 通过 UI 走完整的注册→邮件→验证流程，返回已验证的用户凭据。
/**
 * 注册页自建算术验证码：从 label 文本解析算式并填答案。
 * 后端在 E2E 里把 captcha_required 压成 false，但前端仍会渲染验证码，
 * 空着会被客户端拦下，所以所有走 UI 注册的用例都要先填。
 */
export async function fillCaptcha(page: Page): Promise<void> {
  const label = page.locator('label[for="captcha"]')
  await label.waitFor({ state: 'visible', timeout: 10_000 })
  await expect
    .poll(
      async () => {
        const text = (await label.textContent()) ?? ''
        return /\d+\s*(?:\+|加)\s*\d+/.test(text) ? text : null
      },
      { timeout: 10_000 },
    )
    .toBeTruthy()
  const text = (await label.textContent()) ?? ''
  const m = text.match(/(\d+)\s*(?:\+|加)\s*(\d+)/)
  if (!m) throw new Error(`cannot parse captcha: ${text}`)
  await page.getByLabel(/验证码/).fill(String(Number(m[1]) + Number(m[2])))
}

/**
 * 给指定用户补 reviewer 角色；不传 username 时处理当前登录用户。
 * 指派审稿人对话框只列持 reviewer 角色且启用的账号，默认 admin 不在候选中。
 */
export async function ensureReviewerRole(page: Page, username?: string): Promise<void> {
  const raw = await page.evaluate(() => sessionStorage.getItem('rubbish-auth'))
  if (!raw) throw new Error('管理员未登录，无法读取 token')
  const token = JSON.parse(raw)?.state?.token as string
  if (!token) throw new Error('sessionStorage 中没有 access token')
  const headers = { Authorization: `Bearer ${token}` }
  const apiBase = new URL('/api', page.url()).toString()
  let userId: number
  if (username) {
    const usersResp = await page.request.get(
      `${apiBase}/admin/users?limit=50&q=${encodeURIComponent(username)}`,
      { headers },
    )
    if (!usersResp.ok()) throw new Error(`查询用户 ${username} 失败: ${usersResp.status()}`)
    const users = await usersResp.json()
    const target = users.find((u: { username: string }) => u.username === username)
    if (!target) throw new Error(`未找到用户 ${username}`)
    userId = target.id
  } else {
    const meResp = await page.request.get(`${apiBase}/users/me`, { headers })
    if (!meResp.ok()) throw new Error(`读取当前用户失败: ${meResp.status()}`)
    userId = (await meResp.json()).id
  }
  const roleResp = await page.request.post(`${apiBase}/admin/users/${userId}/roles`, {
    headers,
    data: { role: 'reviewer' },
  })
  if (!roleResp.ok()) throw new Error(`授予 reviewer 角色失败: ${roleResp.status()}`)
}

export async function ensureAdminReviewerRole(page: Page): Promise<void> {
  await ensureReviewerRole(page)
}

/**
 * 打开「新建投稿」四步表单。1.9.0 起它是独立页面 /submissions/new，
 * 不再是列表页上的 dialog；旧套件的 dialog 断言全部失效。
 */
export async function openSubmissionForm(page: Page): Promise<void> {
  // 每个 context 都可能是复用过的：清掉上一轮留下的投稿草稿，
  // 否则异步草稿恢复会覆盖本用例刚填的题录字段。
  await page.evaluate(() => localStorage.removeItem('submission-wizard-draft-v1'))
  await page.getByRole('button', { name: /新建提交/ }).click()
  await expect(page).toHaveURL(/\/submissions\/new/, { timeout: 10_000 })
  await expect(page.getByRole('heading', { name: '新建投稿' })).toBeVisible()
}

/**
 * 按四步向导填完一条最小可提交稿件：题录 → 正文（含参考文献）→ 作者与三项承诺。
 * 直接提交后回到调用方断言结果。
 */
export async function fillSubmissionWizard(
  page: Page,
  input: {
    title: string
    discipline: string
    abstract: string
    authors: string
    downloadUrl?: string
  },
): Promise<void> {
  await expect(page.getByRole('heading', { name: '新建投稿' })).toBeVisible()
  await page.getByLabel(/^标题/).fill(input.title)
  await page.getByLabel(/^学科/).fill(input.discipline)
  await page.getByLabel(/^摘要/).fill(input.abstract)
  await page.getByLabel(/^关键词/).fill('E2E, 测试')
  await page.getByLabel(/^中图分类号/).fill('TP391')
  await page.getByRole('main').getByRole('button', { name: '下一步' }).click()

  if (input.downloadUrl) {
    await page.evaluate(() => {
      const details = Array.from(document.querySelectorAll('details')).find((node) =>
        node.textContent?.includes('补充材料（代码 / 数据 / 外部链接，可选）'),
      )
      if (!details) throw new Error('未找到补充材料区域')
      details.open = true
    })
    await expect(page.getByLabel('稿件直链')).toBeVisible({ timeout: 5_000 })
    await page.getByLabel('稿件直链').fill(input.downloadUrl)
  }

  await page
    .getByTestId('wizard-body-editor')
    .locator('textarea')
    .fill(`# 1 引言\n\nE2E 正文。\n\n# 参考文献\n\n[1] Rubbish E2E. 2026.`)
  await page.getByRole('main').getByRole('button', { name: '下一步' }).click()

  await page.getByLabel(/作者（逗号分隔/).fill(input.authors)
  for (const label of ['原创性声明', '保密与合规声明', '版权与许可确认']) {
    await page.getByLabel(label).check()
  }
  await page.getByRole('main').getByRole('button', { name: '下一步' }).click()
}

export async function registerAndVerifyViaUi(
  page: Page,
  user: TestUser,
): Promise<void> {
  await primeCookieConsent(page)
  await resetEmailOutbox()
  await page.goto('/register')
  await page.getByLabel('邮箱').fill(user.email)
  await page.getByLabel('用户名').fill(user.username)
  await page.getByLabel('密码', { exact: true }).fill(user.password)
  await page.getByLabel('确认密码').fill(user.password)
  await fillCaptcha(page)
  await page.getByRole('button', { name: '注册' }).click()
  // 注册成功后 toast 显示 "注册成功，请查收邮件完成验证"，跳 /verify-email?email=...
  await page.waitForURL(/\/verify-email/, { timeout: 10_000 })

  // 抓邮件取 token
  const emails = await fetchEmailOutbox(3)
  const mine = emails.find((e) => e.to === user.email)
  if (!mine) throw new Error(`no email captured for ${user.email}`)
  const token = extractVerifyToken(mine.body)
  if (!token) throw new Error(`no token in email body:\n${mine.body}`)

  // 1.5.0 起 verify-email.tsx 见到 ?token= 会立即自动验证并渲染结果卡，
  // 不再有「验证」按钮可点——旧实现在这里等按钮，会让所有走注册流程的
  // 用例 60s 超时。这里改为等结果卡：成功卡（前往登录）或失败卡（验证未通过）。
  await page.goto(`/verify-email?token=${token}`)
  await expect(
    page.getByRole('button', { name: '前往登录' }).or(page.getByText('验证未通过')),
  ).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('验证未通过')).toHaveCount(0)
}

// 等待网络空闲（用于 SPA 跳转后等数据请求完成）
export async function waitForNetworkIdle(page: Page, timeout = 5_000): Promise<void> {
  await page.waitForLoadState('networkidle', { timeout }).catch(() => {})
}

// 抓取指定 URL 模式的请求体（用于断言前端发了正确的 API 请求）
export function captureRequests(page: Page, urlPattern: RegExp): Request[] {
  const captured: Request[] = []
  page.on('request', (req) => {
    if (urlPattern.test(req.url())) captured.push(req)
  })
  return captured
}
