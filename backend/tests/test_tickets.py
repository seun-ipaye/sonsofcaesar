from fastapi.testclient import TestClient
from sqlalchemy import select

from app.emails import render_tickets_email
from app.main import app
from app.models import Order, Ticket
from tests.test_webhooks import order, paid_session, send, webhook_secret  # noqa: F401  (fixtures)

client = TestClient(app)


def test_payment_emails_tickets_once(db, order, sent_emails):
    for _ in range(3):
        send('checkout.session.completed', paid_session(order))
    assert len(sent_emails) == 1
    mail = sent_emails[0]
    assert mail['to'] == ['ada@example.com']
    assert mail['subject'] == 'Your tickets: E'
    assert len(mail['attachments']) == 3  # one QR per ticket
    db.expire_all()
    assert db.get(Order, order.id).emailed_at is not None


def test_email_failure_does_not_lose_the_payment(db, order, monkeypatch):
    import resend

    def down(params):
        raise RuntimeError('resend down')

    monkeypatch.setattr(resend.Emails, 'send', down)
    assert send('checkout.session.completed', paid_session(order)).status_code == 200
    db.expire_all()
    o = db.get(Order, order.id)
    assert o.status.value == 'paid' and len(o.tickets) == 3
    assert o.emailed_at is None  # so it can be retried


def test_ticket_and_order_pages(db, order):
    send('checkout.session.completed', paid_session(order))
    code = db.scalar(select(Ticket.code))

    t = client.get(f'/tickets/{code}').json()
    assert t['status'] == 'valid' and t['event']['name'] == 'E' and t['holder_name'] == 'Ada'

    png = client.get(f'/tickets/{code}/qr.png')
    assert png.headers['content-type'] == 'image/png' and png.content[:4] == b'\x89PNG'
    assert client.get(f'/tickets/{code}/qr.svg').headers['content-type'].startswith('image/svg')
    assert client.get('/tickets/not-a-real-code/qr.png').status_code == 404

    o = client.get(f'/orders/{order.id}').json()
    assert o['status'] == 'paid' and len(o['tickets']) == 3
    assert client.get('/orders/00000000-0000-0000-0000-000000000000').status_code == 404


def test_email_escapes_names(db, order):
    send('checkout.session.completed', paid_session(order))
    db.expire_all()
    o = db.get(Order, order.id)
    o.buyer_name = '<script>x</script>'
    _, body = render_tickets_email(o)
    assert '<script>x</script>' not in body and '&lt;script&gt;' in body
