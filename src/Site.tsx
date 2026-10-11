import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { PAGES, type Page } from './Intro'
import Footer from './Footer'
import './Site.css'

const FADE_MS = 500

// Shared layout for every page after the intro: header, page content, footer
export default function Site() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const page = pathname.slice(1)
  const [fading, setFading] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  // Fade the page out to black, swap it, then the new page fades in
  const go = (p: Page) => {
    setMenuOpen(false)
    if (p === page || fading) return
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
            <button key={p} className={p === page ? 'active' : ''} onClick={() => go(p)}>
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

      <main className={`page ${fading ? 'fading' : ''}`} key={page}>
        <Outlet />
      </main>

      <Footer />
    </div>
  )
}
