import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { MarkdownEditor } from '@/components/common/markdown-editor'

function Harness({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial)
  return <MarkdownEditor value={value} onChange={setValue} />
}

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

  it('indents and outdents a multi-line selection', () => {
    render(<Harness initial={'one\ntwo\nthree'} />)
    const area = screen.getByRole('textbox') as HTMLTextAreaElement
    area.setSelectionRange(0, 'one\ntwo'.length)
    fireEvent.keyDown(area, { key: 'Tab' })
    expect(area.value).toBe('  one\n  two\nthree')

    area.setSelectionRange(0, '  one\n  two'.length)
    fireEvent.keyDown(area, { key: 'Tab', shiftKey: true })
    expect(area.value).toBe('one\ntwo\nthree')
  })

  it('wraps the selected text with Ctrl+U', () => {
    render(<Harness initial="需要下划线" />)
    const area = screen.getByRole('textbox') as HTMLTextAreaElement
    area.setSelectionRange(0, 5)
    fireEvent.keyDown(area, { key: 'u', ctrlKey: true })
    expect(area.value).toBe('<u>需要下划线</u>')
  })

  it('exposes accessible names on the editor and tools', () => {
    render(<MarkdownEditor value="" onChange={() => {}} placeholder="正文" />)
    expect(screen.getByLabelText('Markdown 正文：正文')).toBeInTheDocument()
    expect(screen.getByLabelText('加粗（Ctrl+B）')).toBeInTheDocument()
    expect(screen.getByLabelText('插入标题')).toBeInTheDocument()
  })
})

it('undoes and redoes a text change', () => {
  render(<Harness initial="a" />)
  const area = screen.getByLabelText('Markdown 正文') as HTMLTextAreaElement
  fireEvent.change(area, { target: { value: 'ab' } })
  expect(area.value).toBe('ab')

  fireEvent.click(screen.getByLabelText('撤销（Ctrl+Z）'))
  expect(area.value).toBe('a')
  fireEvent.click(screen.getByLabelText('重做（Ctrl+Shift+Z）'))
  expect(area.value).toBe('ab')
})

it('replaces all matches from the find panel', () => {
  render(<Harness initial="alpha beta alpha" />)
  fireEvent.click(screen.getByLabelText('查找替换'))
  fireEvent.change(screen.getByLabelText('查找内容'), {
    target: { value: 'alpha' },
  })
  fireEvent.change(screen.getByLabelText('替换为'), {
    target: { value: 'gamma' },
  })
  fireEvent.click(screen.getByText('全部替换'))
  expect(
    (screen.getByLabelText('Markdown 正文') as HTMLTextAreaElement).value,
  ).toBe('gamma beta gamma')
})

it('builds an outline from headings and enters focus mode', () => {
  render(<Harness initial={'# 标题\n\n## 小节'} />)
  fireEvent.click(screen.getByLabelText('文档大纲'))
  expect(screen.getByText('小节')).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('专注模式'))
  expect(screen.getByTestId('markdown-editor').className).toContain('fixed')
})
