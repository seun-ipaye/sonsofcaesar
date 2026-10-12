import { useEffect, useRef, useState } from 'react'
import type { Page } from './Intro'
import './NavButton.css'

// Pages that aren't open yet: hover/tap shows "coming soon" instead of navigating.
export const COMING_SOON: Page[] = []

// In-house ticketing is switched on per environment (VITE_IN_HOUSE_TICKETS in
// .env.development / .env.production). While it's off, Tickets goes to Bloom.
export const IN_HOUSE_TICKETS = import.meta.env.VITE_IN_HOUSE_TICKETS === 'true'

// Pages that live on another site: the button opens it in a new tab.
// Remove a page from here to use our own page again.
export const EXTERNAL: Partial<Record<Page, string>> = IN_HOUSE_TICKETS
  ? {}
  : { tickets: 'https://sons-of-caesar.bloomtickets.ca/hostinfo/924' }

type Props = {
  page: Page
  label?: string
  className?: string
  disabled?: boolean
  onGo: (page: Page) => void
}

// A nav button. For pages in COMING_SOON it doesn't navigate: hovering (desktop)
// or tapping (mobile) reveals "coming soon" instead.
export default function NavButton({ page, label = page, className = '', disabled, onGo }: Props) {
  const soon = COMING_SOON.includes(page)
  const [showing, setShowing] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => () => clearTimeout(timer.current), [])

  const external = EXTERNAL[page]
  if (external) {
    return (
      <a
        className={`${className} nav-external`}
        href={external}
        target="_blank"
        rel="noreferrer"
        aria-disabled={disabled}
        tabIndex={disabled ? -1 : undefined}
      >
        {label}
      </a>
    )
  }

  if (!soon) {
    return (
      <button className={className} disabled={disabled} onClick={() => onGo(page)}>
        {label}
      </button>
    )
  }

  // Taps don't hover, so on click show the message for a moment
  const flash = () => {
    setShowing(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setShowing(false), 1800)
  }

  return (
    <button
      className={`${className} soon-btn ${showing ? 'showing' : ''}`}
      disabled={disabled}
      aria-label={`${label} (coming soon)`}
      onClick={flash}
    >
      <span className="soon-label">{label}</span>
      <span className="soon-text" aria-hidden="true">
        coming soon
      </span>
    </button>
  )
}
