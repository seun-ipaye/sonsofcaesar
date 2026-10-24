from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    Event, Order, OrderItem, OrderStatus, Staff, StaffEvent, StaffRole, Ticket, TicketType,
)
from app.security import hash_password


def logged_in(email, password):
    c = TestClient(app)
    assert c.post('/auth/login', json={'email': email, 'password': password}).status_code == 200
    return c


@pytest.fixture
def world(db):
    mine = Event(slug='nightmare', name='Nightmare', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True)
    other = Event(slug='asylum', name='Asylum', starts_at=datetime.now(UTC) + timedelta(days=4), on_sale=True)
    ga = TicketType(event=mine, name='GA', price_cents=2000, quantity=50)
    reg = TicketType(event=other, name='Regular', price_cents=2000, quantity=50)
    partner = Staff(email='collab@x.com', name='Collab', role=StaffRole.partner, password_hash=hash_password('partner-pass-1'))
    db.add_all([mine, other, ga, reg, partner,
                Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123'))])
    db.commit()
    db.add(StaffEvent(staff_id=partner.id, event_id=mine.id))
    o = Order(event_id=mine.id, buyer_name='Ada', buyer_email='ada.lovelace@example.com', status=OrderStatus.paid,
              subtotal_cents=2000, fee_cents=0, total_cents=2000, expires_at=datetime.now(UTC), paid_at=datetime.now(UTC),
              items=[OrderItem(ticket_type_id=ga.id, quantity=1, unit_price_cents=2000)])
    db.add(o)
    db.flush()
    db.add(Ticket(order=o, event_id=mine.id, ticket_type_id=ga.id, holder_name='Grace', holder_email='grace.hopper@example.com'))
    db.commit()
    return mine, other, ga, logged_in('collab@x.com', 'partner-pass-1')


def test_sees_only_their_event(world):
    _, _, _, p = world
    assert [e['slug'] for e in p.get('/admin/events').json()] == ['nightmare']
    s = p.get('/admin/events/nightmare').json()
    assert s['tickets_sold'] == 1 and s['revenue_cents'] == 2000  # revenue is visible
    assert p.get('/admin/events/asylum').status_code == 403
    assert p.get('/admin/events/asylum/attendees').status_code == 403
    assert p.get('/admin/events/asylum/attendees.csv').status_code == 403


def test_emails_masked_everywhere(world):
    _, _, _, p = world
    a = p.get('/admin/events/nightmare/attendees').json()[0]
    assert a['buyer_email'] == 'ad•••@example.com' and a['holder_email'] == 'gr•••@example.com'
    csv = p.get('/admin/events/nightmare/attendees.csv').text
    assert 'ada.lovelace@' not in csv and 'grace.hopper@' not in csv and 'ad•••@example.com' in csv
    # Admins still get full emails
    boss = logged_in('boss@x.com', 'admin-pass-123')
    assert boss.get('/admin/events/nightmare/attendees').json()[0]['buyer_email'] == 'ada.lovelace@example.com'


def test_cannot_change_anything(world):
    _, _, ga, p = world
    code = p.get('/admin/events/nightmare/attendees').json()[0]['code']
    attempts = [
        p.patch('/admin/events/nightmare', json={'name': 'Hacked'}),
        p.post('/admin/events/nightmare/tiers', json={'name': 'Free', 'price_cents': 0, 'quantity': 999}),
        p.patch(f'/admin/tiers/{ga.id}', json={'price_cents': 1}),
        p.post('/admin/events', json={'slug': 'x', 'name': 'X', 'starts_at': '2027-01-01T00:00:00Z'}),
        p.post(f'/admin/tickets/{code}/void'),
        p.post('/admin/events/nightmare/email-address'),
        p.get('/admin/events/nightmare/email-address'),
        p.get('/admin/combos'),
        p.post('/admin/combos', json={}),
        p.get('/admin/staff'),
    ]
    assert [r.status_code for r in attempts] == [403] * len(attempts)
    assert TestClient(app).get('/events/nightmare').json()['name'] == 'Nightmare'


def test_no_scanner(world):
    _, _, _, p = world
    assert p.get('/checkin/events').status_code == 403
    assert p.post('/checkin', json={'event_slug': 'nightmare', 'code': 'x'}).status_code == 403
    assert p.get('/checkin/search?event=nightmare&q=grace').status_code == 403


def test_revoking_takes_effect_immediately(world, db):
    mine, _, _, p = world
    db.query(StaffEvent).delete()
    db.commit()
    assert p.get('/admin/events').json() == []
    assert p.get('/admin/events/nightmare').status_code == 403
