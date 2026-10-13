from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Event, Order, Ticket, TicketType
from app.routes import checkout as checkout_routes
from tests.test_webhooks import paid_session, send, webhook_secret  # noqa: F401

client = TestClient(app)


@pytest.fixture
def paid_order(db, monkeypatch):
    """Ada buys 3 GA: one for herself, one for Grace (emailed), one for Linus (not emailed)."""
    monkeypatch.setattr(checkout_routes, 'create_stripe_session', lambda *a: SimpleNamespace(id='cs_1', url='https://x'))
    e = Event(slug='e', name='VOL III', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True)
    ga = TicketType(event=e, name='GA', price_cents=2000, quantity=10)
    db.add_all([e, ga])
    db.commit()
    r = client.post('/checkout', json={
        'event_slug': 'e', 'name': 'Ada Lovelace', 'email': 'ada@example.com',
        'items': [{
            'tier_id': ga.id, 'quantity': 3,
            'names': ['', 'Grace Hopper', 'Linus'],
            'emails': [None, 'Grace@Example.com', None],
        }],
    })
    order = db.get(Order, r.json()['order_id'])
    return order


def test_friend_gets_only_their_ticket(db, paid_order, sent_emails):
    send('checkout.session.completed', paid_session(paid_order))
    send('checkout.session.completed', paid_session(paid_order))  # duplicate notice

    assert [m['to'] for m in sent_emails] == [['ada@example.com'], ['grace@example.com']]
    buyer, friend = sent_emails
    grace = db.scalar(select(Ticket).where(Ticket.holder_name == 'Grace Hopper'))
    others = db.scalars(select(Ticket).where(Ticket.holder_name != 'Grace Hopper')).all()

    assert len(buyer['attachments']) == 3
    assert friend['subject'] == 'Ada got you a ticket: VOL III'
    assert len(friend['attachments']) == 1
    # The friend's email holds their ticket only, and links to it, not the whole order
    assert grace.code in friend['html'] and f'/t/{grace.code}' in friend['html']
    assert all(t.code not in friend['html'] for t in others)
    assert f'/order/{paid_order.id}' not in friend['html']


def test_resend_to_corrected_email_same_tickets(db, paid_order, sent_emails):
    send('checkout.session.completed', paid_session(paid_order))
    codes_before = sorted(db.scalars(select(Ticket.code)))

    page = client.get(f'/orders/{paid_order.id}').json()
    assert page['email_hint'] == 'ad•••@example.com' and page['resends_left'] == 5

    r = client.post(f'/orders/{paid_order.id}/resend', json={'email': 'Ada.Real@Example.com'})
    assert r.json() == {'sent_to': 'ad•••@example.com', 'resends_left': 4}
    assert sent_emails[-1]['to'] == ['ada.real@example.com']
    # Same QR codes: nothing new was issued
    db.expire_all()
    assert sorted(db.scalars(select(Ticket.code))) == codes_before
    assert all(code in sent_emails[-1]['html'] for code in codes_before)

    # Too soon
    assert client.post(f'/orders/{paid_order.id}/resend', json={'email': 'x@example.com'}).status_code == 429


def test_resend_limit(db, paid_order):
    send('checkout.session.completed', paid_session(paid_order))
    for i in range(5):
        db.expire_all()
        o = db.get(Order, paid_order.id)
        o.last_resent_at = None  # skip the cooldown
        db.commit()
        assert client.post(f'/orders/{paid_order.id}/resend', json={'email': f'a{i}@example.com'}).status_code == 200
    db.expire_all()
    db.get(Order, paid_order.id).last_resent_at = None
    db.commit()
    r = client.post(f'/orders/{paid_order.id}/resend', json={'email': 'spam@example.com'})
    assert r.status_code == 429 and 'limit' in r.json()['detail']


def test_cannot_resend_unpaid_order(db, paid_order):
    assert client.post(f'/orders/{paid_order.id}/resend', json={'email': 'a@example.com'}).status_code == 404
