"""The "here are your tickets" email, sent through Resend."""

import html
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import resend
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, OrderStatus
from app.qr import qr_png

log = logging.getLogger(__name__)
TZ = ZoneInfo('America/Toronto')
# Always the live site: email apps can't load images from localhost
LOGO_URL = 'https://www.sonsofcaesar.xyz/favicon.png'


def fmt_when(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime('%A, %B %-d · %-I:%M %p')


def money(cents: int) -> str:
    return f'${cents / 100:,.2f}'


def render_tickets_email(order: Order) -> tuple[str, str]:
    """Returns (subject, html). Black, minimal, like the site."""
    e = order.event
    esc = html.escape
    tickets_url = f'{settings.site_url}/order/{order.id}'

    ticket_blocks = ''.join(
        f'''
        <tr><td style="padding:24px 0;border-top:1px solid #222;text-align:center">
          <img src="{settings.api_url}/tickets/{t.code}/qr.png" width="220" height="220" alt="QR code"
               style="display:block;margin:0 auto 14px;border:8px solid #fff;background:#fff">
          <div style="font-size:16px;color:#fff">{esc(t.holder_name)}</div>
          <div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#ccc;margin-top:6px">{esc(t.ticket_type.name)}</div>
          <div style="font-size:12px;color:#888;margin-top:4px">Ticket {i} of {len(order.tickets)} · ...{t.code[-4:]}</div>
        </td></tr>'''
        for i, t in enumerate(order.tickets, 1)
    )

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
    <div style="font-size:12px;letter-spacing:4px;text-transform:uppercase;color:#888">You're in</div>
    <h1 style="font-size:32px;font-weight:400;letter-spacing:2px;margin:10px 0 6px">{esc(e.name)}</h1>
    <div style="font-size:14px;color:#ccc">{fmt_when(e.starts_at)}</div>
    {f'<div style="font-size:14px;color:#ccc;margin-top:2px">{esc(e.venue)}</div>' if e.venue else ''}
  </td></tr>
  <tr><td style="text-align:center;padding:28px 0">
    <a href="{tickets_url}" style="display:inline-block;border:1px solid #fff;color:#fff;text-decoration:none;
       padding:12px 28px;font-size:12px;letter-spacing:3px;text-transform:uppercase">View tickets</a>
  </td></tr>
  {ticket_blocks}
  <tr><td style="border-top:1px solid #222;padding-top:20px;font-size:12px;line-height:1.7;color:#888;text-align:center">
    Show each QR code at the door. Each one works once.<br>
    Order for {esc(order.buyer_name)} · {money(order.total_cents)} paid<br>
    Questions? DM <a href="https://instagram.com/socfrvr" style="color:#ccc">@socfrvr</a>
  </td></tr>
</table></td></tr></table></body></html>'''
    return f'Your tickets: {e.name}', body


def send_tickets_email(db: Session, order_id, force: bool = False) -> bool:
    """Send (once) the tickets email for a paid order. Returns True if sent."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != OrderStatus.paid:
        db.rollback()
        return False
    if order.emailed_at and not force:
        db.rollback()
        return False

    subject, body = render_tickets_email(order)
    attachments = [
        {
            'filename': f'ticket-{i}-{t.holder_name.split()[0].lower() if t.holder_name.strip() else "guest"}.png',
            'content': list(qr_png(t.code)),
        }
        for i, t in enumerate(order.tickets, 1)
    ]
    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            'from': settings.email_from,
            'to': [order.buyer_email],
            'subject': subject,
            'html': body,
            # QR images also attached, in case the email app blocks images
            'attachments': attachments,
        }
    )
    order.emailed_at = datetime.now(UTC)
    db.commit()
    log.info('Tickets email sent for order %s', order.id)
    return True
