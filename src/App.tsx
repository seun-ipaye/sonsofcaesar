import { useState } from 'react'
import Intro, { type Page } from './Intro'

export default function App() {
  const [page, setPage] = useState<Page | null>(null)

  if (!page) return <Intro onSelect={setPage} />

  return <main className="page">{page}</main>
}
