// Plain-language privacy note for ticket buyers
export default function Privacy() {
  return (
    <article className="privacy">
      <h1>Privacy</h1>
      <p>When you buy tickets we collect your name and email, the names on your tickets, and any email you choose to send a ticket to.</p>
      <p>
        We use them to send tickets, check people in at the door, and contact you about the event you bought for (for
        example, if it's moved or cancelled). We don't sell them or add you to marketing lists.
      </p>
      <p>
        Payments are handled by Stripe. We never see or store your card details. Ticket emails are sent through
        Resend.
      </p>
      <p>
        Photos in our gallery are taken with people's permission at our events. If you'd like a photo of you removed,
        or your details deleted, DM{' '}
        <a href="https://instagram.com/socfrvr" target="_blank" rel="noreferrer">
          @socfrvr
        </a>
        .
      </p>
    </article>
  )
}
