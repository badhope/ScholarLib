import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CookieBanner } from '@/components/common/cookie-banner'

const KEY = 'rubbish_cookie_consent'

describe('CookieBanner', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('shows the banner when no decision is stored', () => {
    render(<CookieBanner />)
    expect(screen.getByTestId('cookie-banner')).toBeInTheDocument()
    expect(screen.getByText(/cookie 仅必要/i)).toBeInTheDocument()
  })

  it('hides the banner when a prior decision exists', () => {
    localStorage.setItem(KEY, 'accepted')
    render(<CookieBanner />)
    expect(screen.queryByTestId('cookie-banner')).toBeNull()
  })

  it('"Accept all" persists choice and hides banner', async () => {
    const user = userEvent.setup()
    render(<CookieBanner />)
    await user.click(screen.getByTestId('cookie-banner-accept'))
    expect(localStorage.getItem(KEY)).toBe('accepted')
    expect(screen.queryByTestId('cookie-banner')).toBeNull()
  })

  it('"Essential only" persists choice and hides banner', async () => {
    const user = userEvent.setup()
    render(<CookieBanner />)
    await user.click(screen.getByTestId('cookie-banner-essential'))
    expect(localStorage.getItem(KEY)).toBe('essential')
    expect(screen.queryByTestId('cookie-banner')).toBeNull()
  })

  it('handles corrupted localStorage value gracefully', () => {
    localStorage.setItem(KEY, 'totally-invalid-value')
    render(<CookieBanner />)
    // Should fall through to "no decision" and render the banner.
    expect(screen.getByTestId('cookie-banner')).toBeInTheDocument()
  })
})
