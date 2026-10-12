import { useState } from 'react'
import { Navigate, useParams } from 'react-router'
import { parties } from '../data/parties'
import GalleryImage from '../gallery/GalleryImage'
import Lightbox from '../gallery/Lightbox'
import '../gallery/Gallery.css'

// Every photo from one party, straight into the grid
export default function Party() {
  const { party: slug } = useParams()
  const party = parties.find((p) => p.slug === slug)
  const [open, setOpen] = useState<number | null>(null)

  if (!party || party.photos.length === 0) return <Navigate to="/gallery" replace />

  return (
    <div className="party">
      <div className="party-grid">
        {party.photos.map((photo, i) => (
          <GalleryImage key={photo.thumb} photo={photo} natural onClick={() => setOpen(i)} />
        ))}
      </div>

      {open !== null && (
        <Lightbox photos={party.photos} index={open} onChange={setOpen} onClose={() => setOpen(null)} />
      )}
    </div>
  )
}
