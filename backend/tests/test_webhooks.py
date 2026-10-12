import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import Event, Order, OrderItem, OrderStatus, Ticket, TicketStatus, TicketType

SECRET = 'whsec_test_secret'
client = TestClient(app)


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, 'stripe_webhook_secret', SECRET)


def send(event_type, obj, secret=SECRET):
    """Send a webhook signed the way Stripe signs them."""
    payload = json.dumps({'id': 'evt_1', 'object': 'event', 'type': event_type, 'data': {'object': obj}})
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f'{ts}.{payload}'.encode(), hashlib.sha256).hexdigest()
    return client.post(
        '/webhooks/stripe',
        content=payload,
        headers={'stripe-signature': f't={ts},v1={sig}', 'content-type': 'application/json'},
    )


@pytest.fixture
def order(db):
    e = Event(slug='e', name='E', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True)
    ga = TicketType(event=e, name='GA', price_cents=2000, quantity=10)
    vip = TicketType(event=e, name='VIP', price_cents=4000, quantity=10)
    db.add_all([e, ga, vip])
    db.commit()
    o = Order(
        event_id=e.id, buyer_name='Ada', buyer_email='ada@example.com',
        subtotal_cents=8000, fee_cents=360, total_cents=8360,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        stripe_session_id='cs_1',
        items=[
            OrderItem(ticket_type_id=ga.id, quantity=2, unit_price_cents=2000),
            OrderItem(ticket_type_id=vip.id, quantity=1, unit_price_cents=4000),
        ],
    )
    db.add(o)
    db.commit()
    return o


def paid_session(order, **overrides):
    return {
        'id': 'cs_1', 'client_reference_id': str(order.id), 'metadata': {'order_id': str(order.id)},
        'payment_status': 'paid', 'payment_intent': 'pi_1', 'amount_total': order.total_cents, **overrides,
    }


def reload(db, order):
    db.expire_all()
    return db.get(Order, order.id)


def test_payment_creates_tickets_once(db, order):
    for _ in range(3):  # Stripe delivering the same notice three times
        assert send('checkout.session.completed', paid_session(order)).status_code == 200
    o = reload(db, order)
    assert o.status == OrderStatus.paid
    assert o.stripe_payment_intent_id == 'pi_1'
    assert len(o.tickets) == 3
    assert {t.status for t in o.tickets} == {TicketStatus.valid}


def test_forged_webhook_rejected(db, order):
    r = send('checkout.session.completed', paid_session(order), secret='whsec_attacker')
    assert r.status_code == 400
    assert reload(db, order).status == OrderStatus.pending
    assert db.query(Ticket).count() == 0


def test_unpaid_completion_and_amount_mismatch_issue_nothing(db, order):
    send('checkout.session.completed', paid_session(order, payment_status='unpaid'))
    send('checkout.session.completed', paid_session(order, amount_total=1))
    assert reload(db, order).status == OrderStatus.pending
    assert db.query(Ticket).count() == 0


def test_expiry_then_late_payment_is_honoured(db, order):
    send('checkout.session.expired', {'id': 'cs_1', 'client_reference_id': str(order.id), 'metadata': {}})
    assert reload(db, order).status == OrderStatus.expired
    send('checkout.session.completed', paid_session(order))
    assert reload(db, order).status == OrderStatus.paid
    assert db.query(Ticket).count() == 3


def test_full_refund_voids_tickets_partial_does_not(db, order):
    send('checkout.session.completed', paid_session(order))
    send('charge.refunded', {'payment_intent': 'pi_1', 'amount': 8360, 'amount_refunded': 360})
    assert reload(db, order).status == OrderStatus.paid
    send('charge.refunded', {'payment_intent': 'pi_1', 'amount': 8360, 'amount_refunded': 8360})
    o = reload(db, order)
    assert o.status == OrderStatus.refunded
    assert {t.status for t in o.tickets} == {TicketStatus.void}
    # A late duplicate "paid" notice must not bring the tickets back
    send('checkout.session.completed', paid_session(order))
    assert reload(db, order).status == OrderStatus.refunded


def test_unknown_events_are_acknowledged():
    assert send('customer.created', {'id': 'cus_1'}).status_code == 200
