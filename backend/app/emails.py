"""Ticket emails, sent through Resend.

- The buyer gets every ticket in their order.
- Anyone the buyer sent a ticket to ("send it to them too") gets just that ticket.
"""

import html
import logging
from urllib.parse import quote_plus
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import resend
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import GENDER_LABEL, Event, Order, OrderStatus, Ticket, TicketStatus, public_venue
from app.qr import qr_png

log = logging.getLogger(__name__)
TZ = ZoneInfo('America/Toronto')
# Always the live site: email apps can't load images from localhost
SITE_FOR_EMAIL = 'https://www.sonsofcaesar.xyz'
LOGO_URL = f'{SITE_FOR_EMAIL}/favicon.png'


def fmt_when(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime('%A, %B %-d · %-I:%M %p')


def money(cents: int) -> str:
    return f'${cents / 100:,.2f}'


def mask_email(email: str) -> str:
    """se•••@gmail.com: enough to recognise your own address, not enough to read it."""
    local, _, domain = email.partition('@')
    return f'{local[:2]}•••@{domain}'


def ticket_label(t: Ticket) -> str:
    """e.g. "GA · Ladies" for gender-priced tickets, else just the tier."""
    return f'{t.ticket_type.name} · {GENDER_LABEL[t.gender]}' if t.gender else t.ticket_type.name


def maps_url(address: str) -> str:
    return 'https://www.google.com/maps/search/?api=1&query=' + quote_plus(address)


def venue_or_address(e: Event) -> str:
    """Ticket holders get the real address (with a Maps link) for secret-address
    events; everyone else's venue line stays as it is."""
    esc = html.escape
    if e.secret_address and e.address:
        return f'''<div style="margin-top:14px;padding:12px 14px;border:1px solid #333;font-size:15px;color:#fff">
      <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-bottom:6px">Address</div>
      {esc(e.address)}<br>
      <a href="{maps_url(e.address)}" style="font-size:12px;color:#ccc">Open in Maps</a>
    </div>'''
    venue = public_venue(e)
    return f'<div style="font-size:14px;color:#ccc;margin-top:2px">{esc(venue)}</div>' if venue else ''


def _render(order: Order, tickets: list[Ticket], kicker: str, button_url: str, button_label: str, footer: str) -> str:
    e = order.event
    esc = html.escape
    ticket_blocks = ''.join(
        f'''
        <tr><td style="padding:24px 0;border-top:1px solid #222;text-align:center">
          <img src="{settings.api_url}/tickets/{t.code}/qr.png" width="220" height="220" alt="QR code"
               style="display:block;margin:0 auto 14px;border:8px solid #fff;background:#fff">
          <div style="font-size:16px;color:#fff">{esc(t.holder_name)}</div>
          <div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#ccc;margin-top:6px">{esc(ticket_label(t))}</div>
          <div style="font-size:12px;color:#888;margin-top:4px">...{t.code[-4:]}</div>
        </td></tr>'''
        for t in tickets
    )
    # The event flyer, under the logo. Email apps need a full https:// link.
    poster = e.poster_url or ''
    if poster.startswith('/'):
        poster = SITE_FOR_EMAIL + poster
    poster_block = (
        f'''<tr><td style="padding-bottom:28px">
    <img src="{esc(poster)}" width="480" alt="{esc(e.name)} flyer" style="display:block;width:100%;max-width:480px;height:auto">
  </td></tr>'''
        if poster.startswith('https://')
        else ''
    )
    return f'''<!doctype html>
<html><body style="margin:0;padding:0;background:#000">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#000">
<tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:480px;font-family:Helvetica,Arial,sans-serif;color:#fff">
  <tr><td style="text-align:center;padding-bottom:24px">
    <img src="{LOGO_URL}" width="64" height="64" alt="Sons of Caesar">
  </td></tr>
  {poster_block}
  <tr><td style="text-align:center">
    <div style="font-size:12px;letter-spacing:4px;text-transform:uppercase;color:#888">{esc(kicker)}</div>
    <h1 style="font-size:32px;font-weight:400;letter-spacing:2px;margin:10px 0 6px">{esc(e.name)}</h1>
    <div style="font-size:14px;color:#ccc">{fmt_when(e.starts_at)}</div>
    {venue_or_address(e)}
  </td></tr>
  <tr><td style="text-align:center;padding:28px 0">
    <a href="{button_url}" style="display:inline-block;border:1px solid #fff;color:#fff;text-decoration:none;
       padding:12px 28px;font-size:12px;letter-spacing:3px;text-transform:uppercase">{esc(button_label)}</a>
  </td></tr>
  {ticket_blocks}
  <tr><td style="border-top:1px solid #222;padding-top:20px;font-size:12px;line-height:1.7;color:#888;text-align:center">
    {footer}<br>
    Questions? DM <a href="https://instagram.com/socfrvr" style="color:#ccc">@socfrvr</a>
  </td></tr>
</table></td></tr></table></body></html>'''


def render_tickets_email(order: Order) -> tuple[str, str]:
    """The buyer's email: every ticket in the order."""
    body = _render(
        order,
        order.tickets,
        kicker="You're in",
        button_url=f'{settings.site_url}/order/{order.id}',
        button_label='View tickets',
        footer=(
            'Show each QR code at the door. Each one works once.<br>'
            'All sales are final; if the event is cancelled you\'ll get a full refund.<br>'
            f'Order for {html.escape(order.buyer_name)} · {money(order.total_cents)} paid'
        ),
    )
    return f'Your tickets: {order.event.name}', body


def render_friend_email(order: Order, ticket: Ticket) -> tuple[str, str]:
    """A friend's email: just their ticket, from the buyer's order."""
    first = order.buyer_name.split()[0] if order.buyer_name.strip() else 'Someone'
    body = _render(
        order,
        [ticket],
        kicker=f'{first} got you a ticket',
        button_url=f'{settings.site_url}/t/{ticket.code}',
        button_label='View ticket',
        footer=(
            'Show this QR code at the door. It works once.<br>'
            f'From {html.escape(order.buyer_name)}\'s order'
        ),
    )
    return f'{first} got you a ticket: {order.event.name}', body


def _attachment(n: int, t: Ticket) -> dict:
    first = t.holder_name.split()[0].lower() if t.holder_name.strip() else 'guest'
    return {'filename': f'ticket-{n}-{first}.png', 'content': list(qr_png(t.code))}


def _send(to: str, subject: str, body: str, attachments: list[dict]) -> None:
    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            'from': settings.email_from,
            'to': [to],
            'subject': subject,
            'html': body,
            # QR images also attached, in case the email app blocks images
            'attachments': attachments,
        }
    )


def send_tickets_email(db: Session, order_id, force: bool = False) -> bool:
    """Send (once) the buyer's email for a paid order. Returns True if sent."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != OrderStatus.paid or (order.emailed_at and not force):
        db.rollback()
        return False
    subject, body = render_tickets_email(order)
    _send(order.buyer_email, subject, body, [_attachment(i, t) for i, t in enumerate(order.tickets, 1)])
    order.emailed_at = datetime.now(UTC)
    db.commit()
    log.info('Tickets email sent for order %s', order.id)
    return True


def send_friend_emails(db: Session, order_id) -> int:
    """Email each ticket the buyer sent to someone else (once each). Returns how many sent."""
    order = db.get(Order, order_id)
    if not order or order.status != OrderStatus.paid:
        return 0
    ticket_ids = [t.id for t in order.tickets if t.holder_email and t.holder_email != order.buyer_email]
    db.commit()
    sent = 0
    for ticket_id in ticket_ids:
        # Lock this ticket and re-check, so two overlapping runs can't both send it
        t = db.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
        if t.emailed_at:
            db.rollback()
            continue
        subject, body = render_friend_email(order, t)
        _send(t.holder_email, subject, body, [_attachment(1, t)])
        t.emailed_at = datetime.now(UTC)
        db.commit()
        sent += 1
    if sent:
        log.info('Order %s: sent %s tickets to friends', order.id, sent)
    return sent


def render_address_email(event: Event, button_url: str) -> tuple[str, str]:
    """"Here's the address": sent from the dashboard when it's added or changed."""
    esc = html.escape
    body = f'''<!doctype html>
<html><body style="margin:0;padding:0;background:#000">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#000">
<tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:480px;font-family:Helvetica,Arial,sans-serif;color:#fff">
  <tr><td style="text-align:center;padding-bottom:24px">
    <img src="{LOGO_URL}" width="64" height="64" alt="Sons of Caesar">
  </td></tr>
  <tr><td style="text-align:center">
    <div style="font-size:12px;letter-spacing:4px;text-transform:uppercase;color:#888">The address</div>
    <h1 style="font-size:32px;font-weight:400;letter-spacing:2px;margin:10px 0 6px">{esc(event.name)}</h1>
    <div style="font-size:14px;color:#ccc">{fmt_when(event.starts_at)}</div>
    {venue_or_address(event)}
  </td></tr>
  <tr><td style="text-align:center;padding:28px 0">
    <a href="{button_url}" style="display:inline-block;border:1px solid #fff;color:#fff;text-decoration:none;
       padding:12px 28px;font-size:12px;letter-spacing:3px;text-transform:uppercase">View tickets</a>
  </td></tr>
  <tr><td style="border-top:1px solid #222;padding-top:20px;font-size:12px;line-height:1.7;color:#888;text-align:center">
    Please keep the address to ticket holders.<br>
    Questions? DM <a href="https://instagram.com/socfrvr" style="color:#ccc">@socfrvr</a>
  </td></tr>
</table></td></tr></table></body></html>'''
    return f'The address for {event.name}', body


def address_recipients(db: Session, event: Event) -> list[tuple[str, str]]:
    """Everyone holding a valid ticket: buyers (link to their order) and friends
    they sent tickets to (link to that ticket). One email per address."""
    seen: dict[str, str] = {}
    orders = db.scalars(select(Order).where(Order.event_id == event.id, Order.status == OrderStatus.paid))
    for order in orders:
        valid = [t for t in order.tickets if t.status == TicketStatus.valid]
        if not valid:
            continue
        seen.setdefault(order.buyer_email.lower(), f'{settings.site_url}/order/{order.id}')
        for t in valid:
            if t.holder_email:
                seen.setdefault(t.holder_email.lower(), f'{settings.site_url}/t/{t.code}')
    return list(seen.items())


def send_address_emails(db: Session, event: Event) -> int:
    """Email the secret address to every ticket holder, in batches of 100. Returns count."""
    recipients = address_recipients(db, event)
    resend.api_key = settings.resend_api_key
    for start in range(0, len(recipients), 100):
        batch = []
        for email, link in recipients[start : start + 100]:
            subject, body = render_address_email(event, link)
            batch.append({'from': settings.email_from, 'to': [email], 'subject': subject, 'html': body})
        resend.Batch.send(batch)
    event.address_emailed_at = datetime.now(UTC)
    db.commit()
    log.info('Address emailed to %s ticket holders for %s', len(recipients), event.slug)
    return len(recipients)
