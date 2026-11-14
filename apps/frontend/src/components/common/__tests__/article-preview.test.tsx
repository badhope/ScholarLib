import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ArticlePreview } from '@/components/common/article-preview'

describe('ArticlePreview', () => {
  it('uses the same renderer as the published article: GFM, math and inline HTML', () => {
    const { container } = render(
      <ArticlePreview
        title="标题"
        authors={['张三']}
        abstract="摘要含 $E=mc^2$ 与 <mark>高亮</mark>"
        keywords={['关键词']}
        body={[
          '## 1 引言',
          '',
          '| 指标 | 值 |',
          '| --- | --- |',
          '| 行高 | 1.95 |',
          '',
          '<mark>高亮</mark> 与 <u>下划线</u>',
          '',
          '公式 $E=mc^2$',
          '',
          '**作者：**马必略',
        ].join('\n')}
      />,
    )
    expect(container.querySelector('.md-table-wrap table')).toBeTruthy()
    expect(container.querySelector('mark')?.textContent).toBe('高亮')
    expect(container.querySelector('u')?.textContent).toBe('下划线')
    expect(container.querySelector('.md-abstract .katex')).toBeTruthy()
    expect(container.querySelector('.md-abstract mark')?.textContent).toBe('高亮')
    expect(container.querySelector('strong')?.textContent).toBe('作者：')
  })

  it('strips duplicate body title, abstract and keywords before previewing', () => {
    const { container } = render(
      <ArticlePreview
        title="标题"
        authors={[]}
        abstract="摘要正文"
        keywords={['关键词']}
        body={'# 标题\n\n## 摘要\n\n摘要正文\n\n## 关键词\n\n关键词\n\n## 1 引言\n\n正文'}
      />,
    )
    expect(container.querySelectorAll('h1')).toHaveLength(1)
    expect(container.textContent).not.toContain('## 摘要')
    expect(container.textContent).toContain('正文')
  })

  it('strips a duplicate H2 title as well as H1', () => {
    const { container } = render(
      <ArticlePreview title="标题" authors={[]} abstract="" keywords={[]} body={'## 标题\n\n正文'} />,
    )
    expect(container.querySelectorAll('h2')).toHaveLength(0)
    expect(container.textContent).toContain('正文')
  })
})
