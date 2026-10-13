import { useStaff } from './Admin'

// Landing page after login. Door staff get the scanner; admins get the dashboard.
// (Both are placeholders until steps 10 and 11.)
export default function AdminHome() {
  const me = useStaff()
  return (
    <section className="admin-placeholder">
      <p className="admin-kicker">{me.role === 'admin' ? 'dashboard' : 'door'}</p>
      <h1>Hey {me.name.split(' ')[0]}.</h1>
      <p>
        {me.role === 'admin'
          ? 'Sales dashboard and attendee list land here in step 11. The scanner arrives in step 10.'
          : 'The scanner arrives here in step 10.'}
      </p>
    </section>
  )
}
