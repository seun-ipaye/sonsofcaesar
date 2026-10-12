import { useMemo, useRef, useState } from 'react'
import { useGo } from '../Site'
import { hero, parties } from '../data/parties'
import GalleryImage from '../gallery/GalleryImage'
import '../gallery/Gallery.css'

const HERO_PHOTOS = 4

// Random pick, different on every visit
function shuffle<T>(items: T[]) {
  const a = [...items]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

export default function Gallery() {
  const go = useGo()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [muted, setMuted] = useState(true)
  // Landscape photos fit the hero tiles best. Skip each party's first photo,
  // since that one is already its cover below.
  const heroPhotos = useMemo(
    () =>
      shuffle(
        parties.flatMap((p) => p.photos.slice(1)).filter((p) => p.width > p.height),
      ).slice(0, HERO_PHOTOS),
    [],
  )

  const toggleSound = () => {
    const v = videoRef.current
    if (!v) return
    v.muted = !v.muted
    setMuted(v.muted)
  }

  return (
    <div className="gallery">
      {/* One screen: the video in the middle, photos around it */}
      <section className="gallery-hero">
        <div className="hero-video">
          {hero && (
            <video
              ref={videoRef}
              src={hero.video}
              poster={hero.poster}
              autoPlay
              muted
              loop
              playsInline
            />
          )}
          <button className="sound" onClick={toggleSound} aria-label={muted ? 'Turn sound on' : 'Turn sound off'}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 9h4l5-4v14l-5-4H4z" fill="currentColor" />
              {muted ? (
                <path d="M16.5 9.5l5 5M21.5 9.5l-5 5" />
              ) : (
                <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" />
              )}
            </svg>
          </button>
        </div>
        {heroPhotos.map((photo, i) => (
          <GalleryImage key={photo.thumb} photo={photo} natural className={`hero-tile t${i}`} />
        ))}
      </section>

      {/* Scroll down: pick a party */}
      <section className="party-cards">
        {parties.map((party) => {
          const cover = party.photos[0]
          const empty = party.photos.length === 0
          return (
            <button
              key={party.slug}
              className={`party-card ${empty ? 'empty' : ''}`}
              onClick={() => !empty && go(`gallery/${party.slug}`)}
              disabled={empty}
            >
              <div className="party-cover">{cover && <GalleryImage photo={cover} />}</div>
              <div className="party-info">
                <h2>{party.title}</h2>
                <span>{empty ? 'photos coming soon' : party.date}</span>
              </div>
            </button>
          )
        })}
      </section>
    </div>
  )
}
