import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SourcePreviewPng from '@/components/source-preview-png'

describe('SourcePreviewPng', () => {
  it('resets to page 1 when the token changes, even before the effect runs', () => {
    const { rerender } = render(<SourcePreviewPng token="token-a" pages={5} />)
    expect(screen.getByAltText('原件第 1 页')).toBeInTheDocument()

    fireEvent.click(screen.getByText('下一页'))
    expect(screen.getByAltText('原件第 2 页')).toBeInTheDocument()

    rerender(<SourcePreviewPng token="token-b" pages={2} />)
    expect(screen.getByAltText('原件第 1 页')).toBeInTheDocument()
    expect(screen.getByText('1 / 2 页')).toBeInTheDocument()
  })

  it('clamps the current page when the new document has fewer pages', () => {
    const { rerender } = render(<SourcePreviewPng token="token-a" pages={5} />)
    fireEvent.click(screen.getByText('下一页'))
    fireEvent.click(screen.getByText('下一页'))
    fireEvent.click(screen.getByText('下一页'))
    fireEvent.click(screen.getByText('下一页'))
    expect(screen.getByAltText('原件第 5 页')).toBeInTheDocument()

    rerender(<SourcePreviewPng token="token-a" pages={3} />)
    expect(screen.getByAltText('原件第 3 页')).toBeInTheDocument()
    expect(screen.getByText('3 / 3 页')).toBeInTheDocument()
  })

  it('offers a retry after an image error', () => {
    render(<SourcePreviewPng token="token-a" pages={3} />)
    fireEvent.error(screen.getByAltText('原件第 1 页'))
    expect(screen.getByText('重新加载本页')).toBeInTheDocument()

    fireEvent.click(screen.getByText('重新加载本页'))
    expect(screen.getByAltText('原件第 1 页')).toHaveAttribute(
      'src',
      '/api/submissions/source-preview/token-a/1.png?v=1',
    )
  })
})
