import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { api, ApiError, formatWhen, money, type OrderPage } from '../api'
import { TicketCard } from './TicketView'
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

  return (
    <section className="order-view">
      <p className="order-kicker">{order.status === 'refunded' ? 'refunded' : "you're in"}</p>
      <h1>{order.event.name}</h1>
      <p className="ticket-when">{formatWhen(order.event.starts_at)}</p>
      {order.event.venue && <p className="ticket-when">{order.event.venue}</p>}
      <p className="order-note">
        {order.tickets.length} {order.tickets.length === 1 ? 'ticket' : 'tickets'} for {order.buyer_name} ·{' '}
        {money(order.total_cents)}. We've emailed them to you too. Each QR works once at the door.
      </p>
      <div className="order-tickets">
        {order.tickets.map((t) => (
          <a key={t.code} href={`/t/${t.code}`} className="order-ticket-link">
            <TicketCard ticket={t} />
          </a>
        ))}
      </div>
    </section>
  )
}
