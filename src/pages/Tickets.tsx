import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, ApiError, formatWhen, money, serviceFeeCents, type SaleEvent, type Tier } from '../api'
import './Tickets.css'

// Show "X left" only when it's getting scarce
const LOW_STOCK = 20

const shortDate = (iso: string) =>
  new Date(iso).toLocaleString('en-CA', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/Toronto',
  })

function tierNote(t: Tier) {
  if (t.status === 'sold_out') return 'Sold out'
  if (t.status === 'ended') return 'Sales ended'
  if (t.status === 'not_yet') return t.sales_start ? `On sale ${shortDate(t.sales_start)}` : 'Not on sale yet'
  const notes = []
  if (t.remaining <= LOW_STOCK) notes.push(`${t.remaining} left`)
  if (t.sales_end) notes.push(`until ${shortDate(t.sales_end)}`)
  return notes.join(' · ')
}

export default function Tickets() {
  const [params] = useSearchParams()
  const [event, setEvent] = useState<SaleEvent | null>(null)
  const [loadError, setLoadError] = useState('')
  const [qty, setQty] = useState<Record<number, number>>({})
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(() => {
    return api<SaleEvent>('/events/current')
      .then((e) => {
        setEvent(e)
        // Keep chosen quantities within what's still available
        setQty((q) =>
          Object.fromEntries(
            e.tiers.map((t) => [t.id, t.status === 'on_sale' ? Math.min(q[t.id] ?? 0, t.remaining, t.max_per_order) : 0]),
          ),
        )
      })
      .catch((e) => setLoadError(e instanceof ApiError && e.status === 404 ? 'none' : e.message))
  }, [])

  // Coming back from Stripe's "back" link: release their held tickets right away,
  // then load (so the stock shown includes the tickets they just let go)
  const cancelledOrder = params.get('cancelled')
  useEffect(() => {
    const release = cancelledOrder
      ? api(`/checkout/${cancelledOrder}/cancel`, { method: 'POST' }).catch(() => {})
      : Promise.resolve()
    release.then(load)
  }, [cancelledOrder, load])

  const subtotal = useMemo(
    () => (event ? event.tiers.reduce((sum, t) => sum + t.price_cents * (qty[t.id] ?? 0), 0) : 0),
    [event, qty],
  )
  const fee = serviceFeeCents(subtotal)
  const count = Object.values(qty).reduce((a, b) => a + b, 0)

  const change = (t: Tier, delta: number) => {
    setError('')
    setQty((q) => {
      const next = Math.max(0, Math.min((q[t.id] ?? 0) + delta, t.max_per_order, t.remaining))
      return { ...q, [t.id]: next }
    })
  }

  const buy = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!event || count === 0) return
    setSubmitting(true)
    setError('')
    try {
      const res = await api<{ checkout_url: string }>('/checkout', {
        method: 'POST',
        body: JSON.stringify({
          event_slug: event.slug,
          items: Object.entries(qty)
            .filter(([, n]) => n > 0)
            .map(([tier_id, quantity]) => ({ tier_id: Number(tier_id), quantity })),
          name: name.trim(),
          email: email.trim(),
        }),
      })
      window.location.href = res.checkout_url
    } catch (err) {
      setSubmitting(false)
      if (err instanceof ApiError && err.status === 422) {
        setError('Check your name and email.')
      } else {
        setError((err as Error).message)
        load() // stock may have changed (e.g. "Only 2 left")
      }
    }
  }

  if (loadError === 'none') {
    return (
      <section className="tickets-empty">
        <p className="tickets-kicker">tickets</p>
        <h1>nothing on sale right now</h1>
        <a href="https://instagram.com/socfrvr" target="_blank" rel="noreferrer">
          @socfrvr for the next one
        </a>
      </section>
    )
  }
  if (loadError) return <p className="tickets-status">{loadError}</p>
  if (!event) return <p className="tickets-status">Loading…</p>

  return (
    <section className="tickets">
      {cancelledOrder && (
        <p className="tickets-banner">Checkout cancelled. You weren't charged.</p>
      )}

      <header className="tickets-head">
        {event.poster_url && <img className="tickets-poster" src={event.poster_url} alt={`${event.name} poster`} />}
        <div>
          <p className="tickets-kicker">tickets</p>
          <h1>{event.name}</h1>
          <p className="tickets-when">{formatWhen(event.starts_at)}</p>
          {event.venue && <p className="tickets-when">{event.venue}</p>}
          {event.description && <p className="tickets-desc">{event.description}</p>}
        </div>
      </header>

      <form className="tickets-form" onSubmit={buy}>
        <ul className="tiers">
          {event.tiers.map((t) => {
            const n = qty[t.id] ?? 0
            const available = t.status === 'on_sale'
            return (
              <li key={t.id} className={`tier ${available ? '' : 'unavailable'}`}>
                <div className="tier-info">
                  <div className="tier-name">{t.name}</div>
                  {t.description && <div className="tier-desc">{t.description}</div>}
                  <div className="tier-note">{tierNote(t)}</div>
                </div>
                <div className="tier-price">{money(t.price_cents)}</div>
                <div className="stepper" aria-label={`${t.name} quantity`}>
                  <button type="button" onClick={() => change(t, -1)} disabled={!available || n === 0} aria-label="Fewer">
                    −
                  </button>
                  <span>{n}</span>
                  <button
                    type="button"
                    onClick={() => change(t, 1)}
                    disabled={!available || n >= Math.min(t.max_per_order, t.remaining)}
                    aria-label="More"
                  >
                    +
                  </button>
                </div>
              </li>
            )
          })}
        </ul>

        {count > 0 && (
          <div className="checkout">
            <dl className="totals">
              <dt>Tickets</dt>
              <dd>{money(subtotal)}</dd>
              <dt>Service fee</dt>
              <dd>{money(fee)}</dd>
              <dt className="total">Total</dt>
              <dd className="total">{money(subtotal + fee)}</dd>
            </dl>

            <label>
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required maxLength={200} />
            </label>
            <label>
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </label>
            <p className="checkout-hint">Your tickets are emailed here.</p>

            {error && <p className="checkout-error">{error}</p>}

            <button className="enter checkout-btn" disabled={submitting}>
              {submitting ? 'One sec…' : `Checkout · ${money(subtotal + fee)}`}
            </button>
            <p className="checkout-hint">Secure payment by Stripe.</p>
          </div>
        )}
      </form>
    </section>
  )
}
