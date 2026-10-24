"""Admin dashboard: sales numbers, attendees, and editing events and tiers. Admins only."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.auth import admin_or_partner_view, current_staff, partner_event_ids
from app.db import get_db
from app.inventory import taken_counts
from app.models import GENDER_LABEL, Event, Gender, Order, OrderItem, OrderStatus, Staff, StaffRole, Ticket, TicketStatus, TicketType
from app.emails import mask_email
from app.schemas import (
    AdminEventListItem,
    AdminEventOut,
    AdminTierOut,
    AttendeeOut,
    EventIn,
    EventPatch,
    SalesDay,
    TierIn,
    TierPatch,
)

# Admins: everything. Partners: read-only overview + attendees of their own events
# (see admin_or_partner_view; anything not on its list is admin-only).
router = APIRouter(prefix='/admin', tags=['admin'], dependencies=[Depends(admin_or_partner_view)])


def _event(db: Session, slug: str) -> Event:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, 'Event not found')
    return event


# What each valid ticket was sold for: the price on its order line
_ticket_price = (
    select(
        Ticket.id.label('ticket_id'),
        Ticket.ticket_type_id,
        Ticket.gender,
        Ticket.checked_in_at,
        Order.paid_at,
        Order.combo_id,
        OrderItem.unit_price_cents,
    )
    .join(Order, Ticket.order_id == Order.id)
    .join(
        OrderItem,
        and_(
            OrderItem.order_id == Ticket.order_id,
            OrderItem.ticket_type_id == Ticket.ticket_type_id,
            # A tier can have a Ladies line and a Men line in one order: match the right one
            OrderItem.gender.is_not_distinct_from(Ticket.gender),
        ),
    )
    .where(Ticket.status == TicketStatus.valid)
)


def _tier_stats(db: Session, event: Event) -> dict[int, dict]:
    ids = [t.id for t in event.ticket_types]
    sold = _ticket_price.where(Ticket.event_id == event.id).subquery()
    rows = db.execute(
        select(
            sold.c.ticket_type_id,
            func.count(),
            func.count(sold.c.checked_in_at),
            func.coalesce(func.sum(sold.c.unit_price_cents), 0),
        ).group_by(sold.c.ticket_type_id)
    ).all()
    stats = {
        i: {'sold': 0, 'checked_in': 0, 'revenue_cents': 0, 'sold_ladies': 0, 'sold_men': 0, 'sold_combo': 0}
        for i in ids
    }
    for tier_id, n, checked, revenue in rows:
        stats[tier_id].update(sold=n, checked_in=checked, revenue_cents=int(revenue))
    for tier_id, gender, n in db.execute(
        select(sold.c.ticket_type_id, sold.c.gender, func.count())
        .where(sold.c.gender.is_not(None))
        .group_by(sold.c.ticket_type_id, sold.c.gender)
    ).all():
        stats[tier_id][f'sold_{Gender(gender).value}'] = n
    for tier_id, n in db.execute(
        select(sold.c.ticket_type_id, func.count())
        .where(sold.c.combo_id.is_not(None))
        .group_by(sold.c.ticket_type_id)
    ).all():
        stats[tier_id]['sold_combo'] = n
    # Held = currently in someone's checkout (taken counts paid + active holds)
    taken = taken_counts(db, ids)
    paid_qty = dict(
        db.execute(
            select(OrderItem.ticket_type_id, func.sum(OrderItem.quantity))
            .join(Order)
            .where(OrderItem.ticket_type_id.in_(ids), Order.status == OrderStatus.paid)
            .group_by(OrderItem.ticket_type_id)
        ).all()
    )
    for i in ids:
        stats[i]['held'] = max(taken[i] - int(paid_qty.get(i, 0)), 0)
    return stats


@router.get('/events', response_model=list[AdminEventListItem])
def list_events(db: Session = Depends(get_db), staff: Staff = Depends(current_staff)):
    events = db.scalars(select(Event).order_by(Event.starts_at.desc())).all()
    if staff.role == StaffRole.partner:
        mine = partner_event_ids(db, staff)
        events = [e for e in events if e.id in mine]
    sold = dict(
        db.execute(
            select(Ticket.event_id, func.count()).where(Ticket.status == TicketStatus.valid).group_by(Ticket.event_id)
        ).all()
    )
    return [
        AdminEventListItem(
            slug=e.slug,
            name=e.name,
            starts_at=e.starts_at,
            on_sale=e.on_sale,
            tickets_sold=sold.get(e.id, 0),
            capacity=sum(t.quantity for t in e.ticket_types if t.active),
        )
        for e in events
    ]


@router.get('/events/{slug}', response_model=AdminEventOut)
def event_summary(slug: str, db: Session = Depends(get_db)):
    event = _event(db, slug)
    stats = _tier_stats(db, event)

    paid = select(Order).where(Order.event_id == event.id, Order.status == OrderStatus.paid).subquery()
    orders, fees = db.execute(select(func.count(), func.coalesce(func.sum(paid.c.fee_cents), 0)).select_from(paid)).one()
    refunded = db.scalar(
        select(func.count()).where(Order.event_id == event.id, Order.status == OrderStatus.refunded)
    )

    sold = _ticket_price.where(Ticket.event_id == event.id).subquery()
    day = func.to_char(func.timezone('America/Toronto', sold.c.paid_at), 'YYYY-MM-DD')
    by_day = db.execute(
        select(day, func.count(), func.coalesce(func.sum(sold.c.unit_price_cents), 0))
        .where(sold.c.paid_at.is_not(None))  # a hand-fixed order without a paid time can't crash the chart
        .group_by(day)
        .order_by(day)
    ).all()

    tiers = [
        AdminTierOut(
            id=t.id,
            name=t.name,
            description=t.description,
            price_cents=t.price_cents,
            quantity=t.quantity,
            max_per_order=t.max_per_order,
            sales_start=t.sales_start,
            sales_end=t.sales_end,
            active=t.active,
            gendered=t.gendered,
            price_ladies_cents=t.price_ladies_cents,
            price_men_cents=t.price_men_cents,
            **stats[t.id],
        )
        for t in event.ticket_types
    ]
    return AdminEventOut(
        slug=event.slug,
        name=event.name,
        description=event.description,
        venue=event.venue,
        poster_url=event.poster_url,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        on_sale=event.on_sale,
        sales_start=event.sales_start,
        secret_address=event.secret_address,
        address=event.address,
        address_emailed_at=event.address_emailed_at,
        tickets_sold=sum(t.sold for t in tiers),
        capacity=sum(t.quantity for t in tiers if t.active),
        checked_in=sum(t.checked_in for t in tiers),
        orders=orders,
        revenue_cents=sum(t.revenue_cents for t in tiers),
        fees_cents=int(fees),
        refunded_orders=refunded,
        tiers=tiers,
        sales_by_day=[SalesDay(day=d, tickets=n, revenue_cents=int(r)) for d, n, r in by_day],
    )


# ---------- attendees ----------


def _masked(a: AttendeeOut) -> AttendeeOut:
    # Partners see who's coming, but not people's full email addresses
    return a.model_copy(
        update={
            'buyer_email': mask_email(a.buyer_email),
            'holder_email': mask_email(a.holder_email) if a.holder_email else None,
        }
    )


def _attendees(db: Session, event: Event) -> list[AttendeeOut]:
    tickets = db.scalars(
        select(Ticket).join(Order).where(Ticket.event_id == event.id).order_by(func.lower(Ticket.holder_name))
    ).all()
    return [
        AttendeeOut(
            code=t.code,
            holder_name=t.holder_name,
            holder_email=t.holder_email,
            tier=t.ticket_type.name,
            gender=t.gender.value if t.gender else None,
            status=t.status.value,
            checked_in_at=t.checked_in_at,
            checked_in_by=t.checked_in_by.name if t.checked_in_by else None,
            order_id=str(t.order_id),
            buyer_name=t.order.buyer_name,
            combo=t.order.combo.name if t.order.combo else None,
            buyer_email=t.order.buyer_email,
            paid_at=t.order.paid_at,
        )
        for t in tickets
    ]


@router.get('/events/{slug}/attendees', response_model=list[AttendeeOut])
def attendees(slug: str, db: Session = Depends(get_db), staff: Staff = Depends(current_staff)):
    rows = _attendees(db, _event(db, slug))
    return [_masked(a) for a in rows] if staff.role == StaffRole.partner else rows


@router.get('/events/{slug}/attendees.csv')
def attendees_csv(slug: str, db: Session = Depends(get_db), staff: Staff = Depends(current_staff)):
    event = _event(db, slug)
    partner = staff.role == StaffRole.partner
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Name', 'Tier', 'Gender', 'Status', 'Checked in', 'Checked in by', 'Ticket email', 'Buyer', 'Buyer email', 'Paid', 'Ticket code'])
    for a in _attendees(db, event):
        if partner:
            a = _masked(a)
        w.writerow([
            a.holder_name, a.tier, GENDER_LABEL[Gender(a.gender)] if a.gender else '', a.status,
            a.checked_in_at.isoformat() if a.checked_in_at else '', a.checked_in_by or '',
            a.holder_email or '', a.buyer_name, a.buyer_email,
            a.paid_at.isoformat() if a.paid_at else '', a.code,
        ])
    return Response(
        buf.getvalue(),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{event.slug}-attendees.csv"'},
    )


@router.post('/tickets/{code}/void', response_model=AttendeeOut)
def void_ticket(code: str, db: Session = Depends(get_db), restore: bool = Query(False)):
    """Void a ticket (e.g. after refunding just the ticket price), or ?restore=true to undo."""
    ticket = db.scalar(select(Ticket).where(Ticket.code == code).with_for_update())
    if not ticket:
        raise HTTPException(404, 'Ticket not found')
    if restore and ticket.order.status == OrderStatus.refunded:
        raise HTTPException(400, 'This order was fully refunded; its tickets stay void')
    ticket.status = TicketStatus.valid if restore else TicketStatus.void
    db.commit()
    return next(a for a in _attendees(db, ticket.event) if a.code == code)


# ---------- editing ----------


@router.post('/events', response_model=AdminEventOut)
def create_event(body: EventIn, db: Session = Depends(get_db)):
    from app.models import Combo

    if db.scalar(select(Event).where(Event.slug == body.slug)) or db.scalar(select(Combo).where(Combo.slug == body.slug)):
        raise HTTPException(409, 'That link name is taken')
    db.add(Event(**body.model_dump()))
    db.commit()
    return event_summary(body.slug, db)


@router.patch('/events/{slug}', response_model=AdminEventOut)
def update_event(slug: str, body: EventPatch, db: Session = Depends(get_db)):
    event = _event(db, slug)
    changes = body.model_dump(exclude_unset=True)
    new_slug = changes.get('slug')
    if new_slug and new_slug != slug and db.scalar(select(Event).where(Event.slug == new_slug)):
        raise HTTPException(409, 'That link name is taken')
    for field, value in changes.items():
        if field in ('slug', 'name', 'starts_at', 'on_sale', 'secret_address') and value is None:
            continue  # required fields can't be cleared
        setattr(event, field, value)
    db.commit()
    return event_summary(event.slug, db)


def _check_gender_prices(gendered: bool, ladies: int | None, men: int | None) -> None:
    if gendered and (ladies is None or men is None):
        raise HTTPException(400, 'Set both a Ladies price and a Men price')


@router.post('/events/{slug}/tiers', response_model=AdminEventOut)
def add_tier(slug: str, body: TierIn, db: Session = Depends(get_db)):
    event = _event(db, slug)
    _check_gender_prices(body.gendered, body.price_ladies_cents, body.price_men_cents)
    db.add(TicketType(event=event, sort_order=len(event.ticket_types), **body.model_dump()))
    db.commit()
    return event_summary(slug, db)


@router.patch('/tiers/{tier_id}', response_model=AdminEventOut)
def update_tier(tier_id: int, body: TierPatch, db: Session = Depends(get_db)):
    tier = db.scalar(select(TicketType).where(TicketType.id == tier_id).with_for_update())
    if not tier:
        raise HTTPException(404, 'Tier not found')
    changes = body.model_dump(exclude_unset=True)
    if changes.get('quantity') is not None:
        taken = taken_counts(db, [tier.id])[tier.id]
        if changes['quantity'] < taken:
            raise HTTPException(400, f"{taken} are already sold or held; quantity can't go below that")
    for field, value in changes.items():
        if field in ('name', 'price_cents', 'quantity', 'max_per_order', 'active', 'gendered') and value is None:
            continue
        setattr(tier, field, value)
    _check_gender_prices(tier.gendered, tier.price_ladies_cents, tier.price_men_cents)
    db.commit()
    return event_summary(tier.event.slug, db)


@router.get('/staff')
def list_staff(db: Session = Depends(get_db)):
    return [
        {'name': s.name, 'email': s.email, 'role': s.role.value, 'active': s.active}
        for s in db.scalars(select(Staff).order_by(Staff.name))
    ]



@router.post('/events/{slug}/email-address')
def email_address(slug: str, db: Session = Depends(get_db)):
    """Send the secret address to every ticket holder (buyers + friends sent a ticket)."""
    from app.emails import address_recipients, send_address_emails

    event = _event(db, slug)
    if not (event.secret_address and event.address):
        raise HTTPException(400, 'Turn on Secret address and fill in the address first')
    if not address_recipients(db, event):
        raise HTTPException(400, 'Nobody has a ticket yet')
    try:
        sent = send_address_emails(db, event)
    except Exception:
        raise HTTPException(502, "Couldn't send right now. Try again in a minute.")
    return {'sent': sent}


@router.get('/events/{slug}/email-address')
def email_address_preview(slug: str, db: Session = Depends(get_db)):
    """How many people the address email would go to (shown before confirming)."""
    from app.emails import address_recipients

    return {'recipients': len(address_recipients(db, _event(db, slug)))}
