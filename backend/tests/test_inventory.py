from datetime import UTC, datetime, timedelta

from app.inventory import remaining, taken_counts
from app.models import Event, Order, OrderItem, OrderStatus, TicketType
from app.security import hash_password, verify_password


def order(event, tier, qty, status, expires_in_minutes=30):
    return Order(
        event_id=event.id,
        buyer_name='x',
        buyer_email='x@example.com',
        status=status,
        subtotal_cents=0,
        fee_cents=0,
        total_cents=0,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        items=[OrderItem(ticket_type_id=tier.id, quantity=qty, unit_price_cents=tier.price_cents)],
    )


def test_taken_counts_paid_and_active_holds_only(db):
    event = Event(slug='e', name='E', starts_at=datetime.now(UTC))
    ga = TicketType(event=event, name='GA', price_cents=2000, quantity=10)
    vip = TicketType(event=event, name='VIP', price_cents=4000, quantity=5)
    db.add_all([event, ga, vip])
    db.commit()

    db.add_all(
        [
            order(event, ga, 3, OrderStatus.paid),  # counts
            order(event, ga, 2, OrderStatus.pending),  # counts: hold still active
            order(event, ga, 4, OrderStatus.pending, expires_in_minutes=-1),  # hold expired: free again
            order(event, ga, 1, OrderStatus.expired),  # never paid
            order(event, ga, 1, OrderStatus.refunded),  # refunded: back on sale
        ]
    )
    db.commit()

    counts = taken_counts(db, [ga.id, vip.id])
    assert counts == {ga.id: 5, vip.id: 0}
    assert remaining(ga, counts[ga.id]) == 5
    assert remaining(vip, counts[vip.id]) == 5


def test_password_hashing():
    h = hash_password('correct horse battery')
    assert h != 'correct horse battery'
    assert verify_password(h, 'correct horse battery')
    assert not verify_password(h, 'wrong')
