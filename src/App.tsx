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
import { EXTERNAL } from './NavButton'

// Old /tickets links go straight to the ticketing site
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
        <Route path="/tickets" element={EXTERNAL.tickets ? <ExternalRedirect to={EXTERNAL.tickets} /> : <Tickets />} />
        <Route path="/gallery" element={<Gallery />} />
        <Route path="/gallery/:party" element={<Party />} />
        <Route path="/t/:code" element={<TicketView />} />
        <Route path="/order/:orderId" element={<OrderView />} />
        {/* <Route path="/about" element={<About />} /> (hidden for now) */}
      </Route>
      {/* Unknown addresses go back to the intro */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
