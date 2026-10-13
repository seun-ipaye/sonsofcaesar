import { useStaff } from './Admin'
import Dashboard from './Dashboard'
import Scanner from './Scanner'

// Door staff go straight to the scanner; admins get the dashboard.
export default function AdminHome() {
  const me = useStaff()
  return me.role === 'door' ? <Scanner /> : <Dashboard />
}
