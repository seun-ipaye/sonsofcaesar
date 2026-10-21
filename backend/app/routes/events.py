from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.inventory import remaining, taken_counts
from app.models import Event, TicketType, public_venue
from app.pricing import service_fee_cents
from app.schemas import EventCard, EventOut, TierOut, TierStatus

router = APIRouter(prefix='/events', tags=['events'])


def tier_status(tier: TicketType, left: int, now: datetime) -> TierStatus:
    # The whole event's sale hasn't opened yet: every tier waits
    if tier.event.sales_start and now < tier.event.sales_start:
        return 'not_yet'
    if tier.sales_start and now < tier.sales_start:
        return 'not_yet'
    if tier.sales_end and now >= tier.sales_end:
        return 'ended'
    if left <= 0:
        return 'sold_out'
    return 'on_sale'


def lowest_prices(t: TicketType) -> list[int]:
    if t.gendered:
        return [p for p in (t.price_ladies_cents, t.price_men_cents) if p is not None] or [t.price_cents]
    return [t.price_cents]


def event_combos(db: Session, event: Event):
    from app.routes.combos import combo_out, listed_combos  # avoid an import cycle

    return [combo_out(db, c) for c in listed_combos(db, event.id)]


def event_out(db: Session, event: Event) -> EventOut:
    now = datetime.now(UTC)
    tiers = [t for t in event.ticket_types if t.active]
    taken = taken_counts(db, [t.id for t in tiers])
    return EventOut(
        slug=event.slug,
        name=event.name,
        description=event.description,
        venue=public_venue(event),
        poster_url=event.poster_url,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        sales_start=event.sales_start,
        combos=event_combos(db, event),
        tiers=[
            TierOut(
                id=t.id,
                name=t.name,
                description=t.description,
                price_cents=t.price_cents,
                fee_for_one_cents=service_fee_cents(min(lowest_prices(t))),
                max_per_order=t.max_per_order,
                buyable=min(remaining(t, taken[t.id]), t.max_per_order),
                status=tier_status(t, remaining(t, taken[t.id]), now),
                sales_start=t.sales_start,
                sales_end=t.sales_end,
                gendered=t.gendered,
                price_ladies_cents=t.price_ladies_cents if t.gendered else None,
                price_men_cents=t.price_men_cents if t.gendered else None,
            )
            for t in tiers
        ],
    )


def upcoming_on_sale(db: Session):
    now = datetime.now(UTC)
    # Still upcoming or happening now (ends_at if set, otherwise starts_at)
    return (
        select(Event)
        .where(Event.on_sale, func.coalesce(Event.ends_at, Event.starts_at) > now)
        .order_by(Event.starts_at)
    )


@router.get('', response_model=list[EventCard])
def list_events(db: Session = Depends(get_db)):
    """Every listed, upcoming event, soonest first: the /tickets choice screen."""
    cards = []
    for event in db.scalars(upcoming_on_sale(db)):
        out = event_out(db, event)
        statuses = {t.status for t in out.tiers}
        # The event's headline status: buyable if any tier is, else the most hopeful one
        status: TierStatus = next(
            (s for s in ('on_sale', 'not_yet', 'sold_out', 'ended') if s in statuses), 'ended'
        )
        prices = [
            p
            for t in out.tiers
            if t.status in ('on_sale', 'not_yet')
            for p in ([t.price_ladies_cents, t.price_men_cents] if t.gendered else [t.price_cents])
            if p is not None
        ]
        cards.append(
            EventCard(
                slug=event.slug,
                name=event.name,
                venue=public_venue(event),
                poster_url=event.poster_url,
                starts_at=event.starts_at,
                sales_start=event.sales_start,
                status=status,
                from_price_cents=min(prices) if prices else None,
            )
        )
    return cards


@router.get('/current', response_model=EventOut)
def current_event(db: Session = Depends(get_db)):
    """The next event that's on sale: what the /tickets page shows."""
    event = db.scalars(upcoming_on_sale(db).limit(1)).first()
    if not event:
        raise HTTPException(404, 'No event on sale right now')
    return event_out(db, event)


@router.get('/{slug}', response_model=EventOut)
def get_event(slug: str, db: Session = Depends(get_db)):
    """A specific on-sale event, for direct links."""
    event = db.scalars(upcoming_on_sale(db).where(Event.slug == slug)).first()
    if not event:
        raise HTTPException(404, 'Event not found')
    return event_out(db, event)
