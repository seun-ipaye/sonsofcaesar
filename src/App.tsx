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
import Privacy from './pages/Privacy'
import Admin, { NotForPartners } from './admin/Admin'
import AdminHome from './admin/AdminHome'
import Scanner from './admin/Scanner'
import Combos from './admin/Combos'
import { EXTERNAL } from './NavButton'

// While tickets live on another site (EXTERNAL in NavButton), /tickets redirects there
function TicketsRoute() {
  if (EXTERNAL.tickets) return <ExternalRedirect to={EXTERNAL.tickets} />
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
        <Route path="/tickets/:slug" element={<TicketsRoute />} />
        <Route path="/gallery" element={<Gallery />} />
        <Route path="/gallery/:party" element={<Party />} />
        <Route path="/t/:code" element={<TicketView />} />
        <Route path="/order/:orderId" element={<OrderView />} />
        <Route path="/privacy" element={<Privacy />} />
        {/* <Route path="/about" element={<About />} /> (hidden for now) */}
      </Route>
      {/* Staff area: its own layout, no public header/footer */}
      <Route path="/admin" element={<Admin />}>
        <Route index element={<AdminHome />} />
        <Route path="scan" element={<NotForPartners><Scanner /></NotForPartners>} />
        <Route path="combos" element={<NotForPartners><Combos /></NotForPartners>} />
      </Route>
      {/* Unknown addresses go back to the intro */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
