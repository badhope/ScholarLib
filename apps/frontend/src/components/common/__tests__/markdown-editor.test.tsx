import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MarkdownEditor } from '@/components/common/markdown-editor'

describe('MarkdownEditor', () => {
  it('shows a live split preview with headings and math', async () => {
    render(
      <MarkdownEditor value={'# 标题\n\n公式 $E=mc^2$'} onChange={() => {}} />,
    )
    await userEvent.click(screen.getByText('分栏'))
    const preview = await screen.findByTestId('md-split-preview')
    expect(preview).toBeTruthy()
    expect(preview?.querySelector('h1')?.textContent).toBe('标题')
    expect(preview?.querySelector('.katex')).toBeTruthy()
  })
})
