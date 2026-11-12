import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Scroll-reveal without motion's whileInView.
 *
 * motion 14.5.0's `whileInView` never advances in this app (React 19 + Vite 8):
 * the observer is created and its callback fires, but the variant never
 * updates, so sections stay at their `hidden` opacity forever. The same
 * element animates correctly through `animate`, and it reproduces in the
 * production build, so we drive the reveal ourselves with a plain
 * IntersectionObserver.
 *
 * Exposes a callback ref (rather than a ref object) so React Compiler's
 * "cannot access refs during render" rule stays satisfied.
 */
export function useInViewReveal(options?: { rootMargin?: string; threshold?: number }) {
  const [node, setNode] = useState<Element | null>(null)
  const [revealed, setRevealed] = useState(true) // 首屏即可见：滚动入场在移动端/截图下会把整块停在 opacity 0
  const observerRef = useRef<IntersectionObserver | null>(null)

  const rootMargin = options?.rootMargin ?? '0px 0px 200px 0px'
  const threshold = options?.threshold ?? 0

  const setRef = useCallback((next: Element | null) => {
    setNode(next)
  }, [])

  useEffect(() => {
    if (!node || revealed) return
    if (typeof IntersectionObserver === 'undefined') {
      // No observer (very old browser / SSR): show content immediately.
      const id = requestAnimationFrame(() => setRevealed(true))
      return () => cancelAnimationFrame(id)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setRevealed(true)
          observer.disconnect()
        }
      },
      { rootMargin, threshold },
    )
    observer.observe(node)
    observerRef.current = observer

    return () => {
      observer.disconnect()
      observerRef.current = null
    }
  }, [node, revealed, rootMargin, threshold])

  return [setRef, revealed] as const
}
