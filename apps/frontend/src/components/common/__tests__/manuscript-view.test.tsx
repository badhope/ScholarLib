import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ManuscriptView } from '../manuscript-view'
import { api } from '@/lib/api'

vi.mock('@/hooks/use-is-mobile', () => ({ useIsMobile: () => true }))
vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }))

describe('ManuscriptView', () => {
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
