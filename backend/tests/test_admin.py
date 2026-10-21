from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Event, Order, OrderItem, OrderStatus, Staff, StaffRole, Ticket, TicketStatus, TicketType
from app.security import hash_password


def logged_in(email, password):
    c = TestClient(app)
    assert c.post('/auth/login', json={'email': email, 'password': password}).status_code == 200
    return c


@pytest.fixture
def data(db):
    e = Event(slug='vol-iii', name='VOL III', starts_at=datetime.now(UTC) + timedelta(days=10), on_sale=True)
    ga = TicketType(event=e, name='GA', price_cents=2000, quantity=100)
    vip = TicketType(event=e, name='VIP', price_cents=4000, quantity=10, sort_order=1)
    db.add_all([
        e, ga, vip,
        Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123')),
        Staff(email='door@x.com', name='Door', role=StaffRole.door, password_hash=hash_password('door-pass-123')),
    ])
    db.commit()

    def order(items, status=OrderStatus.paid, fee=150, expires=timedelta(minutes=30)):
        o = Order(
            event_id=e.id, buyer_name='Ada', buyer_email='ada@example.com', status=status,
            subtotal_cents=sum(t.price_cents * q for t, q in items), fee_cents=fee,
            total_cents=sum(t.price_cents * q for t, q in items) + fee,
            expires_at=datetime.now(UTC) + expires, paid_at=datetime.now(UTC) if status != OrderStatus.pending else None,
            items=[OrderItem(ticket_type_id=t.id, quantity=q, unit_price_cents=t.price_cents) for t, q in items],
        )
        db.add(o)
        db.flush()
        if status in (OrderStatus.paid, OrderStatus.refunded):
            for t, q in items:
                for i in range(q):
                    db.add(Ticket(
                        order=o, event_id=e.id, ticket_type_id=t.id, holder_name=f'{t.name} person {i}',
                        status=TicketStatus.valid if status == OrderStatus.paid else TicketStatus.void,
                    ))
        return o

    order([(ga, 2), (vip, 1)])  # paid: 2 GA + 1 VIP
    order([(ga, 1)])  # paid
    order([(ga, 3)], status=OrderStatus.refunded)  # refunded: doesn't count
    order([(vip, 2)], status=OrderStatus.pending)  # someone checking out now
    db.commit()
    db.scalars(Ticket.__table__.select()).all()
    first_ga = db.query(Ticket).filter_by(status=TicketStatus.valid).first()
    first_ga.checked_in_at = datetime.now(UTC)
    db.commit()
    return e, ga, vip


def test_admin_only(data):
    assert TestClient(app).get('/admin/events').status_code == 401
    assert logged_in('door@x.com', 'door-pass-123').get('/admin/events').status_code == 403


def test_summary_numbers(data):
    boss = logged_in('boss@x.com', 'admin-pass-123')
    s = boss.get('/admin/events/vol-iii').json()
    assert s['tickets_sold'] == 4 and s['capacity'] == 110 and s['orders'] == 2
    assert s['revenue_cents'] == 3 * 2000 + 4000  # refunded order not counted
    assert s['fees_cents'] == 300 and s['refunded_orders'] == 1 and s['checked_in'] == 1
    tiers = {t['name']: t for t in s['tiers']}
    assert (tiers['GA']['sold'], tiers['GA']['held']) == (3, 0)
    assert (tiers['VIP']['sold'], tiers['VIP']['held']) == (1, 2)  # 2 in an active checkout
    assert sum(d['tickets'] for d in s['sales_by_day']) == 4

    listing = boss.get('/admin/events').json()
    assert listing[0]['slug'] == 'vol-iii' and listing[0]['tickets_sold'] == 4


def test_attendees_csv_and_void(data):
    boss = logged_in('boss@x.com', 'admin-pass-123')
    people = boss.get('/admin/events/vol-iii/attendees').json()
    assert len(people) == 7  # 4 valid + 3 void from the refund
    assert people[0]['buyer_email'] == 'ada@example.com'  # admins see full emails

    csv = boss.get('/admin/events/vol-iii/attendees.csv')
    assert csv.headers['content-type'].startswith('text/csv')
    assert csv.text.splitlines()[0].startswith('Name,Tier,Gender,Status') and len(csv.text.splitlines()) == 8

    code = next(p['code'] for p in people if p['status'] == 'valid')
    assert boss.post(f'/admin/tickets/{code}/void').json()['status'] == 'void'
    assert boss.get('/admin/events/vol-iii').json()['tickets_sold'] == 3
    assert boss.post(f'/admin/tickets/{code}/void?restore=true').json()['status'] == 'valid'
    # Tickets from a fully refunded order can't be restored
    refunded = next(p['code'] for p in people if p['status'] == 'void')
    assert boss.post(f'/admin/tickets/{refunded}/void?restore=true').status_code == 400


def test_edit_event_and_tiers(data):
    e, ga, vip = data
    boss = logged_in('boss@x.com', 'admin-pass-123')
    s = boss.patch('/admin/events/vol-iii', json={'venue': 'The Spot', 'on_sale': False}).json()
    assert s['venue'] == 'The Spot' and s['on_sale'] is False

    # Can't shrink VIP below 1 sold + 2 held
    assert boss.patch(f'/admin/tiers/{vip.id}', json={'quantity': 2}).status_code == 400
    s = boss.patch(f'/admin/tiers/{vip.id}', json={'quantity': 3, 'price_cents': 4500, 'sales_end': None}).json()
    v = next(t for t in s['tiers'] if t['name'] == 'VIP')
    assert (v['quantity'], v['price_cents']) == (3, 4500)

    s = boss.post('/admin/events/vol-iii/tiers', json={'name': 'Late', 'price_cents': 2500, 'quantity': 50}).json()
    assert [t['name'] for t in s['tiers']] == ['GA', 'VIP', 'Late']

    new = boss.post('/admin/events', json={
        'slug': 'vol-iv', 'name': 'VOL IV', 'starts_at': (datetime.now(UTC) + timedelta(days=60)).isoformat(),
    })
    assert new.status_code == 200 and new.json()['on_sale'] is False
    assert boss.post('/admin/events', json={'slug': 'vol-iv', 'name': 'X', 'starts_at': '2027-01-01T00:00:00Z'}).status_code == 409
    assert boss.post('/admin/events', json={'slug': 'Bad Slug!', 'name': 'X', 'starts_at': '2027-01-01T00:00:00Z'}).status_code == 422
