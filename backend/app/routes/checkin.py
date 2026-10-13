"""Door check-in: scan a QR (or look someone up) and let them in once."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.auth import current_staff
from app.db import get_db
from app.emails import mask_email
from app.models import Event, Order, Staff, StaffRole, Ticket, TicketStatus
from app.schemas import CheckinIn, CheckinResult, CheckinStats, CheckinTicket, StaffEventOut

router = APIRouter(prefix='/checkin', tags=['checkin'], dependencies=[Depends(current_staff)])

UNDO_WINDOW = timedelta(minutes=5)


def _event(db: Session, slug: str) -> Event:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, 'Event not found')
    return event


def _out(t: Ticket) -> CheckinTicket:
    return CheckinTicket(
        code=t.code,
        holder_name=t.holder_name,
        tier=t.ticket_type.name,
        status=t.status.value,
        checked_in_at=t.checked_in_at,
        checked_in_by=t.checked_in_by.name if t.checked_in_by else None,
        buyer_email_hint=mask_email(t.order.buyer_email),
    )


def _extract_code(raw: str) -> str:
    # The QR holds just the code, but accept a pasted ticket link too (".../t/<code>")
    raw = raw.strip()
    return raw.rsplit('/t/', 1)[-1].split('?')[0] if '/t/' in raw else raw


@router.get('/events', response_model=list[StaffEventOut])
def events(db: Session = Depends(get_db)):
    """Events worth scanning for: anything from yesterday onward, soonest first."""
    since = datetime.now(UTC) - timedelta(days=1)
    rows = db.scalars(
        select(Event).where(func.coalesce(Event.ends_at, Event.starts_at) > since).order_by(Event.starts_at)
    )
    return [StaffEventOut(slug=e.slug, name=e.name, starts_at=e.starts_at) for e in rows]


@router.post('', response_model=CheckinResult)
def check_in(body: CheckinIn, db: Session = Depends(get_db), staff: Staff = Depends(current_staff)):
    event = _event(db, body.event_slug)
    code = _extract_code(body.code)

    # One atomic step: only flips a valid, not-yet-used ticket for THIS event.
    # If two phones scan the same QR at once, exactly one of them gets a row back.
    claimed = db.execute(
        update(Ticket)
        .where(
            Ticket.code == code,
            Ticket.event_id == event.id,
            Ticket.status == TicketStatus.valid,
            Ticket.checked_in_at.is_(None),
        )
        .values(checked_in_at=func.now(), checked_in_by_id=staff.id)
        .returning(Ticket.id)
    ).scalar()
    db.commit()

    ticket = db.scalar(select(Ticket).where(Ticket.code == code))
    if claimed:
        return CheckinResult(result='ok', ticket=_out(ticket))
    if not ticket:
        return CheckinResult(result='not_found')
    if ticket.event_id != event.id:
        return CheckinResult(result='wrong_event', ticket=_out(ticket), other_event=ticket.event.name)
    if ticket.status == TicketStatus.void:
        return CheckinResult(result='void', ticket=_out(ticket))
    return CheckinResult(result='already', ticket=_out(ticket))


@router.post('/undo', response_model=CheckinTicket)
def undo(body: CheckinIn, db: Session = Depends(get_db), staff: Staff = Depends(current_staff)):
    """Undo a check-in made by mistake. Door staff: only their own, within 5 minutes."""
    event = _event(db, body.event_slug)
    ticket = db.scalar(
        select(Ticket).where(Ticket.code == _extract_code(body.code), Ticket.event_id == event.id).with_for_update()
    )
    if not ticket or not ticket.checked_in_at:
        raise HTTPException(404, 'Not checked in')
    if staff.role != StaffRole.admin:
        if ticket.checked_in_by_id != staff.id or datetime.now(UTC) - ticket.checked_in_at > UNDO_WINDOW:
            raise HTTPException(403, 'Only an admin can undo this one')
    ticket.checked_in_at = None
    ticket.checked_in_by_id = None
    db.commit()
    return _out(ticket)


@router.get('/search', response_model=list[CheckinTicket])
def search(event: str, q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db)):
    """Manual lookup by ticket name, buyer name/email, or the last characters of the code."""
    ev = _event(db, event)
    like = f'%{q.strip()}%'
    rows = db.scalars(
        select(Ticket)
        .join(Order)
        .where(
            Ticket.event_id == ev.id,
            or_(
                Ticket.holder_name.ilike(like),
                Order.buyer_name.ilike(like),
                Order.buyer_email.ilike(like),
                Ticket.code.ilike(f'%{q.strip()}'),  # code ending with what they typed
            ),
        )
        .order_by(Ticket.holder_name)
        .limit(25)
    )
    return [_out(t) for t in rows]


@router.get('/stats', response_model=CheckinStats)
def stats(event: str, db: Session = Depends(get_db)):
    ev = _event(db, event)
    valid = select(Ticket).where(Ticket.event_id == ev.id, Ticket.status == TicketStatus.valid).subquery()
    total = db.scalar(select(func.count()).select_from(valid))
    checked = db.scalar(select(func.count()).select_from(valid).where(valid.c.checked_in_at.is_not(None)))
    return CheckinStats(checked_in=checked, total=total)
