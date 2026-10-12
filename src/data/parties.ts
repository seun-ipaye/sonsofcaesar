import gallery from './gallery.json'

export type Photo = {
  source: string
  width: number
  height: number
  color: string
  thumb: string
  full: string
}

// One entry per party, newest first. `slug` matches the folder name in
// gallery-source/ ("VOL II" -> "vol-ii") and the address /gallery/<slug>.
const PARTY_INFO = [
  { slug: 'vol-ii', title: 'VOL II', date: 'April 3, 2026' },
  { slug: 'on-deck', title: 'ON DECK', date: 'March 6, 2026' },
]

type Manifest = {
  hero?: { video: string; poster: string }
  parties: Record<string, { photos: Photo[] }>
}
const manifest = gallery as Manifest

export const hero = manifest.hero

export const parties = PARTY_INFO.map((p) => ({
  ...p,
  photos: manifest.parties[p.slug]?.photos ?? [],
}))

export type Party = (typeof parties)[number]

export const allPhotos = parties.flatMap((p) => p.photos)
