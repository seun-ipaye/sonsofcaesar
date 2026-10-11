import { useEffect, useState } from 'react'
import './Intro.css'

const GIF_DURATION_MS = 2000

export default function Intro({ onEnter }: { onEnter: () => void }) {
  const [showButton, setShowButton] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setShowButton(true), GIF_DURATION_MS)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className="intro">
      <img className="intro-gif" src="/intro.gif" alt="Sons of Caesar" />
      <button
        className={`enter ${showButton ? 'visible' : ''}`}
        onClick={onEnter}
        disabled={!showButton}
      >
        enter
      </button>
    </div>
  )
}
