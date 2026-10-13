"""Public ticket and order pages. The ticket code and order id are long random
strings, so knowing one is what proves you hold it (like a link to a Google Doc)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.emails import mask_email, send_tickets_email
from app.models import Order, OrderStatus, Ticket
from app.qr import qr_png, qr_svg
from app.schemas import OrderPageOut, ResendIn, TicketEventOut, TicketOut, TicketPageOut

router = APIRouter(tags=['tickets'])

MAX_RESENDS = 5
RESEND_COOLDOWN = timedelta(minutes=1)

# QR images never change for a code, so browsers/email apps can cache them
IMMUTABLE = {'Cache-Control': 'public, max-age=31536000, immutable'}


def _ticket(db: Session, code: str) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.code == code))
    if not ticket:
        raise HTTPException(404, 'Ticket not found')
    return ticket


def _ticket_out(t: Ticket) -> TicketOut:
    return TicketOut(
        code=t.code, tier=t.ticket_type.name, holder_name=t.holder_name,
        status=t.status.value, checked_in_at=t.checked_in_at,
    )


def _event_out(e) -> TicketEventOut:
    return TicketEventOut(name=e.name, venue=e.venue, starts_at=e.starts_at, ends_at=e.ends_at)


@router.get('/tickets/{code}', response_model=TicketPageOut)
def get_ticket(code: str, db: Session = Depends(get_db)):
    t = _ticket(db, code)
    return TicketPageOut(**_ticket_out(t).model_dump(), event=_event_out(t.event))


@router.get('/tickets/{code}/qr.png')
def ticket_qr_png(code: str, db: Session = Depends(get_db)):
    _ticket(db, code)  # only draw QRs for real tickets
    return Response(qr_png(code), media_type='image/png', headers=IMMUTABLE)


@router.get('/tickets/{code}/qr.svg')
def ticket_qr_svg(code: str, db: Session = Depends(get_db)):
    _ticket(db, code)
    return Response(qr_svg(code), media_type='image/svg+xml', headers=IMMUTABLE)


@router.get('/orders/{order_id}', response_model=OrderPageOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """The "you're in" page polls this until the payment is confirmed."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, 'Order not found')
    return OrderPageOut(
        id=str(order.id),
        status=order.status.value,
        buyer_name=order.buyer_name,
        email_hint=mask_email(order.buyer_email),
        resends_left=max(MAX_RESENDS - order.resend_count, 0),
        total_cents=order.total_cents,
        event=_event_out(order.event),
        tickets=[_ticket_out(t) for t in sorted(order.tickets, key=lambda t: t.ticket_type.sort_order)],
    )


@router.post('/orders/{order_id}/resend')
def resend_order_email(order_id: uuid.UUID, body: ResendIn, db: Session = Depends(get_db)):
    """"Didn't get your tickets?": optionally fix the email, then send the SAME tickets again.
    Limited per order so the form can't be used to spam people."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != OrderStatus.paid:
        raise HTTPException(404, 'Order not found')
    now = datetime.now(UTC)
    if order.resend_count >= MAX_RESENDS:
        raise HTTPException(429, 'Resend limit reached. DM @socfrvr and we\'ll sort it out.')
    if order.last_resent_at and now - order.last_resent_at < RESEND_COOLDOWN:
        raise HTTPException(429, 'Just sent. Give it a minute and check your spam folder.')

    order.buyer_email = body.email.lower()
    order.resend_count += 1
    order.last_resent_at = now
    db.commit()
    try:
        send_tickets_email(db, order.id, force=True)
    except Exception:
        raise HTTPException(502, "Couldn't send right now. Try again in a minute.")
    return {'sent_to': mask_email(order.buyer_email), 'resends_left': MAX_RESENDS - order.resend_count}
