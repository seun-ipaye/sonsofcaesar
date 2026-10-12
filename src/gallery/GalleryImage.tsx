import { useState } from 'react'
import type { Photo } from '../data/parties'

type Props = {
  photo: Photo
  className?: string
  onClick?: () => void
  // Keep the photo's own shape (grids) or fill the box given by CSS (hero)
  natural?: boolean
}

// A thumbnail that loads only when it's about to scroll into view, shows the
// photo's main color until then, and fades in once it has loaded.
export default function GalleryImage({ photo, className = '', onClick, natural }: Props) {
  const [loaded, setLoaded] = useState(false)

  return (
    <div
      className={`gimg ${className}`}
      style={{
        background: photo.color,
        aspectRatio: natural ? `${photo.width} / ${photo.height}` : undefined,
      }}
      onClick={onClick}
    >
      <img
        src={photo.thumb}
        width={photo.width}
        height={photo.height}
        alt=""
        loading="lazy"
        decoding="async"
        className={loaded ? 'loaded' : ''}
        onLoad={() => setLoaded(true)}
      />
    </div>
  )
}
