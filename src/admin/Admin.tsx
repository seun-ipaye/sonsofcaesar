import { createContext, useContext, useEffect, useState } from 'react'
import { Link, Outlet } from 'react-router'
import { api, ApiError, type StaffMe } from '../api'
import './Admin.css'

const StaffContext = createContext<StaffMe | null>(null)
export const useStaff = () => useContext(StaffContext)!

// Everything under /admin: checks who's logged in, shows the login form if nobody.
export default function Admin() {
  const [me, setMe] = useState<StaffMe | null | undefined>(undefined) // undefined = still checking

  useEffect(() => {
    api<StaffMe>('/auth/me')
      .then(setMe)
      .catch(() => setMe(null))
  }, [])

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => {})
    setMe(null)
  }

  if (me === undefined) return <div className="admin-shell" />
  if (me === null) return <Login onLogin={setMe} />

  return (
    <StaffContext.Provider value={me}>
      <div className="admin-shell">
        <header className="admin-header">
          <Link to="/admin" className="admin-brand">
            <img src="/favicon.png" alt="" /> staff
          </Link>
          <div className="admin-who">
            {me.name} · {me.role}
            <button onClick={logout}>log out</button>
          </div>
        </header>
        <main className="admin-main">
          <Outlet />
        </main>
      </div>
    </StaffContext.Provider>
  )
}

function Login({ onLogin }: { onLogin: (me: StaffMe) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await api<StaffMe>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server')
      setBusy(false)
    }
  }

  return (
    <div className="admin-shell admin-login">
      <form onSubmit={submit}>
        <img src="/favicon.png" alt="Sons of Caesar" className="admin-login-logo" />
        <p className="admin-kicker">staff</p>
        <label>
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="admin-error">{error}</p>}
        <button className="enter" disabled={busy}>
          {busy ? 'One sec…' : 'Log in'}
        </button>
      </form>
    </div>
  )
}

// Pages partners (collabs) can't use: the scanner and combos
export function NotForPartners({ children }: { children: React.ReactNode }) {
  if (useStaff().role === 'partner') {
    return <p className="admin-placeholder">This page isn't available on your account.</p>
  }
  return <>{children}</>
}
