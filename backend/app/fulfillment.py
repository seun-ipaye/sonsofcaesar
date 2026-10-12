"""What happens when Stripe tells us about a payment, expiry or refund.

Every function here is safe to run more than once for the same order: Stripe
sometimes delivers the same notification twice, and we must never create
duplicate tickets.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, Ticket, TicketStatus

log = logging.getLogger(__name__)


def _lock_order(db: Session, **where) -> Order | None:
    # Lock the order row so two copies of the same notification can't both act on it
    return db.scalar(select(Order).filter_by(**where).with_for_update())


def fulfill_order(db: Session, order_id: str, payment_intent_id: str | None, amount_paid: int | None) -> Order | None:
    """Payment succeeded: mark the order paid and create one ticket per admission."""
    order = _lock_order(db, id=order_id)
    if not order:
        log.error('Paid checkout for unknown order %s', order_id)
        return None
    if order.status == OrderStatus.paid:
        return order  # already done (duplicate notification)
    if order.status == OrderStatus.refunded:
        log.warning('Ignoring payment for refunded order %s', order_id)
        return order
    if amount_paid is not None and amount_paid != order.total_cents:
        # Should be impossible (we set the price), but never issue tickets on a mismatch
        log.error('Order %s: paid %s but expected %s', order_id, amount_paid, order.total_cents)
        return order

    # A payment can land after our hold lapsed (e.g. the notification was delayed).
    # They paid, so they get their tickets; at worst a tier goes over by a few.
    if order.status == OrderStatus.expired:
        log.warning('Order %s paid after its hold expired; honouring it', order_id)

    order.status = OrderStatus.paid
    order.paid_at = datetime.now(UTC)
    order.stripe_payment_intent_id = payment_intent_id
    for item in order.items:
        for _ in range(item.quantity):
            db.add(
                Ticket(
                    order=order,
                    event_id=order.event_id,
                    ticket_type_id=item.ticket_type_id,
                    holder_name=order.buyer_name,
                )
            )
    db.commit()
    log.info('Order %s paid: %s tickets issued', order_id, sum(i.quantity for i in order.items))
    return order


def expire_order(db: Session, order_id: str) -> None:
    """Checkout page timed out without payment: release the hold."""
    order = _lock_order(db, id=order_id)
    if order and order.status == OrderStatus.pending:
        order.status = OrderStatus.expired
    db.commit()


def refund_order(db: Session, payment_intent_id: str, fully_refunded: bool) -> None:
    """Refunded in the Stripe dashboard: void the tickets so they can't be scanned."""
    order = _lock_order(db, stripe_payment_intent_id=payment_intent_id)
    if not order:
        db.commit()
        return
    if not fully_refunded:
        # Partial refunds (e.g. refunding just the fee) leave tickets valid
        log.info('Order %s partially refunded; tickets left valid', order.id)
        db.commit()
        return
    order.status = OrderStatus.refunded
    for ticket in order.tickets:
        ticket.status = TicketStatus.void
    db.commit()
    log.info('Order %s refunded: %s tickets voided', order.id, len(order.tickets))
