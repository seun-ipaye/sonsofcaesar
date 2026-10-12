import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Event, Order, OrderStatus, TicketType
from app.pricing import service_fee_cents
from app.routes import checkout


@pytest.fixture(autouse=True)
def fake_stripe(monkeypatch):
    """Stand-in for Stripe: records what we'd send, returns a fake payment link."""
    calls = []

    def create(order, event, tiers):
        calls.append(order)
        time.sleep(0.05)  # pretend the network takes a moment (widens race windows)
        return SimpleNamespace(id=f'cs_test_{len(calls)}', url=f'https://checkout.stripe.test/{len(calls)}')

    monkeypatch.setattr(checkout, 'create_stripe_session', create)
    return calls


@pytest.fixture
def event(db):
    e = Event(slug='vol-iii', name='VOL III', starts_at=datetime.now(UTC) + timedelta(days=20), on_sale=True)
    db.add_all(
        [
            e,
            TicketType(event=e, name='GA', price_cents=2000, quantity=5, max_per_order=4),
            TicketType(event=e, name='VIP', price_cents=4000, quantity=1, max_per_order=2, sort_order=1),
            TicketType(
                event=e, name='Early', price_cents=1500, quantity=10, sort_order=2,
                sales_end=datetime.now(UTC) - timedelta(days=1),
            ),
        ]
    )
    db.commit()
    return e


def tier_id(db, name):
    return db.scalar(select(TicketType.id).where(TicketType.name == name))


def buy(items, email='ada@example.com'):
    return TestClient(app).post(
        '/checkout',
        json={'event_slug': 'vol-iii', 'items': items, 'name': 'Ada Lovelace', 'email': email},
    )


def test_happy_path_holds_stock(db, event, fake_stripe):
    ga = tier_id(db, 'GA')
    r = buy([{'tier_id': ga, 'quantity': 2}])
    assert r.status_code == 200, r.text
    assert r.json()['checkout_url'].startswith('https://checkout.stripe.test/')

    order = db.scalar(select(Order))
    assert order.status == OrderStatus.pending
    assert order.subtotal_cents == 4000
    assert order.fee_cents == service_fee_cents(4000)
    assert order.total_cents == 4000 + order.fee_cents
    assert order.stripe_session_id == 'cs_test_1'
    assert order.buyer_email == 'ada@example.com'

    # The hold shows up as fewer tickets left
    tiers = {t['name']: t for t in TestClient(app).get('/events/current').json()['tiers']}
    assert tiers['GA']['remaining'] == 3


@pytest.mark.parametrize(
    'tier,qty,status,msg',
    [
        ('GA', 5, 400, 'Max 4 GA per order'),
        ('VIP', 2, 409, 'Only 1 VIP left'),
        ('Early', 1, 400, 'Early sales have ended'),
    ],
)
def test_rules(db, event, tier, qty, status, msg):
    r = buy([{'tier_id': tier_id(db, tier), 'quantity': qty}])
    assert r.status_code == status
    assert r.json()['detail'] == msg


def test_rejects_bad_input(db, event):
    ga = tier_id(db, 'GA')
    assert buy([{'tier_id': ga, 'quantity': 1}], email='not-an-email').status_code == 422
    assert buy([{'tier_id': ga, 'quantity': 0}]).status_code == 422
    assert buy([{'tier_id': ga, 'quantity': 1}, {'tier_id': ga, 'quantity': 1}]).status_code == 400
    assert buy([{'tier_id': 9999, 'quantity': 1}]).status_code == 400


def test_last_ticket_race_only_one_wins(db, event):
    """Ten buyers hit 'buy' for the single VIP ticket at the same moment."""
    vip = tier_id(db, 'VIP')
    results = []

    def attempt(i):
        results.append(buy([{'tier_id': vip, 'quantity': 1}], email=f'buyer{i}@example.com').status_code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200] + [409] * 9
    assert db.query(Order).count() == 1


def test_stripe_failure_holds_nothing(db, event, monkeypatch):
    def boom(*a):
        raise stripe.APIConnectionError('down')

    monkeypatch.setattr(checkout, 'create_stripe_session', boom)
    r = buy([{'tier_id': tier_id(db, 'GA'), 'quantity': 1}])
    assert r.status_code == 502
    assert db.query(Order).count() == 0


def test_cancel_releases_hold(db, event, monkeypatch):
    expired = []
    monkeypatch.setattr(stripe.checkout.Session, 'expire', lambda sid, **kw: expired.append(sid))
    vip = tier_id(db, 'VIP')
    order_id = buy([{'tier_id': vip, 'quantity': 1}]).json()['order_id']
    # The only VIP is held, so a second buyer is turned away...
    assert buy([{'tier_id': vip, 'quantity': 1}], email='b@example.com').status_code == 409

    r = TestClient(app).post(f'/checkout/{order_id}/cancel')
    assert r.json() == {'released': True}
    assert expired == ['cs_test_1']
    # ...until the first buyer backs out
    assert buy([{'tier_id': vip, 'quantity': 1}], email='b@example.com').status_code == 200
    # Cancelling twice (or a paid order) does nothing
    assert TestClient(app).post(f'/checkout/{order_id}/cancel').json() == {'released': False}


def test_cancel_does_nothing_if_stripe_refuses(db, event, monkeypatch):
    def refuse(sid, **kw):
        raise stripe.InvalidRequestError('already complete', None)

    monkeypatch.setattr(stripe.checkout.Session, 'expire', refuse)
    order_id = buy([{'tier_id': tier_id(db, 'GA'), 'quantity': 1}]).json()['order_id']
    assert TestClient(app).post(f'/checkout/{order_id}/cancel').json() == {'released': False}
    db.expire_all()
    assert db.get(Order, order_id).status == OrderStatus.pending
