import { useEffect, useRef } from 'react'
import type { Photo } from '../data/parties'

type Props = {
  photos: Photo[]
  index: number
  onChange: (index: number) => void
  onClose: () => void
}

// Full-screen photo viewer: arrows / swipe to move, Esc / tap outside to close
export default function Lightbox({ photos, index, onChange, onClose }: Props) {
  const touchX = useRef<number | null>(null)
  const photo = photos[index]
  const prev = () => onChange((index - 1 + photos.length) % photos.length)
  const next = () => onChange((index + 1) % photos.length)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  })

  // Preload the neighbours so moving between photos feels instant
  useEffect(() => {
    for (const i of [index - 1, index + 1]) {
      const p = photos[(i + photos.length) % photos.length]
      new Image().src = p.full
    }
  }, [index, photos])

  return (
    <div
      className="lightbox"
      onClick={onClose}
      onTouchStart={(e) => (touchX.current = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (touchX.current === null) return
        const dx = e.changedTouches[0].clientX - touchX.current
        if (Math.abs(dx) > 50) (dx > 0 ? prev : next)()
        touchX.current = null
      }}
    >
      {/* Thumbnail underneath shows instantly while the full size loads on top */}
      <div className="lightbox-photo" onClick={(e) => e.stopPropagation()}>
        <img key={photo.thumb} src={photo.thumb} alt="" className="lightbox-thumb" />
        <img key={photo.full} src={photo.full} alt="" className="lightbox-full" />
      </div>

      <button className="lightbox-btn close" aria-label="Close" onClick={onClose}>
        ×
      </button>
      <button
        className="lightbox-btn prev"
        aria-label="Previous photo"
        onClick={(e) => {
          e.stopPropagation()
          prev()
        }}
      >
        ‹
      </button>
      <button
        className="lightbox-btn next"
        aria-label="Next photo"
        onClick={(e) => {
          e.stopPropagation()
          next()
        }}
      >
        ›
      </button>
      <div className="lightbox-count">
        {index + 1} / {photos.length}
      </div>
    </div>
  )
}
