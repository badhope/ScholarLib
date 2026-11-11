import { test, expect } from '@playwright/test'
import { ADMIN, loginViaUi } from './helpers'

// 导入页面(ingest/index.tsx) - BibTeX / RIS / CSV 解析。
//
// 注意:fetch tab 调 Crossref / arXiv 外网,沙箱可能不通,所以这里
// 只测本地 parse 流程,不测 fetch。

const BIBTEX_SAMPLE = `@article{smith2024deep,
  title = {Deep Learning for Citations},
  author = {Smith, Alice and Jones, Bob},
  journal = {Journal of E2E},
  year = {2024},
  volume = {1},
  number = {2},
  pages = {3--10},
  doi = {10.1000/e2e-bibtex},
  abstract = {A test BibTeX entry for E2E ingest.},
  keywords = {deep learning, citations}
}`

const RIS_SAMPLE = `TY  - JOUR
TI  - RIS Test Entry
AU  - Carol Lee
AU  - Dan Wu
PY  - 2023
DO  - 10.1000/e2e-ris
AB  - A test RIS entry for E2E ingest.
KW  - ris
ER  -`

const CSV_SAMPLE = `title,authors,year,discipline,abstract,doi,tags
CSV Test Entry,"Eve Adams",2022,physics,"A test CSV entry for E2E.",10.1000/e2e-csv,csv;e2e`

test.describe('ingest: parse BibTeX / RIS / CSV', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, ADMIN)
    await page.goto('/ingest')
    await expect(page.getByRole('heading', { name: '导入' })).toBeVisible()
  })

  test('parse BibTeX yields one resource card', async ({ page }) => {
    await page.getByRole('tab', { name: '解析文件' }).click()
    // 选 BibTeX(默认就是 bibtex,但显式点一下)
    await page.locator('button[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'BibTeX' }).click()
    // 粘贴内容
    await page.getByPlaceholder('粘贴 BibTeX / RIS / CSV 内容…').fill(BIBTEX_SAMPLE)
    await page.getByRole('button', { name: '解析' }).click()
    // toast 成功
    await expect(page.getByText(/解析完成.*1 条/)).toBeVisible({ timeout: 5_000 })
    // 卡片出现,显示标题(textarea 里也有同串,所以限定到 heading)
    await expect(page.getByRole('heading', { name: 'Deep Learning for Citations' })).toBeVisible()
    // 提交到目录按钮
    await expect(page.getByRole('button', { name: '提交到目录' })).toBeVisible()
  })

  test('parse RIS yields one resource card', async ({ page }) => {
    await page.getByRole('tab', { name: '解析文件' }).click()
    await page.locator('button[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'RIS' }).click()
    await page.getByPlaceholder('粘贴 BibTeX / RIS / CSV 内容…').fill(RIS_SAMPLE)
    await page.getByRole('button', { name: '解析' }).click()
    await expect(page.getByText(/解析完成.*1 条/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('heading', { name: 'RIS Test Entry' })).toBeVisible()
  })

  test('parse CSV yields one resource card', async ({ page }) => {
    await page.getByRole('tab', { name: '解析文件' }).click()
    await page.locator('button[role="combobox"]').first().click()
    await page.getByRole('option', { name: 'CSV' }).click()
    await page.getByPlaceholder('粘贴 BibTeX / RIS / CSV 内容…').fill(CSV_SAMPLE)
    await page.getByRole('button', { name: '解析' }).click()
    await expect(page.getByText(/解析完成.*1 条/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('heading', { name: 'CSV Test Entry' })).toBeVisible()
  })

  test('parse invalid content shows error toast', async ({ page }) => {
    await page.getByRole('tab', { name: '解析文件' }).click()
    await page.getByPlaceholder('粘贴 BibTeX / RIS / CSV 内容…').fill('not-a-valid-bibtex-content')
    await page.getByRole('button', { name: '解析' }).click()
    // toast 错误出现(可能是 0 条成功 + errors,也可能是 toast.error)
    await expect(page.locator('[data-sonner-toast]')).toBeVisible({ timeout: 5_000 })
  })

  test('submit to catalog navigates to submissions page with preset', async ({ page }) => {
    await page.getByRole('tab', { name: '解析文件' }).click()
    await page.getByPlaceholder('粘贴 BibTeX / RIS / CSV 内容…').fill(BIBTEX_SAMPLE)
    await page.getByRole('button', { name: '解析' }).click()
    await expect(page.getByRole('heading', { name: 'Deep Learning for Citations' })).toBeVisible({ timeout: 5_000 })

    // 点提交到目录 → 跳 /submissions/new 表单页 + 预填数据
    await page.getByRole('button', { name: '提交到目录' }).click()
    await expect(page).toHaveURL(/\/submissions\/new/, { timeout: 10_000 })
    await expect(page.getByRole('heading', { name: '新建投稿' })).toBeVisible({ timeout: 5_000 })
    // preset 把解析出的标题填进了 title 输入框（input value 不是 textContent，
    // 不能用 getByText，要用 toHaveValue）
    await expect(page.getByLabel('标题')).toHaveValue('Deep Learning for Citations')
  })

  test('ingest page is not accessible to non-authenticated users', async ({ browser }) => {
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto('/ingest')
    await expect(page).toHaveURL(/\/login/)
    await ctx.close()
  })
})
