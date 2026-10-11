import { useState } from 'react'
import Intro, { type Page } from './Intro'
import Site from './Site'

export default function App() {
  const [page, setPage] = useState<Page | null>(null)

  if (!page) return <Intro onSelect={setPage} />

  return <Site page={page} onNavigate={setPage} />
}
