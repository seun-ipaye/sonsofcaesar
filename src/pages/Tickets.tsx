import './Tickets.css'

// Placeholder until ticketing is built. People only land here from a direct link,
// since the Tickets buttons show "coming soon" instead of navigating.
export default function Tickets() {
  return (
    <section className="tickets-soon">
      <p className="tickets-kicker">tickets</p>
      <h1>coming soon</h1>
      <a href="https://instagram.com/socfrvr" target="_blank" rel="noreferrer">
        @socfrvr for the next one
      </a>
    </section>
  )
}
