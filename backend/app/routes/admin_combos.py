"""Admin: create and edit combo passes, and see their sales (kept separate from
each event's own numbers)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.combos import combo_taken
from app.db import get_db
from app.models import Combo, ComboPart, Event, Order, OrderStatus, TicketType
from app.routes.combos import combo_out
from app.schemas import AdminComboOut, ComboIn, ComboPatch, TierChoice

router = APIRouter(prefix='/admin/combos', tags=['admin'], dependencies=[Depends(require_admin)])


def _combo(db: Session, slug: str) -> Combo:
    combo = db.scalar(select(Combo).where(Combo.slug == slug))
    if not combo:
        raise HTTPException(404, 'Combo not found')
    return combo


def admin_combo_out(db: Session, combo: Combo) -> AdminComboOut:
    paid = select(Order).where(Order.combo_id == combo.id, Order.status == OrderStatus.paid).subquery()
    sold, revenue, fees, orders = db.execute(
        select(
            func.coalesce(func.sum(paid.c.combo_quantity), 0),
            func.coalesce(func.sum(paid.c.subtotal_cents), 0),
            func.coalesce(func.sum(paid.c.fee_cents), 0),
            func.count(),
        ).select_from(paid)
    ).one()
    held = combo_taken(db, [combo.id])[combo.id] - int(sold)
    public = combo_out(db, combo)
    return AdminComboOut(
        id=combo.id,
        slug=combo.slug,
        name=combo.name,
        description=combo.description,
        poster_url=combo.poster_url,
        price_cents=combo.price_cents,
        quantity=combo.quantity,
        max_per_order=combo.max_per_order,
        sales_end=combo.sales_end,
        on_sale=combo.on_sale,
        tier_ids=[p.ticket_type_id for p in combo.parts],
        parts=public.parts,
        sold=int(sold),
        held=max(held, 0),
        revenue_cents=int(revenue),
        fees_cents=int(fees),
        orders=orders,
    )


def _set_parts(db: Session, combo: Combo, tier_ids: list[int]) -> None:
    if len(set(tier_ids)) != len(tier_ids):
        raise HTTPException(400, 'Pick one tier from each event (not two from the same event)')
    tiers = db.scalars(select(TicketType).where(TicketType.id.in_(tier_ids))).all()
    if len(tiers) != len(tier_ids):
        raise HTTPException(400, 'One of those tiers no longer exists')
    events = [t.event_id for t in tiers]
    if len(set(events)) != len(events):
        raise HTTPException(400, 'Pick one tier from each event (not two from the same event)')
    # Changing what a combo includes after passes are sold would leave buyers with the
    # wrong tickets, so it's locked once anything has sold
    if combo.id and sorted(p.ticket_type_id for p in combo.parts) != sorted(tier_ids):
        if combo_taken(db, [combo.id])[combo.id] > 0:
            raise HTTPException(400, "Passes are already sold, so the events it includes can't change")
    combo.parts = [ComboPart(ticket_type_id=t.id) for t in tiers]


@router.get('', response_model=list[AdminComboOut])
def list_combos(db: Session = Depends(get_db)):
    return [admin_combo_out(db, c) for c in db.scalars(select(Combo).order_by(Combo.created_at.desc()))]


@router.get('/tiers', response_model=list[TierChoice])
def tier_choices(db: Session = Depends(get_db)):
    """Every tier of every upcoming-ish event, for picking what a combo includes."""
    rows = db.scalars(select(TicketType).join(Event).order_by(Event.starts_at, TicketType.sort_order))
    return [TierChoice(id=t.id, label=f'{t.event.name} · {t.name}', event_slug=t.event.slug) for t in rows]


@router.post('', response_model=AdminComboOut)
def create_combo(body: ComboIn, db: Session = Depends(get_db)):
    if db.scalar(select(Combo).where(Combo.slug == body.slug)) or db.scalar(select(Event).where(Event.slug == body.slug)):
        raise HTTPException(409, 'That link name is taken')
    combo = Combo(**body.model_dump(exclude={'tier_ids'}))
    _set_parts(db, combo, body.tier_ids)
    db.add(combo)
    db.commit()
    return admin_combo_out(db, combo)


@router.patch('/{slug}', response_model=AdminComboOut)
def update_combo(slug: str, body: ComboPatch, db: Session = Depends(get_db)):
    combo = _combo(db, slug)
    changes = body.model_dump(exclude_unset=True)
    new_slug = changes.get('slug')
    if new_slug and new_slug != slug:
        if db.scalar(select(Combo).where(Combo.slug == new_slug)) or db.scalar(select(Event).where(Event.slug == new_slug)):
            raise HTTPException(409, 'That link name is taken')
    if changes.get('quantity') is not None:
        taken = combo_taken(db, [combo.id])[combo.id]
        if changes['quantity'] < taken:
            raise HTTPException(400, f"{taken} are already sold or held; the cap can't go below that")
    if changes.get('tier_ids') is not None:
        _set_parts(db, combo, changes.pop('tier_ids'))
    changes.pop('tier_ids', None)
    for field, value in changes.items():
        if field in ('slug', 'name', 'price_cents', 'quantity', 'max_per_order', 'on_sale') and value is None:
            continue
        setattr(combo, field, value)
    db.commit()
    return admin_combo_out(db, combo)
