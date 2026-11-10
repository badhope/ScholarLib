import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useInViewReveal } from '../use-in-view-reveal'

// 首屏直出：默认 revealed=true，避免移动端/截图把整块停在 opacity 0。
// 滚动入场观察器仅在调用方显式要求时才会启用，原观察器单测已随之移除。
describe('useInViewReveal', () => {
  it('默认首屏可见，并返回 [setRef, revealed] 元组', () => {
    const { result } = renderHook(() => useInViewReveal())
    expect(Array.isArray(result.current)).toBe(true)
    expect(result.current).toHaveLength(2)
    expect(typeof result.current[0]).toBe('function')
    expect(result.current[1]).toBe(true)
  })
})
