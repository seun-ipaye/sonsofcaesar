from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Event, Order, Staff, StaffRole, Ticket, TicketType
from app.pricing import service_fee_cents
from app.routes import checkout as checkout_routes
from app.security import hash_password
from tests.test_webhooks import paid_session, send, webhook_secret  # noqa: F401

client = TestClient(app)


@pytest.fixture
def party(db, monkeypatch):
    monkeypatch.setattr(checkout_routes, 'create_stripe_session', lambda *a: SimpleNamespace(id='cs_g', url='https://x'))
    e = Event(slug='nightmare', name='Nightmare', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True)
    ga = TicketType(event=e, name='GA', price_cents=0, quantity=3, max_per_order=4,
                    gendered=True, price_ladies_cents=1000, price_men_cents=1500)
    vip = TicketType(event=e, name='VIP', price_cents=4000, quantity=10, sort_order=1)
    db.add_all([e, ga, vip,
                Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123')),
                Staff(email='door@x.com', name='Door', role=StaffRole.door, password_hash=hash_password('door-pass-123'))])
    db.commit()
    return e, ga, vip


def buy(items):
    return client.post('/checkout', json={'event_slug': 'nightmare', 'name': 'Ada', 'email': 'a@example.com', 'items': items})


def test_public_tier_shows_both_prices(party):
    tiers = {t['name']: t for t in client.get('/events/nightmare').json()['tiers']}
    assert (tiers['GA']['gendered'], tiers['GA']['price_ladies_cents'], tiers['GA']['price_men_cents']) == (True, 1000, 1500)
    assert tiers['VIP']['gendered'] is False
    assert client.get('/events').json()[0]['from_price_cents'] == 1000


def test_mixed_order_prices_and_tickets(party, db):
    _, ga, vip = party
    r = buy([
        {'tier_id': ga.id, 'gender': 'ladies', 'quantity': 1, 'names': ['Ada']},
        {'tier_id': ga.id, 'gender': 'men', 'quantity': 2, 'names': ['Bo', 'Cy']},
        {'tier_id': vip.id, 'quantity': 1},
    ])
    assert r.status_code == 200, r.text
    order = db.get(Order, r.json()['order_id'])
    assert order.subtotal_cents == 1000 + 2 * 1500 + 4000
    assert order.fee_cents == service_fee_cents(order.subtotal_cents)

    send('checkout.session.completed', paid_session(order))
    db.expire_all()
    got = sorted((t.holder_name, t.gender.value if t.gender else '') for t in db.scalars(select(Ticket)))
    assert got == [('Ada', ''), ('Ada', 'ladies'), ('Bo', 'men'), ('Cy', 'men')]

    # Revenue counts each ticket once at its own price (no double-matching across the two GA lines)
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})
    summary = boss.get('/admin/events/nightmare').json()
    g = next(t for t in summary['tiers'] if t['name'] == 'GA')
    assert (g['sold'], g['sold_ladies'], g['sold_men'], g['revenue_cents']) == (3, 1, 2, 4000)
    assert summary['revenue_cents'] == 8000
    csv = boss.get('/admin/events/nightmare/attendees.csv').text
    assert 'Bo,GA,Men,valid' in csv and 'Ada,GA,Ladies,valid' in csv

    # The door sees the gender
    door = TestClient(app)
    door.post('/auth/login', json={'email': 'door@x.com', 'password': 'door-pass-123'})
    bo = next(t for t in db.scalars(select(Ticket)) if t.holder_name == 'Bo')
    scan = door.post('/checkin', json={'event_slug': 'nightmare', 'code': bo.code}).json()
    assert scan['result'] == 'ok' and scan['ticket']['gender'] == 'men'


def test_rules(party, db):
    _, ga, vip = party
    assert buy([{'tier_id': ga.id, 'quantity': 1}]).json()['detail'] == 'Choose Ladies or Men for GA'
    assert buy([{'tier_id': vip.id, 'gender': 'men', 'quantity': 1}]).json()['detail'] == 'VIP is not priced by gender'
    dup = buy([{'tier_id': ga.id, 'gender': 'men', 'quantity': 1}, {'tier_id': ga.id, 'gender': 'men', 'quantity': 1}])
    assert dup.status_code == 400
    # One shared pool of 3: 2 ladies + 2 men is too many, even though each side alone fits
    r = buy([{'tier_id': ga.id, 'gender': 'ladies', 'quantity': 2}, {'tier_id': ga.id, 'gender': 'men', 'quantity': 2}])
    assert r.status_code == 409 and r.json()['detail'] == 'Not enough GA tickets left'
    # Max per order (4) counts both genders together
    ga.quantity = 50
    db.commit()
    r = buy([{'tier_id': ga.id, 'gender': 'ladies', 'quantity': 3}, {'tier_id': ga.id, 'gender': 'men', 'quantity': 2}])
    assert r.json()['detail'] == 'Max 4 GA per order'


def test_admin_needs_both_prices(party):
    _, ga, _ = party
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})
    r = boss.post('/admin/events/nightmare/tiers', json={'name': 'Late', 'price_cents': 0, 'quantity': 10,
                                                         'gendered': True, 'price_ladies_cents': 1200})
    assert r.status_code == 400 and 'both' in r.json()['detail']
    ok = boss.patch(f'/admin/tiers/{ga.id}', json={'price_men_cents': 1800}).json()
    assert next(t for t in ok['tiers'] if t['name'] == 'GA')['price_men_cents'] == 1800


def test_ticket_email_shows_gender(party, db, sent_emails):
    _, ga, _ = party
    r = buy([{'tier_id': ga.id, 'gender': 'ladies', 'quantity': 1}])
    order = db.get(Order, r.json()['order_id'])
    send('checkout.session.completed', paid_session(order))
    assert 'GA · Ladies' in sent_emails[0]['html']
