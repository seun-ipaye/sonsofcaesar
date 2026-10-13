import { Link } from 'react-router'
import { useStaff } from './Admin'
import Scanner from './Scanner'

// Door staff go straight to the scanner. Admins get a home page (dashboard in step 11).
export default function AdminHome() {
  const me = useStaff()
  if (me.role === 'door') return <Scanner />
  return (
    <section className="admin-placeholder">
      <p className="admin-kicker">dashboard</p>
      <h1>Hey {me.name.split(' ')[0]}.</h1>
      <p>Sales dashboard and attendee list land here in step 11.</p>
      <Link to="/admin/scan" className="enter admin-scan-link">
        open scanner
      </Link>
    </section>
  )
}
