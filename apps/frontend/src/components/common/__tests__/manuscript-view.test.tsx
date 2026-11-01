import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ManuscriptView } from '../manuscript-view'
import { api } from '@/lib/api'

vi.mock('@/hooks/use-is-mobile', () => ({ useIsMobile: () => true }))
vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }))

function renderView(md: string) {
 vi.mocked(api.get).mockResolvedValue({ data: md })
 const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
 return render(
  <QueryClientProvider client={client}>
   <ManuscriptView resourceId={1} initialPercent={0} onProgress={() => {}} />
  </QueryClientProvider>,
 )
}

describe('ManuscriptView', () => {
 it('把摘要渲染为独立卡片并从正文流中移除', async () => {
  const { container } = renderView('# 论文标题\n\n## 摘要\n\n本文研究排版层级。\n\n**关键词**：排版；层级\n\n## 1 引言\n\n正文第一段。\n\n### 1.1 子节\n\n子节正文。')
  const abstract = await screen.findByRole('region', { name: '摘要' })
  expect(abstract).toHaveTextContent('本文研究排版层级。')
  expect(abstract).not.toHaveTextContent('正文第一段。')
  expect(container.querySelectorAll('.markdown-body')).toHaveLength(1)
  expect(screen.getByRole('heading', { level: 1, name: '论文标题' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 2, name: '1 引言' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 3, name: '1.1 子节' })).toBeInTheDocument()
  expect(screen.getByText('关键词').closest('p')).toHaveClass('md-keywords')
 })

 it('识别旧稿 blockquote 摘要', async () => {
  renderView('> **摘　要**　旧稿摘要正文。\n\n## 1 引言\n\n正文。')
  const abstract = await screen.findByRole('region', { name: '摘要' })
  expect(abstract).toHaveTextContent('旧稿摘要正文。')
 })

 it('区分图注、表注，并把表格包进横向滚动容器', async () => {
  renderView('## 1 引言\n\n正文。\n\n| 指标 | 值 |\n| --- | --- |\n| 行高 | 1.95 |\n\n*表 1　指标表*\n\n![图 1](https://example.com/a.png)\n\n*图 1　示意图*')
  const table = await screen.findByRole('table')
  expect(table.parentElement).toHaveClass('md-table-wrap')
  expect(screen.getByText(/^表 1/).closest('p')).toHaveClass('md-caption')
  expect(screen.getByText(/^图 1/).closest('p')).toHaveClass('md-caption')
 })

 it('参考文献逐条分段且不重复标题', async () => {
  renderView('## 1 引言\n\n正文。\n\n## 参考文献\n\n[1] 张三. 论文[J]. 期刊, 2026.\n\n[2] 李四. 专著[M]. 出版社, 2025.')
  const first = await screen.findByText(/^\[1\]/)
  const second = screen.getByText(/^\[2\]/)
  expect(first.tagName).toBe('P')
  expect(second.tagName).toBe('P')
  expect(first).not.toBe(second)
  expect(screen.queryByRole('heading', { name: '参考文献' })).not.toBeInTheDocument()
 })

 it('保留移动端题录之前的内容和图片，并让目录指向实际标题', async () => {
 vi.mocked(api.get).mockResolvedValue({ data: '前置内容\n\n# 标题\n\n![机构图](https://example.com/a.png)\n\n> **摘要** 摘要内容\n\n## 1 **方法**\n\n正文\n\n## 1 **方法**\n\n```md\n## 假标题\n```\n\n### 子节' })
 const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
 render(<QueryClientProvider client={client}><ManuscriptView resourceId={1} initialPercent={0} onProgress={() => {}} /></QueryClientProvider>)
 expect(await screen.findByText('前置内容')).toBeInTheDocument()
 expect(screen.getByAltText('机构图')).toBeInTheDocument()
 const headings = screen.getAllByRole('heading', { name: '1 方法' })
 await waitFor(() => expect(headings[0].id).toBeTruthy())
 expect(headings[0].id).not.toBe(headings[1].id)
 fireEvent(window, new Event('rubbish:open-toc'))
 const dialog = screen.getByRole('dialog', { name: '文章目录' })
 expect(dialog.textContent).not.toContain('假标题')
 expect(dialog.textContent?.match(/方法/g)).toHaveLength(2)
 })
})
