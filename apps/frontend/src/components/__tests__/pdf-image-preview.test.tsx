import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PdfImagePreview from '@/components/pdf-image-preview'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ pages: 3 }),
  })
  vi.stubGlobal('fetch', fetchMock)
})

describe('PdfImagePreview', () => {
  it('resets to page 1 when the resource changes', async () => {
    const { rerender } = render(<PdfImagePreview resourceId={91} version="21" />)
    await waitFor(() => expect(screen.getByText('1 / 3 页')).toBeInTheDocument())

    fireEvent.click(screen.getByText('下一页'))
    await waitFor(() => expect(screen.getByAltText('PDF 第 2 页')).toBeInTheDocument())

    rerender(<PdfImagePreview resourceId={3} version="21" />)
    await waitFor(() => expect(screen.getByAltText('PDF 第 1 页')).toBeInTheDocument())
  })

  it('fetches page count once per resource, not on every page turn', async () => {
    render(<PdfImagePreview resourceId={91} version="21" />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByText('下一页'))
    fireEvent.click(screen.getByText('下一页'))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByAltText('PDF 第 3 页')).toBeInTheDocument())
  })

  it('offers a retry after an image error', async () => {
    render(<PdfImagePreview resourceId={91} version="21" />)
    await waitFor(() => expect(screen.getByText('1 / 3 页')).toBeInTheDocument())
    fireEvent.error(screen.getByAltText('PDF 第 1 页'))
    expect(screen.getByText('重新加载本页')).toBeInTheDocument()

    fireEvent.click(screen.getByText('重新加载本页'))
    await waitFor(() =>
      expect(screen.getByAltText('PDF 第 1 页')).toHaveAttribute(
        'src',
        '/api/catalog/91/export?format=png&v=21&page=1&retry=1',
      ),
    )
  })
})
