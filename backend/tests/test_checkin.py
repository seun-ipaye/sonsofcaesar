import threading
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
def setup(db):
    tonight = Event(slug='tonight', name='VOL III', starts_at=datetime.now(UTC) + timedelta(hours=2))
    last = Event(slug='last', name='VOL II', starts_at=datetime.now(UTC) - timedelta(days=30))
    ga = TicketType(event=tonight, name='GA', price_cents=2000, quantity=50)
    old = TicketType(event=last, name='GA', price_cents=2000, quantity=50)
    tolu = Staff(email='tolu@x.com', name='Tolu', role=StaffRole.door, password_hash=hash_password('door-pass-123'))
    kemi = Staff(email='kemi@x.com', name='Kemi', role=StaffRole.door, password_hash=hash_password('door-pass-456'))
    boss = Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123'))
    db.add_all([tonight, last, ga, old, tolu, kemi, boss])
    db.commit()

    def ticket(event, tier, name, code, status=TicketStatus.valid):
        o = Order(
            event_id=event.id, buyer_name='Ada Buyer', buyer_email='ada@example.com', status=OrderStatus.paid,
            subtotal_cents=2000, fee_cents=0, total_cents=2000, expires_at=datetime.now(UTC),
            items=[OrderItem(ticket_type_id=tier.id, quantity=1, unit_price_cents=2000)],
        )
        db.add(o)
        db.flush()
        db.add(Ticket(order=o, event_id=event.id, ticket_type_id=tier.id, holder_name=name, code=code, status=status))

    ticket(tonight, ga, 'Grace Hopper', 'GOODCODE0000000000AAAA')
    ticket(tonight, ga, 'Linus T', 'LINUSCODE00000000BBBB')
    ticket(tonight, ga, 'Refunded Rita', 'VOIDCODE000000000CCCC', TicketStatus.void)
    ticket(last, old, 'Old Olu', 'OLDCODE0000000000DDDD')
    db.commit()


def scan(c, code, event='tonight'):
    return c.post('/checkin', json={'event_slug': event, 'code': code}).json()


def test_requires_login(setup):
    assert TestClient(app).post('/checkin', json={'event_slug': 'tonight', 'code': 'x'}).status_code == 401


def test_scan_outcomes(setup):
    tolu = logged_in('tolu@x.com', 'door-pass-123')
    kemi = logged_in('kemi@x.com', 'door-pass-456')

    r = scan(tolu, 'GOODCODE0000000000AAAA')
    assert r['result'] == 'ok' and r['ticket']['holder_name'] == 'Grace Hopper' and r['ticket']['tier'] == 'GA'

    again = scan(kemi, 'GOODCODE0000000000AAAA')
    assert again['result'] == 'already' and again['ticket']['checked_in_by'] == 'Tolu'

    assert scan(tolu, 'VOIDCODE000000000CCCC')['result'] == 'void'
    wrong = scan(tolu, 'OLDCODE0000000000DDDD')
    assert wrong['result'] == 'wrong_event' and wrong['other_event'] == 'VOL II'
    assert scan(tolu, 'NOTOURS')['result'] == 'not_found'
    # A pasted ticket link works too
    assert scan(tolu, 'https://sonsofcaesar.xyz/t/LINUSCODE00000000BBBB')['result'] == 'ok'

    assert tolu.get('/checkin/stats?event=tonight').json() == {'checked_in': 2, 'total': 2}


def test_same_ticket_ten_phones_at_once(setup):
    phones = [logged_in('tolu@x.com', 'door-pass-123') for _ in range(10)]
    results = []
    threads = [threading.Thread(target=lambda c=c: results.append(scan(c, 'GOODCODE0000000000AAAA')['result'])) for c in phones]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ['already'] * 9 + ['ok']


def test_undo_rules(setup, db):
    tolu = logged_in('tolu@x.com', 'door-pass-123')
    kemi = logged_in('kemi@x.com', 'door-pass-456')
    boss = logged_in('boss@x.com', 'admin-pass-123')
    body = {'event_slug': 'tonight', 'code': 'GOODCODE0000000000AAAA'}

    scan(tolu, body['code'])
    assert kemi.post('/checkin/undo', json=body).status_code == 403  # not hers
    assert tolu.post('/checkin/undo', json=body).status_code == 200  # own, within 5 min
    assert scan(kemi, body['code'])['result'] == 'ok'  # can be scanned again

    # Kemi's check-in, 10 minutes later: too late for her, fine for an admin
    t = db.query(Ticket).filter_by(code=body['code']).one()
    t.checked_in_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    assert kemi.post('/checkin/undo', json=body).status_code == 403
    assert boss.post('/checkin/undo', json=body).status_code == 200


def test_manual_lookup(setup):
    tolu = logged_in('tolu@x.com', 'door-pass-123')
    names = lambda q: [t['holder_name'] for t in tolu.get(f'/checkin/search?event=tonight&q={q}').json()]  # noqa: E731
    assert names('grace') == ['Grace Hopper']
    assert names('BBBB') == ['Linus T']  # last characters of the code
    assert sorted(names('ada@')) == ['Grace Hopper', 'Linus T', 'Refunded Rita']  # buyer's email
    assert names('olu') == []  # other events never show up
    hit = tolu.get('/checkin/search?event=tonight&q=grace').json()[0]
    assert hit['buyer_email_hint'] == 'ad•••@example.com'
