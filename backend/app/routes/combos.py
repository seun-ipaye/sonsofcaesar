"""Public combo pages: the /tickets combo card, "Going to both?" and the combo's own page."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.combos import combo_state
from app.db import get_db
from app.models import Combo, ComboPart, TicketType, public_venue
from app.pricing import service_fee_cents
from app.schemas import ComboOut, ComboPartOut

router = APIRouter(prefix='/combos', tags=['combos'])


def combo_out(db: Session, combo: Combo) -> ComboOut:
    status, buyable = combo_state(db, combo)
    return ComboOut(
        slug=combo.slug,
        name=combo.name,
        description=combo.description,
        poster_url=combo.poster_url,
        price_cents=combo.price_cents,
        fee_for_one_cents=service_fee_cents(combo.price_cents),
        max_per_order=combo.max_per_order,
        buyable=buyable,
        status=status,
        sales_end=combo.sales_end,
        parts=[
            ComboPartOut(
                event_slug=p.ticket_type.event.slug,
                event_name=p.ticket_type.event.name,
                starts_at=p.ticket_type.event.starts_at,
                venue=public_venue(p.ticket_type.event),
                poster_url=p.ticket_type.event.poster_url,
                tier=p.ticket_type.name,
            )
            for p in sorted(combo.parts, key=lambda p: p.ticket_type.event.starts_at)
        ],
    )


def visible(db: Session, combo: Combo) -> bool:
    """Listed, has parts, every event is listed, and it isn't over."""
    return (
        combo.on_sale
        and bool(combo.parts)
        and all(p.ticket_type.event.on_sale for p in combo.parts)
        and combo_state(db, combo)[0] != 'ended'
    )


def listed_combos(db: Session, event_id: int | None = None) -> list[Combo]:
    q = select(Combo).where(Combo.on_sale).order_by(Combo.created_at)
    if event_id is not None:
        q = q.where(
            Combo.id.in_(
                select(ComboPart.combo_id).join(TicketType).where(TicketType.event_id == event_id)
            )
        )
    return [c for c in db.scalars(q) if visible(db, c)]


@router.get('', response_model=list[ComboOut])
def list_combos(db: Session = Depends(get_db)):
    return [combo_out(db, c) for c in listed_combos(db)]


@router.get('/{slug}', response_model=ComboOut)
def get_combo(slug: str, db: Session = Depends(get_db)):
    combo = db.scalar(select(Combo).where(Combo.slug == slug))
    if not combo or not visible(db, combo):
        raise HTTPException(404, 'Combo not found')
    return combo_out(db, combo)
