import { createHmac } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { nextTestUser, loginViaUi, registerAndVerifyViaUi } from './helpers'

/**
 * Phase 3.1 全链路：开启 2FA → 登出 → 密码登录被要求二次验证 →
 * 输入 TOTP 码完成登录 → 关闭 2FA 恢复一步登录。
 *
 * TOTP 码在 Node 侧用 crypto 直接算（RFC 6238 / SHA-1 / 30s 步长），
 * 与后端 pyotp 的默认参数完全一致，无需引入额外依赖。
 *
 * 2FA 已归一为单一实现（/api/auth/2fa/* + totp_* 加密列）：账号安全页与
 * 设置页渲染的是同一个 TwoFactorSection 组件，选择器按该组件为准。
 */

function base32Decode(input: string): Buffer {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = 0
  let value = 0
  const bytes: number[] = []
  for (const ch of input.replace(/=+$/, '').toUpperCase()) {
    const idx = alphabet.indexOf(ch)
    if (idx === -1) continue
    value = (value << 5) | idx
    bits += 5
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff)
      bits -= 8
    }
  }
  return Buffer.from(bytes)
}

function totp(secret: string, timestamp = Date.now()): string {
  const counter = Math.floor(timestamp / 1000 / 30)
  const buf = Buffer.alloc(8)
  buf.writeBigUInt64BE(BigInt(counter))
  const hmac = createHmac('sha1', base32Decode(secret)).update(buf).digest()
  const offset = hmac[hmac.length - 1] & 0x0f
  const code =
    ((hmac[offset] & 0x7f) << 24) |
    (hmac[offset + 1] << 16) |
    (hmac[offset + 2] << 8) |
    hmac[offset + 3]
  return String(code % 1_000_000).padStart(6, '0')
}

/**
 * 后端对 TOTP 有重放保护：每个 30s 窗口的码只能用一次（counter <= 已用过的
 * 直接拒绝）。同一个用例里连续用两次码时，必须等进下一个窗口，否则会偶发
 * 拿到"验证码错误"。
 */
/** 当前 TOTP 窗口序号（30s 步长，与后端一致），用于跨调用对比。 */
function totpWindowNow(): number {
  return Math.floor(Date.now() / 1000 / 30)
}

/**
 * 取一个"严格晚于" `afterWindow` 的 TOTP 窗口的码，且取在**该窗口中段**。
 *
 * 为什么必须取中段（而不只是"换新窗口"）：填码（fill）是瞬间完成，但真正
 * 提交要再等 confirm-2fa.click() + 网络往返。若提交时刻漂到下一个 30s
 * 窗口 W+1，后端接受窗口变 [W, W+1]，而 W 可能已被"启用 2FA"消费
 * （last_counter = W）→ 所填的 W 码被重放保护拒掉 → 前端弹"验证码错误"。
 * 取在中段（窗口开始后 ~10s 处）给前后各留 ~10s 余量，提交几乎不会漂出
 * 所填窗口，对重放保护竞态免疫。
 *
 * - 省略 `afterWindow`：保留原行为——安全垫后取当前窗口码（窗口边界前 5s 内才额外等）。
 * - 传入 `afterWindow`：若当前窗口仍 ≤ 该值，等到下一个窗口的中段。
 */
async function totpInFreshWindow(
  secret: string,
  afterWindow?: number,
): Promise<string> {
  // 等到当前 30s 窗口开始后 ~10s（中段），保证提交大概率仍在同窗口内。
  const secondsInWindow = Math.floor(Date.now() / 1000) % 30
  let target = 10
  if (afterWindow !== undefined && totpWindowNow() <= afterWindow) {
    // 当前窗口被重放保护占据，目标挪到下一窗口的中段（即 30 + 10 = 40s 处的码）。
    target = 40
  }
  if (secondsInWindow < target) {
    await new Promise((r) => setTimeout(r, (target - secondsInWindow) * 1000 + 200))
  }
  return totp(secret)
}

async function logoutByClearingStorage(page: Page): Promise<void> {
  // 直接清 storage 模拟登出，避免依赖 UI 菜单路径
  await page.evaluate(() => localStorage.clear())
  await page.goto('/login')
}

test.describe('two-factor authentication', () => {
  test('enable 2FA → two-step login → disable restores plain login', async ({
    browser,
  }) => {
    // 全量串行跑时登录/注册页会因前序用例的限流与浏览器排队变慢；
    // 单跑约 48s，120s 只放宽上限，不放宽任何断言。
    test.setTimeout(120_000)
    const ctx = await browser.newContext()
    const user = nextTestUser('twofa')
    const page = await ctx.newPage()
    await registerAndVerifyViaUi(page, user)
    await loginViaUi(page, user)

    // --- 1) 账号安全页开启 2FA ---
    await page.goto('/account/security')
    await page.getByTestId('start-2fa-setup').click()
    // secret 与恢复码都只在 setup 响应里出现一次
    const secretEl = page.getByTestId('2fa-secret')
    await expect(secretEl).toBeVisible({ timeout: 5_000 })
    const secret = (await secretEl.textContent())!.trim()
    expect(secret.length).toBeGreaterThanOrEqual(16)

    const codes = page.getByTestId('recovery-codes')
    await expect(codes).toBeVisible()
    const items = codes.locator('li')
    await expect(items).toHaveCount(10)
    const backupCodes = (await items.allTextContents()).map((t) => t.trim())
    expect(new Set(backupCodes).size).toBe(10)

    await page.getByTestId('2fa-code-input').fill(await totpInFreshWindow(secret))
    await page.getByTestId('confirm-enable-2fa').click()
    // 启用成功 → 进入 enabled 面板（"关闭两步验证"按钮出现即在位）
    await expect(page.getByTestId('open-disable-2fa')).toBeVisible({
      timeout: 10_000,
    })
    // 记录本次"启用 2FA"消费的 TOTP 窗口 N。重放保护已把它落到
    // totp_last_used_counter 上，后续两步登录必须取到比 N 更新的窗口。
    const enableWindow = totpWindowNow()

    // 刷新页面确认服务端状态真的落库（而不是只改了本地 state）
    await page.reload()
    await expect(page.getByTestId('open-disable-2fa')).toBeVisible({
      timeout: 10_000,
    })

    // --- 2) 登出 → 重新登录进入两步验证 ---
    await logoutByClearingStorage(page)
    await page.getByLabel('用户名或邮箱').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()

    // CardTitle 渲染为 div（非 heading role），用精确文本定位
    await expect(page.getByText('两步验证', { exact: true })).toBeVisible({
      timeout: 5_000,
    })
    await expect(page.getByTestId('confirm-2fa')).toBeVisible()

    // 错误码先被拒绝
    await page.getByLabel('验证码').fill('000000')
    await page.getByTestId('confirm-2fa').click()
    await expect(page.getByText('验证码错误，请重试')).toBeVisible({
      timeout: 5_000,
    })

    // 正确 TOTP 完成登录（换到比"启用"更新的窗口，避开重放保护）
    await page.getByLabel('验证码').fill(await totpInFreshWindow(secret, enableWindow))
    await page.getByTestId('confirm-2fa').click()
    await expect(page.getByText('登录成功')).toBeVisible({ timeout: 5_000 })
    await expect(page).toHaveURL(/dashboard/, { timeout: 10_000 })

    // --- 3) 关闭 2FA（密码 + 一次性码）→ 登录恢复一步式 ---
    await page.goto('/account/security')
    await page.getByTestId('open-disable-2fa').click()
    // 用 id 而不是 label 文本：账号安全页上「当前密码」同时是改密码卡片的
    // 标签，getByLabel 会 strict mode 命中两个输入框。
    await page.locator('#disable-password').fill(user.password)
    // 用备用码而不是 TOTP：省掉等新窗口，也顺带验证恢复码真的可用
    await page.getByTestId('disable-backup').fill(backupCodes[0])
    await page.getByTestId('confirm-disable-2fa').click()
    await expect(page.getByText('两步验证已关闭')).toBeVisible({ timeout: 5_000 })

    // 关闭会吊销既有会话（token_version 提升），重新登录应跳过第二步
    await logoutByClearingStorage(page)
    await page.getByLabel('用户名或邮箱').fill(user.username)
    await page.getByLabel('密码', { exact: true }).fill(user.password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByText('登录成功')).toBeVisible({ timeout: 5_000 })
    await expect(page).toHaveURL(/dashboard/, { timeout: 10_000 })

    await ctx.close()
  })

  test('account security page requires login', async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/account/security')
    await expect(page).toHaveURL(/login/, { timeout: 10_000 })
    await ctx.close()
  })
})
