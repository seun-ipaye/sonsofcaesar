import { Navigate, Route, Routes } from 'react-router'
import Intro from './Intro'
import Site from './Site'
import Home from './pages/Home'
import Tickets from './pages/Tickets'
import Gallery from './pages/Gallery'
import About from './pages/About'

export default function App() {
  return (
    <Routes>
      {/* The intro only plays at the main address */}
      <Route path="/" element={<Intro />} />
      <Route element={<Site />}>
        <Route path="/home" element={<Home />} />
        <Route path="/tickets" element={<Tickets />} />
        <Route path="/gallery" element={<Gallery />} />
        <Route path="/about" element={<About />} />
      </Route>
      {/* Unknown addresses go back to the intro */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
