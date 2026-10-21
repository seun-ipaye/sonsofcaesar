import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Event, Order, OrderStatus, Staff, StaffRole, Ticket, TicketStatus, TicketType
from app.routes import checkout as checkout_routes
from app.security import hash_password
from tests.test_webhooks import paid_session, send, webhook_secret  # noqa: F401

client = TestClient(app)


@pytest.fixture
def setup(db, monkeypatch):
    calls = []

    def fake_session(order, combo):
        calls.append(order)
        return SimpleNamespace(id=f'cs_combo_{len(calls)}', url='https://checkout.stripe.test/combo')

    monkeypatch.setattr(checkout_routes, 'create_combo_session', fake_session)
    monkeypatch.setattr(checkout_routes, 'create_stripe_session', lambda *a: SimpleNamespace(id='cs_reg', url='https://x'))
    asylum = Event(slug='asylum', name='Asylum', starts_at=datetime.now(UTC) + timedelta(days=9), on_sale=True, venue='Blanche Lounge')
    nightmare = Event(slug='nightmare', name='Nightmare', starts_at=datetime.now(UTC) + timedelta(days=10), on_sale=True,
                      secret_address=True, address='1 Secret St')
    regular = TicketType(event=asylum, name='Regular', price_cents=2000, quantity=10)
    ga = TicketType(event=nightmare, name='GA', price_cents=0, quantity=3, gendered=True,
                    price_ladies_cents=1000, price_men_cents=1500)
    db.add_all([asylum, nightmare, regular, ga,
                Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123')),
                Staff(email='door@x.com', name='Door', role=StaffRole.door, password_hash=hash_password('door-pass-123'))])
    db.commit()
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})
    r = boss.post('/admin/combos', json={'slug': 'halloween', 'name': 'Combo pass', 'price_cents': 2500,
                                         'quantity': 5, 'max_per_order': 4, 'tier_ids': [regular.id, ga.id]})
    assert r.status_code == 200, r.text
    boss.patch('/admin/combos/halloween', json={'on_sale': True})
    return SimpleNamespace(asylum=asylum, nightmare=nightmare, regular=regular, ga=ga, boss=boss, calls=calls)


def buy(qty=1, names=None, emails=None, email='ada@example.com'):
    return client.post('/checkout/combo', json={'combo_slug': 'halloween', 'quantity': qty, 'name': 'Ada',
                                                'email': email, 'names': names or [], 'emails': emails or []})


def test_public_listing_and_event_box(setup):
    combos = client.get('/combos').json()
    assert [c['slug'] for c in combos] == ['halloween']
    c = combos[0]
    assert (c['price_cents'], c['status'], c['buyable']) == (2500, 'on_sale', 3)  # limited by Nightmare GA's 3 left
    assert [p['event_name'] for p in c['parts']] == ['Asylum', 'Nightmare']
    assert c['parts'][1]['venue'] == 'Address sent after purchase'  # never the secret address
    assert '1 Secret St' not in client.get('/combos/halloween').text
    # "Going to both?" on each event
    assert client.get('/events/asylum').json()['combos'][0]['slug'] == 'halloween'
    assert client.get('/events/nightmare').json()['combos'][0]['slug'] == 'halloween'


def test_full_flow(setup, db, sent_emails):
    r = buy(2, names=['', 'Grace'], emails=[None, 'grace@example.com'])
    assert r.status_code == 200, r.text
    order = db.get(Order, r.json()['order_id'])
    assert (order.event_id, order.combo_quantity, order.subtotal_cents) == (None, 2, 5000)
    # Holds stock on both nights
    assert client.get('/events/nightmare').json()['tiers'][0]['buyable'] == 1

    send('checkout.session.completed', paid_session(order))
    db.expire_all()
    tickets = db.scalars(select(Ticket).order_by(Ticket.holder_name, Ticket.event_id)).all()
    got = [(t.holder_name, t.event.slug, t.gender) for t in tickets]
    assert got == [('Ada', 'asylum', None), ('Ada', 'nightmare', None), ('Grace', 'asylum', None), ('Grace', 'nightmare', None)]

    # One email for the buyer (all 4 QRs), one for Grace (her 2), grouped by night
    assert [m['to'] for m in sent_emails] == [['ada@example.com'], ['grace@example.com']]
    buyer, grace = sent_emails
    assert buyer['subject'] == 'Your tickets: Combo pass' and len(buyer['attachments']) == 4
    assert 'Asylum' in buyer['html'] and 'Nightmare' in buyer['html'] and '1 Secret St' in buyer['html']
    assert grace['subject'] == 'Ada got you a pass: Combo pass' and len(grace['attachments']) == 2

    # Order page: grouped by night, secret address only on the Nightmare group
    page = client.get(f'/orders/{order.id}').json()
    assert page['title'] == 'Combo pass' and page['is_combo'] and page['event'] is None
    assert [g['event']['name'] for g in page['groups']] == ['Asylum', 'Nightmare']
    assert [len(g['tickets']) for g in page['groups']] == [2, 2]
    assert page['groups'][0]['event']['address'] is None and page['groups'][1]['event']['address'] == '1 Secret St'

    # Door: each QR works at its own night only
    door = TestClient(app)
    door.post('/auth/login', json={'email': 'door@x.com', 'password': 'door-pass-123'})
    ada_asylum = next(t for t in tickets if t.holder_name == 'Ada' and t.event.slug == 'asylum')
    assert door.post('/checkin', json={'event_slug': 'nightmare', 'code': ada_asylum.code}).json()['result'] == 'wrong_event'
    assert door.post('/checkin', json={'event_slug': 'asylum', 'code': ada_asylum.code}).json()['result'] == 'ok'

    # Dashboard: combo sales are their own line; each night counts the tickets but not the money
    combo = setup.boss.get('/admin/combos').json()[0]
    assert (combo['sold'], combo['revenue_cents'], combo['orders']) == (2, 5000, 1)
    asylum = setup.boss.get('/admin/events/asylum').json()
    reg = asylum['tiers'][0]
    assert (reg['sold'], reg['sold_combo'], reg['revenue_cents']) == (2, 2, 0)
    assert asylum['orders'] == 0 and asylum['revenue_cents'] == 0
    people = setup.boss.get('/admin/events/nightmare/attendees').json()
    assert {p['combo'] for p in people} == {'Combo pass'}

    # Address email reaches combo holders of that night
    from app.emails import address_recipients

    assert sorted(e for e, _ in address_recipients(db, setup.nightmare)) == ['ada@example.com', 'grace@example.com']

    # Full refund voids both nights
    send('charge.refunded', {'payment_intent': 'pi_1', 'amount': order.total_cents, 'amount_refunded': order.total_cents})
    db.expire_all()
    assert {t.status for t in db.scalars(select(Ticket))} == {TicketStatus.void}


def test_stock_and_caps(setup, db):
    # Nightmare GA has 3: a regular buyer takes 2, so only 1 combo fits
    r = client.post('/checkout', json={'event_slug': 'nightmare', 'name': 'B', 'email': 'b@example.com',
                                       'items': [{'tier_id': setup.ga.id, 'gender': 'men', 'quantity': 2}]})
    assert r.status_code == 200
    assert buy(2).json()['detail'] == 'Not enough Combo pass left'
    assert buy(1).status_code == 200
    assert client.get('/combos/halloween').json()['status'] == 'sold_out'
    # And regular Nightmare GA is now sold out too (the combo holds one)
    assert client.get('/events/nightmare').json()['tiers'][0]['status'] == 'sold_out'


def test_combo_cap(setup, db):
    setup.ga.quantity = 50
    db.commit()
    setup.boss.patch('/admin/combos/halloween', json={'quantity': 2})
    assert buy(2).status_code == 200
    assert buy(1).json()['detail'] == 'Combo pass is sold out'
    # Cap can't drop below what's sold or held
    assert setup.boss.patch('/admin/combos/halloween', json={'quantity': 1}).status_code == 400


def test_race_for_last_spot(setup, db):
    """Ten people try to buy the last Nightmare GA at once: 5 via combo, 5 directly."""
    setup.ga.quantity = 1
    db.commit()
    results = []

    def combo_buyer(i):
        results.append(('combo', buy(1, email=f'c{i}@example.com').status_code))

    def direct_buyer(i):
        r = TestClient(app).post('/checkout', json={'event_slug': 'nightmare', 'name': 'B', 'email': f'd{i}@example.com',
                                                    'items': [{'tier_id': setup.ga.id, 'gender': 'ladies', 'quantity': 1}]})
        results.append(('direct', r.status_code))

    threads = [threading.Thread(target=f, args=(i,)) for i in range(5) for f in (combo_buyer, direct_buyer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for _, code in results if code == 200) == 1
    assert db.query(Order).filter(Order.status == OrderStatus.pending).count() == 1


def test_admin_rules(setup):
    b = setup.boss
    two_same = b.post('/admin/combos', json={'slug': 'bad', 'name': 'Bad', 'price_cents': 100, 'quantity': 5,
                                             'tier_ids': [setup.regular.id, setup.regular.id]})
    assert two_same.status_code == 400
    assert b.post('/admin/combos', json={'slug': 'asylum', 'name': 'X', 'price_cents': 100, 'quantity': 5,
                                         'tier_ids': [setup.regular.id, setup.ga.id]}).status_code == 409  # event's link name
    # Hidden combos disappear publicly
    b.patch('/admin/combos/halloween', json={'on_sale': False})
    assert client.get('/combos').json() == [] and client.get('/combos/halloween').status_code == 404
    assert buy(1).status_code == 404
