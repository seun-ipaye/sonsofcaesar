import { Navigate, Route, Routes } from 'react-router'
import Intro from './Intro'
import Site from './Site'
import Home from './pages/Home'
import Tickets from './pages/Tickets'
import Gallery from './pages/Gallery'
// import About from './pages/About' (hidden for now)
import Party from './pages/Party'
import TicketView from './pages/TicketView'
import OrderView from './pages/OrderView'
import Admin from './admin/Admin'
import AdminHome from './admin/AdminHome'
import Scanner from './admin/Scanner'
import { EXTERNAL } from './NavButton'

// Old /tickets links go straight to the ticketing site
// While tickets live on Bloom, /tickets redirects there, except for testers:
// /tickets?preview shows our own page (remembered for this browser tab, so the
// return trip from Stripe keeps working).
function TicketsRoute() {
  const params = new URLSearchParams(window.location.search)
  let preview = params.has('preview')
  try {
    if (preview) sessionStorage.setItem('soc-tickets-preview', '1')
    preview ||= sessionStorage.getItem('soc-tickets-preview') === '1'
  } catch {
    /* storage blocked: the ?preview link still works on its own */
  }
  if (EXTERNAL.tickets && !preview) return <ExternalRedirect to={EXTERNAL.tickets} />
  return <Tickets />
}

function ExternalRedirect({ to }: { to: string }) {
  window.location.replace(to)
  return null
}

export default function App() {
  return (
    <Routes>
      {/* The intro only plays at the main address */}
      <Route path="/" element={<Intro />} />
      <Route element={<Site />}>
        <Route path="/home" element={<Home />} />
        <Route path="/tickets" element={<TicketsRoute />} />
        <Route path="/gallery" element={<Gallery />} />
        <Route path="/gallery/:party" element={<Party />} />
        <Route path="/t/:code" element={<TicketView />} />
        <Route path="/order/:orderId" element={<OrderView />} />
        {/* <Route path="/about" element={<About />} /> (hidden for now) */}
      </Route>
      {/* Staff area: its own layout, no public header/footer */}
      <Route path="/admin" element={<Admin />}>
        <Route index element={<AdminHome />} />
        <Route path="scan" element={<Scanner />} />
      </Route>
      {/* Unknown addresses go back to the intro */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
