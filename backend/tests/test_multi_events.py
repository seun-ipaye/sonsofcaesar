from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import Event, Staff, StaffRole, TicketType
from app.security import hash_password

client = TestClient(app)


def days(n):
    return datetime.now(UTC) + timedelta(days=n)


def setup_events(db):
    asylum = Event(slug='asylum', name='Asylum', starts_at=days(14), on_sale=True, poster_url='/images/a.jpg')
    nightmare = Event(slug='nightmare', name='Nightmare', starts_at=days(15), on_sale=True, sales_start=days(10))
    hidden = Event(slug='draft', name='Draft', starts_at=days(20), on_sale=False)
    db.add_all([
        asylum, nightmare, hidden,
        TicketType(event=asylum, name='Early Bird', price_cents=1500, quantity=20),
        TicketType(event=asylum, name='Regular', price_cents=2000, quantity=100, sort_order=1),
        TicketType(event=nightmare, name='GA', price_cents=2500, quantity=100),
        TicketType(event=hidden, name='GA', price_cents=1000, quantity=10),
    ])
    db.commit()


def test_choice_screen_lists_listed_events(db):
    setup_events(db)
    cards = client.get('/events').json()
    assert [c['slug'] for c in cards] == ['asylum', 'nightmare']  # soonest first, drafts hidden
    a, n = cards
    assert (a['status'], a['from_price_cents'], a['poster_url']) == ('on_sale', 1500, '/images/a.jpg')
    assert (n['status'], n['from_price_cents']) == ('not_yet', 2500)
    assert n['sales_start'] is not None


def test_sales_start_blocks_buying_until_then(db):
    setup_events(db)
    page = client.get('/events/nightmare').json()
    assert page['sales_start'] and all(t['status'] == 'not_yet' for t in page['tiers'])
    ga = page['tiers'][0]['id']
    r = client.post('/checkout', json={
        'event_slug': 'nightmare', 'items': [{'tier_id': ga, 'quantity': 1}], 'name': 'A', 'email': 'a@example.com',
    })
    assert r.status_code == 400 and r.json()['detail'] == 'Tickets for this event are not on sale yet'

    # Once the start time passes, it's on sale on its own
    ev = db.query(Event).filter_by(slug='nightmare').one()
    ev.sales_start = days(-1)
    db.commit()
    assert all(t['status'] == 'on_sale' for t in client.get('/events/nightmare').json()['tiers'])


def test_admin_can_rename_link_and_set_sales_start(db):
    setup_events(db)
    db.add(Staff(email='boss@x.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123')))
    db.commit()
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})

    r = boss.patch('/admin/events/asylum', json={'slug': 'asylum-windsor'})
    assert r.status_code == 200 and r.json()['slug'] == 'asylum-windsor'
    assert client.get('/events/asylum-windsor').status_code == 200
    assert client.get('/events/asylum').status_code == 404

    assert boss.patch('/admin/events/asylum-windsor', json={'slug': 'nightmare'}).status_code == 409  # taken
    assert boss.patch('/admin/events/asylum-windsor', json={'slug': 'Bad Name'}).status_code == 422

    start = days(3).isoformat()
    r = boss.patch('/admin/events/asylum-windsor', json={'sales_start': start})
    assert r.json()['sales_start'] is not None
    r = boss.patch('/admin/events/asylum-windsor', json={'sales_start': None})  # clear: open now
    assert r.json()['sales_start'] is None
