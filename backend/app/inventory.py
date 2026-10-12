"""How many tickets of each tier are taken.

"Taken" = in paid orders, plus in pending orders whose 30-minute hold hasn't
expired yet (someone is on the Stripe page right now).
"""

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatus, TicketType


def taken_counts(db: Session, ticket_type_ids: list[int]) -> dict[int, int]:
    now = datetime.now(UTC)
    rows = db.execute(
        select(OrderItem.ticket_type_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order)
        .where(
            OrderItem.ticket_type_id.in_(ticket_type_ids),
            or_(
                Order.status == OrderStatus.paid,
                and_(Order.status == OrderStatus.pending, Order.expires_at > now),
            ),
        )
        .group_by(OrderItem.ticket_type_id)
    ).all()
    counts = dict.fromkeys(ticket_type_ids, 0)
    counts.update({tid: int(n) for tid, n in rows})
    return counts


def remaining(tier: TicketType, taken: int) -> int:
    return max(tier.quantity - taken, 0)
