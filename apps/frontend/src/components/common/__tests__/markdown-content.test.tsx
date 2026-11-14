import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownContent } from '@/components/common/markdown-content'

describe('MarkdownContent', () => {
  it('renders headings, GFM tables, math and inline HTML in one pass', () => {
    const { container } = render(
      <MarkdownContent
        text={[
          '# 标题',
          '',
          '| 项目 | 数值 |',
          '| --- | --- |',
          '| 甲 | 1 |',
          '',
          '行内公式 $E=mc^2$',
          '',
          '<mark>高亮</mark> 与 <u>下划线</u>',
        ].join('\n')}
      />,
    )
    expect(container.querySelector('h1')?.textContent).toBe('标题')
    expect(container.querySelector('.md-table-wrap table')).toBeTruthy()
    expect(container.querySelector('.katex')).toBeTruthy()
    expect(container.querySelector('mark')?.textContent).toBe('高亮')
    expect(container.querySelector('u')?.textContent).toBe('下划线')
  })

  it('keeps figure captions and data images instead of stripping them', () => {
    const data = 'data:image/png;base64,iVBORw0KGgo='
    const { container } = render(
      <MarkdownContent
        text={`<figure><img src="${data}" alt="图" /><figcaption>图 1 测试</figcaption></figure>`}
      />,
    )
    expect(container.querySelector('figure')).toBeTruthy()
    expect(container.querySelector('figcaption')?.textContent).toBe('图 1 测试')
    expect(container.querySelector('img')?.getAttribute('src')).toBe(data)
  })

  it('sanitizes scripts and event handlers', () => {
    const { container } = render(
      <MarkdownContent text={'<img src="x" onerror="alert(1)" /><script>alert(1)</script>'} />,
    )
    const img = container.querySelector('img')
    expect(img?.getAttribute('onerror')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
  })
})
