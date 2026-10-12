import { useState } from 'react'
import { Outlet, useLocation, useNavigate, useOutletContext } from 'react-router'
import { PAGES, type Page } from './Intro'
import Footer from './Footer'
import './Site.css'

const FADE_MS = 500

// Shared layout for every page after the intro: header, page content, footer
export default function Site() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // "/gallery/on-deck" -> path "gallery/on-deck", section "gallery"
  const path = pathname.slice(1)
  const section = path.split('/')[0]
  const [fading, setFading] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  // Fade the page out to black, swap it, then the new page fades in.
  // Takes a page name or a deeper path like "gallery/on-deck".
  const go = (p: Page | string) => {
    setMenuOpen(false)
    if (p === path || fading) return
    setFading(true)
    setTimeout(() => {
      navigate(`/${p}`)
      window.scrollTo(0, 0)
      setFading(false)
    }, FADE_MS)
  }

  return (
    <div className="site" style={{ '--fade': `${FADE_MS}ms` } as React.CSSProperties}>
      <header className="header">
        <button
          className={`hamburger ${menuOpen ? 'open' : ''}`}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <span />
          <span />
          <span />
        </button>

        <img
          className="header-logo"
          src="/intro.gif"
          alt="Sons of Caesar"
          onClick={() => go('home')}
        />

        <nav className="header-links">
          {PAGES.map((p) => (
            <button key={p} className={p === section ? 'active' : ''} onClick={() => go(p)}>
              {p}
            </button>
          ))}
        </nav>
      </header>

      <div className={`mobile-menu ${menuOpen ? 'open' : ''}`}>
        {PAGES.map((p) => (
          <button key={p} className="enter" onClick={() => go(p)}>
            {p}
          </button>
        ))}
      </div>

      <main className={`page ${fading ? 'fading' : ''}`} key={path}>
        <Outlet context={go} />
      </main>

      <Footer />
    </div>
  )
}

// Lets pages navigate with the same fade as the header links
export function useGo() {
  return useOutletContext<(page: Page | string) => void>()
}
