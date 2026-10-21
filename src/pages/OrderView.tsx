import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { api, ApiError, formatWhen, money, type OrderPage, type TicketEvent } from '../api'
import { TicketCard } from './TicketView'
import SecretAddress from './SecretAddress'
import Chevron from '../Chevron'
import './TicketView.css'
import './OrderView.css'

const POLL_MS = 2000
const GIVE_UP_AFTER_MS = 90_000

// Where Stripe sends buyers after paying, and the "View tickets" link in the email.
// Payment confirmation arrives a moment after the redirect, so we check until it's in.
export default function OrderView() {
  const { orderId = '' } = useParams()
  const [order, setOrder] = useState<OrderPage | null>(null)
  const [error, setError] = useState('')
  const [slow, setSlow] = useState(false)

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const started = Date.now()

    const load = async () => {
      try {
        const o = await api<OrderPage>(`/orders/${orderId}`)
        if (stopped) return
        setOrder(o)
        if (o.status === 'pending') {
          if (Date.now() - started > GIVE_UP_AFTER_MS) return setSlow(true)
          timer = setTimeout(load, POLL_MS)
        }
      } catch (e) {
        if (!stopped) setError(e instanceof ApiError && e.status === 404 ? 'Order not found' : (e as Error).message)
      }
    }
    load()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [orderId])

  if (error) return <p className="ticket-message">{error}</p>
  if (!order) return <p className="ticket-message">Loading…</p>

  if (order.status === 'pending') {
    return (
      <p className="ticket-message">
        {slow
          ? "Your payment is taking longer than usual to confirm. Your tickets will be emailed as soon as it does. If nothing arrives, DM @socfrvr."
          : 'Confirming your payment…'}
      </p>
    )
  }

  if (order.status === 'expired') {
    return <p className="ticket-message">This checkout expired before payment. Nothing was charged.</p>
  }

  // One group per event: a normal order has one, a combo pass has one per night.
  // (Falls back to the older single-event shape for the minute after a deploy.)
  const groups =
    order.groups && order.groups.length
      ? order.groups
      : order.event
        ? [{ event: order.event, tickets: order.tickets }]
        : []
  const single = groups.length === 1
  const title = order.title ?? groups[0]?.event.name ?? 'Your tickets'

  return (
    <section className="order-view">
      <p className="order-kicker">{order.status === 'refunded' ? 'refunded' : "you're in"}</p>
      <h1>{title}</h1>
      {single ? (
        <EventLines event={groups[0].event} />
      ) : (
        <p className="ticket-when">{groups.map((g) => g.event.name).join(' + ')}</p>
      )}
      <p className="order-note">
        {order.tickets.length} {order.tickets.length === 1 ? 'ticket' : 'tickets'} for {order.buyer_name} ·{' '}
        {money(order.total_cents)}. We've emailed them to you too.{' '}
        {single ? 'Each QR works once at the door.' : 'Show each QR at its own event. Each works once.'}
      </p>

      {groups.map((g) => (
        <div className="order-group" key={g.event.name + g.event.starts_at}>
          {!single && (
            <div className="order-group-head">
              <h2>{g.event.name}</h2>
              <EventLines event={g.event} />
            </div>
          )}
          <div className="order-tickets">
            {g.tickets.map((t) => (
              <a key={t.code} href={`/t/${t.code}`} className="order-ticket-link">
                <TicketCard ticket={t} />
              </a>
            ))}
          </div>
          <SecretAddress address={g.event.address} />
        </div>
      ))}

      {order.status === 'paid' && <ResendTickets order={order} />}
    </section>
  )
}

function EventLines({ event }: { event: TicketEvent }) {
  return (
    <>
      <p className="ticket-when">{formatWhen(event.starts_at)}</p>
      {event.venue && !event.address && <p className="ticket-when">{event.venue}</p>}
    </>
  )
}

// "Didn't get your tickets?": fix the email address and send the same tickets again
function ResendTickets({ order }: { order: OrderPage }) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [hint, setHint] = useState(order.email_hint)
  const [left, setLeft] = useState(order.resends_left)
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setStatus(null)
    try {
      const r = await api<{ sent_to: string; resends_left: number }>(`/orders/${order.id}/resend`, {
        method: 'POST',
        body: JSON.stringify({ email: email.trim() }),
      })
      setHint(r.sent_to)
      setLeft(r.resends_left)
      setStatus({ ok: true, text: `Sent to ${r.sent_to}. Check your spam folder too.` })
    } catch (err) {
      setStatus({
        ok: false,
        text: err instanceof ApiError && err.status === 422 ? 'That email doesn\'t look right.' : (err as Error).message,
      })
    }
    setBusy(false)
  }

  return (
    <div className="resend">
      <button type="button" className={`resend-toggle ${open ? 'open' : ''}`} onClick={() => setOpen(!open)}>
        <Chevron />
        didn't get your tickets?
      </button>
      {open && (
        <form onSubmit={submit} className="resend-form">
          <p>
            We sent them to <strong>{hint}</strong>. Typo? Enter the right email and we'll send the same tickets
            again.
          </p>
          <div className="resend-row">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Your email"
              required
              autoComplete="email"
            />
            <button className="enter" disabled={busy || left === 0}>
              {busy ? 'Sending…' : 'Send'}
            </button>
          </div>
          {status && <p className={status.ok ? 'resend-ok' : 'resend-error'}>{status.text}</p>}
        </form>
      )}
    </div>
  )
}
