import { useEffect, useState } from 'react'
import './Intro.css'

const GIF_DURATION_MS = 2000
const FADE_MS = 500

export const PAGES = ['home', 'tickets', 'gallery', 'about'] as const
export type Page = (typeof PAGES)[number]

// waiting: gif playing, nothing shown
// enter:   enter button visible
// leaving: enter button fading out
// menu:    the four options visible
type Phase = 'waiting' | 'enter' | 'leaving' | 'menu'

export default function Intro({ onSelect }: { onSelect: (page: Page) => void }) {
  const [phase, setPhase] = useState<Phase>('waiting')

  useEffect(() => {
    const t = setTimeout(() => setPhase('enter'), GIF_DURATION_MS)
    return () => clearTimeout(t)
  }, [])

  useEffect(() => {
    if (phase !== 'leaving') return
    const t = setTimeout(() => setPhase('menu'), FADE_MS)
    return () => clearTimeout(t)
  }, [phase])

  return (
    <div className="intro" style={{ '--fade': `${FADE_MS}ms` } as React.CSSProperties}>
      <img className="intro-gif" src="/intro.gif" alt="Sons of Caesar" />
      {/* Both layers always occupy the same space, so the gif never moves */}
      <div className="controls">
        <button
          className={`enter ${phase === 'enter' ? 'visible' : ''}`}
          onClick={() => setPhase('leaving')}
          disabled={phase !== 'enter'}
        >
          enter
        </button>
        <nav className={`menu ${phase === 'menu' ? 'visible' : ''}`}>
          {PAGES.map((page) => (
            <button
              key={page}
              className="enter"
              onClick={() => onSelect(page)}
              disabled={phase !== 'menu'}
            >
              {page}
            </button>
          ))}
        </nav>
      </div>
    </div>
  )
}
