from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import Event, Order, OrderItem, OrderStatus, TicketType
from app.pricing import service_fee_cents

client = TestClient(app)  # not used as a context manager, so startup migrations don't run


def days(n):
    return datetime.now(UTC) + timedelta(days=n)


def test_service_fee_covers_stripe():
    for subtotal in [1500, 2000, 4000, 8000, 12345]:
        fee = service_fee_cents(subtotal)
        total = subtotal + fee
        stripe_cut = round(total * 0.029 + 30)
        # We keep at least the full ticket price, and never overcharge by more than a cent
        assert total - stripe_cut >= subtotal
        assert total - stripe_cut - subtotal <= 1
    assert service_fee_cents(0) == 0


def test_current_event_and_tier_statuses(db):
    past = Event(slug='old', name='Old', starts_at=days(-10), on_sale=True)
    hidden = Event(slug='draft', name='Draft', starts_at=days(5), on_sale=False)
    event = Event(slug='vol-iii', name='VOL III', starts_at=days(20), venue='Windsor', on_sale=True)
    later = Event(slug='vol-iv', name='VOL IV', starts_at=days(60), on_sale=True)
    early = TicketType(event=event, name='Early Bird', price_cents=1500, quantity=10, sales_end=days(-1))
    ga = TicketType(event=event, name='GA', price_cents=2000, quantity=3, sort_order=1)
    vip = TicketType(event=event, name='VIP', price_cents=4000, quantity=5, sales_start=days(2), sort_order=2)
    secret = TicketType(event=event, name='Comp', price_cents=0, quantity=5, active=False, sort_order=3)
    db.add_all([past, hidden, event, later, early, ga, vip, secret])
    db.commit()
    db.add(
        Order(
            event_id=event.id, buyer_name='x', buyer_email='x@x.com', status=OrderStatus.paid,
            subtotal_cents=6000, fee_cents=0, total_cents=6000, expires_at=days(1),
            items=[OrderItem(ticket_type_id=ga.id, quantity=3, unit_price_cents=2000)],
        )
    )
    db.commit()

    r = client.get('/events/current')
    assert r.status_code == 200
    body = r.json()
    # Skips past and not-on-sale events, picks the soonest
    assert body['slug'] == 'vol-iii'
    tiers = {t['name']: t for t in body['tiers']}
    assert 'Comp' not in tiers  # hidden tiers aren't shown
    assert tiers['Early Bird']['status'] == 'ended'
    assert tiers['GA']['status'] == 'sold_out' and tiers['GA']['buyable'] == 0
    # Real stock is never sent: VIP has 5 left but shows at most its per-order limit
    assert 'remaining' not in tiers['VIP'] and tiers['VIP']['buyable'] == 4
    assert tiers['VIP']['status'] == 'not_yet'
    assert tiers['GA']['fee_for_one_cents'] == service_fee_cents(2000)

    assert client.get('/events/vol-iv').json()['name'] == 'VOL IV'
    assert client.get('/events/draft').status_code == 404


def test_no_event_on_sale():
    assert client.get('/events/current').status_code == 404
