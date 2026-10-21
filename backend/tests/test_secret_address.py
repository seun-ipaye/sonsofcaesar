from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Event, Order, OrderItem, OrderStatus, Staff, StaffRole, Ticket, TicketStatus, TicketType
from app.security import hash_password

ADDRESS = '1234 Secret St, Windsor'
client = TestClient(app)


@pytest.fixture
def party(db):
    e = Event(
        slug='nightmare', name='Nightmare', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True,
        venue='Somewhere', secret_address=True, address=ADDRESS,
    )
    ga = TicketType(event=e, name='GA', price_cents=2000, quantity=50)
    db.add_all([e, ga, Staff(email='boss@x.com', name='Boss', role=StaffRole.admin,
                             password_hash=hash_password('admin-pass-123'))])
    db.commit()

    def order(buyer, status=OrderStatus.paid, friend=None):
        o = Order(event_id=e.id, buyer_name='B', buyer_email=buyer, status=status, subtotal_cents=2000,
                  fee_cents=0, total_cents=2000, expires_at=datetime.now(UTC),
                  items=[OrderItem(ticket_type_id=ga.id, quantity=2, unit_price_cents=2000)])
        db.add(o)
        db.flush()
        void = status == OrderStatus.refunded
        st = TicketStatus.void if void else TicketStatus.valid
        db.add_all([
            Ticket(order=o, event_id=e.id, ticket_type_id=ga.id, holder_name='B', status=st),
            Ticket(order=o, event_id=e.id, ticket_type_id=ga.id, holder_name='F', holder_email=friend, status=st),
        ])
        db.commit()
        return o

    paid = order('ada@example.com', friend='grace@example.com')
    order('Ada@Example.com')  # same buyer again: one email, not two
    refunded = order('rita@example.com', status=OrderStatus.refunded, friend='rfriend@example.com')
    return e, paid, refunded


def test_public_never_sees_the_address(party):
    page = client.get('/events/nightmare').text
    cards = client.get('/events').text
    assert ADDRESS not in page and ADDRESS not in cards
    assert client.get('/events/nightmare').json()['venue'] == 'Address sent after purchase'


def test_valid_holders_see_it_refunded_do_not(party, db):
    _, paid, refunded = party
    assert client.get(f'/orders/{paid.id}').json()['event']['address'] == ADDRESS
    code = paid.tickets[0].code
    assert client.get(f'/tickets/{code}').json()['event']['address'] == ADDRESS

    assert client.get(f'/orders/{refunded.id}').json()['event']['address'] is None
    assert client.get(f'/tickets/{refunded.tickets[0].code}').json()['event']['address'] is None

    # A single voided ticket loses it even inside a paid order
    t = paid.tickets[1]
    t.status = TicketStatus.void
    db.commit()
    assert client.get(f'/tickets/{t.code}').json()['event']['address'] is None


def test_email_everyone_with_a_ticket(party, sent_emails, monkeypatch):
    import resend

    batches = []
    monkeypatch.setattr(resend.Batch, 'send', lambda params: batches.append(params) or {'data': []})
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})

    assert boss.get('/admin/events/nightmare/email-address').json() == {'recipients': 2}
    r = boss.post('/admin/events/nightmare/email-address')
    assert r.json() == {'sent': 2}
    sent = batches[0]
    assert sorted(m['to'][0] for m in sent) == ['ada@example.com', 'grace@example.com']  # no refunded people
    assert all(ADDRESS in m['html'] and m['subject'] == 'The address for Nightmare' for m in sent)
    grace = next(m for m in sent if m['to'] == ['grace@example.com'])
    assert '/t/' in grace['html'] and '/order/' not in grace['html']  # friend only sees their ticket link
    assert boss.get('/admin/events/nightmare').json()['address_emailed_at'] is not None


def test_cannot_email_without_an_address(party, db):
    e, _, _ = party
    e.secret_address = False
    db.commit()
    boss = TestClient(app)
    boss.post('/auth/login', json={'email': 'boss@x.com', 'password': 'admin-pass-123'})
    assert boss.post('/admin/events/nightmare/email-address').status_code == 400
    assert TestClient(app).post('/admin/events/nightmare/email-address').status_code == 401


def test_ticket_email_includes_address(party, db):
    from app.emails import render_friend_email, render_tickets_email

    _, paid, _ = party
    assert ADDRESS in render_tickets_email(paid)[1] and 'Open in Maps' in render_tickets_email(paid)[1]
    assert ADDRESS in render_friend_email(paid, paid.tickets[1])[1]
