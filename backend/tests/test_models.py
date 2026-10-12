from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Event, Order, OrderItem, Ticket, TicketStatus, TicketType


def make_event(db):
    event = Event(slug='test-party', name='Test Party', starts_at=datetime.now(UTC) + timedelta(days=30))
    ga = TicketType(event=event, name='GA', price_cents=2000, quantity=100)
    db.add_all([event, ga])
    db.commit()
    return event, ga


def test_order_with_tickets(db):
    event, ga = make_event(db)
    order = Order(
        event_id=event.id,
        buyer_name='Ada',
        buyer_email='ada@example.com',
        subtotal_cents=4000,
        fee_cents=150,
        total_cents=4150,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        items=[OrderItem(ticket_type_id=ga.id, quantity=2, unit_price_cents=2000)],
    )
    db.add(order)
    db.flush()
    tickets = [Ticket(order=order, event_id=event.id, ticket_type_id=ga.id, holder_name='Ada') for _ in range(2)]
    db.add_all(tickets)
    db.commit()

    assert order.status.value == 'pending'
    assert len(order.tickets) == 2
    assert tickets[0].status == TicketStatus.valid
    # Codes are random and long enough to be unguessable
    assert tickets[0].code != tickets[1].code
    assert len(tickets[0].code) >= 20


def test_price_cannot_be_negative(db):
    event = Event(slug='x', name='X', starts_at=datetime.now(UTC))
    db.add_all([event, TicketType(event=event, name='Bad', price_cents=-1, quantity=1)])
    with pytest.raises(IntegrityError):
        db.commit()
