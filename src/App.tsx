import { useState } from 'react'
import Intro from './Intro'

export default function App() {
  const [entered, setEntered] = useState(false)

  if (!entered) return <Intro onEnter={() => setEntered(true)} />

  return <main className="home" />
}
