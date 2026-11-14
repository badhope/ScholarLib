import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AuthPngPreview from '@/components/auth-png-preview'

const getMock = vi.fn()

vi.mock('@/lib/api', () => ({
  api: { get: (...args: unknown[]) => getMock(...args) },
}))

beforeEach(() => {
  getMock.mockReset()
  getMock.mockResolvedValue({ data: new Blob(['image'], { type: 'image/png' }) })
})

describe('AuthPngPreview', () => {
  it('resets to page 1 when the source URL changes', async () => {
    const { rerender } = render(<AuthPngPreview baseUrl="/submissions/source-preview/a" pages={5} />)
    await waitFor(() => expect(screen.getByAltText('原件第 1 页')).toBeInTheDocument())

    fireEvent.click(screen.getByText('下一页'))
    expect(screen.getByAltText('原件第 2 页')).toBeInTheDocument()

    rerender(<AuthPngPreview baseUrl="/submissions/source-preview/b" pages={2} />)
    await waitFor(() => expect(screen.getByAltText('原件第 1 页')).toBeInTheDocument())
    expect(screen.getByText('1 / 2 页')).toBeInTheDocument()
  })

  it('clamps the page and retries with an authenticated request', async () => {
    const { rerender } = render(<AuthPngPreview baseUrl="/submissions/source-preview/a" pages={5} />)
    await waitFor(() => expect(screen.getByAltText('原件第 1 页')).toBeInTheDocument())
    for (let index = 0; index < 4; index += 1) fireEvent.click(screen.getByText('下一页'))
    expect(screen.getByAltText('原件第 5 页')).toBeInTheDocument()

    rerender(<AuthPngPreview baseUrl="/submissions/source-preview/a" pages={3} />)
    await waitFor(() => expect(screen.getByText('3 / 3 页')).toBeInTheDocument())

    fireEvent.error(screen.getByAltText('原件第 3 页'))
    expect(screen.getByText('重试')).toBeInTheDocument()
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(getMock).toHaveBeenLastCalledWith('/submissions/source-preview/a/3.png', {
      responseType: 'blob',
      timeout: 60_000,
    }))
  })
})
