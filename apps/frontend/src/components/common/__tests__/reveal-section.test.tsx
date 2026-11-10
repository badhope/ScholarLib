import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RevealSection } from '../reveal-section'

describe('RevealSection', () => {
  it('首屏直接渲染子节点，不再依赖观察器', () => {
    render(<RevealSection><span>首屏内容</span></RevealSection>)
    expect(screen.getByText('首屏内容')).toBeInTheDocument()
  })
})
