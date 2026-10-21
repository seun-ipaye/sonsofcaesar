import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { api, ApiError, formatWhen, qrUrl, type TicketPage } from '../api'
import SecretAddress from './SecretAddress'
import './TicketView.css'

// One ticket, full screen-ish: what you show at the door.
export default function TicketView() {
  const { code = '' } = useParams()
  const [ticket, setTicket] = useState<TicketPage | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<TicketPage>(`/tickets/${code}`)
      .then(setTicket)
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? 'Ticket not found' : e.message))
  }, [code])

  if (error) return <p className="ticket-message">{error}</p>
  if (!ticket) return <p className="ticket-message">Loading…</p>

  return (
    <section className="ticket-view">
      <TicketCard ticket={ticket} />
      <SecretAddress address={ticket.event.address} />
      <h1>{ticket.event.name}</h1>
      <p className="ticket-when">{formatWhen(ticket.event.starts_at)}</p>
      {ticket.event.venue && !ticket.event.address && <p className="ticket-when">{ticket.event.venue}</p>}
    </section>
  )
}

// The QR card, reused on the order page
export function TicketCard({ ticket }: { ticket: TicketPage | (Omit<TicketPage, 'event'> & { event?: never }) }) {
  const state = ticket.status === 'void' ? 'void' : ticket.checked_in_at ? 'used' : 'valid'
  return (
    <div className={`ticket-card ${state}`}>
      <div className="ticket-qr">
        <img src={qrUrl(ticket.code)} alt="Ticket QR code" />
        {state !== 'valid' && <span className="ticket-stamp">{state === 'void' ? 'refunded' : 'used'}</span>}
      </div>
      <div className="ticket-tier">
        {ticket.tier}
        {ticket.gender ? ` · ${ticket.gender === 'ladies' ? 'Ladies' : 'Men'}` : ''}
      </div>
      <div className="ticket-holder">
        {ticket.holder_name} · …{ticket.code.slice(-4)}
      </div>
    </div>
  )
}
