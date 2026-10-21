"""Combo passes: availability rules shared by the public pages and checkout."""

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.inventory import remaining, taken_counts
from app.models import Combo, Order, OrderStatus, TicketType


def combo_taken(db: Session, combo_ids: list[int]) -> dict[int, int]:
    """Passes in paid orders plus active checkout holds, per combo."""
    now = datetime.now(UTC)
    rows = db.execute(
        select(Order.combo_id, func.coalesce(func.sum(Order.combo_quantity), 0))
        .where(
            Order.combo_id.in_(combo_ids),
            or_(
                Order.status == OrderStatus.paid,
                and_(Order.status == OrderStatus.pending, Order.expires_at > now),
            ),
        )
        .group_by(Order.combo_id)
    ).all()
    counts = dict.fromkeys(combo_ids, 0)
    counts.update({cid: int(n) for cid, n in rows})
    return counts


def part_tiers(combo: Combo) -> list[TicketType]:
    return [p.ticket_type for p in combo.parts]


def combo_state(db: Session, combo: Combo, now: datetime | None = None) -> tuple[str, int]:
    """(status, buyable) for a combo.

    status: on_sale / not_yet / sold_out / ended (same words as tiers).
    buyable: how many passes can be bought right now, capped at max_per_order so the
    real stock level stays private.
    """
    from app.routes.events import tier_status  # avoid an import cycle

    now = now or datetime.now(UTC)
    tiers = part_tiers(combo)
    if not tiers:
        return 'ended', 0
    if combo.sales_end and now >= combo.sales_end:
        return 'ended', 0
    if any(not t.active or event_over(t, now) for t in tiers):
        return 'ended', 0

    taken = taken_counts(db, [t.id for t in tiers])
    left_per_tier = {t.id: remaining(t, taken[t.id]) for t in tiers}
    statuses = [tier_status(t, left_per_tier[t.id], now) for t in tiers]
    if 'ended' in statuses:
        return 'ended', 0
    if 'not_yet' in statuses:
        return 'not_yet', 0

    combo_left = max(combo.quantity - combo_taken(db, [combo.id])[combo.id], 0)
    left = min([combo_left, *left_per_tier.values()])
    if left <= 0:
        return 'sold_out', 0
    return 'on_sale', min(left, combo.max_per_order)


def event_over(tier: TicketType, now: datetime) -> bool:
    e = tier.event
    return (e.ends_at or e.starts_at) <= now
