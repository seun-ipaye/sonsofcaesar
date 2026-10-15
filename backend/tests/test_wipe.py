from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app import cli as cli_module
from app.models import Event, Order, OrderItem, OrderStatus, Staff, StaffRole, Ticket, TicketType

runner = CliRunner()


def seed(db, session_id):
    e = Event(slug='e', name='E', starts_at=datetime.now(UTC) + timedelta(days=5))
    ga = TicketType(event=e, name='GA', price_cents=2000, quantity=10)
    db.add_all([e, ga, Staff(email='s@x.com', name='S', role=StaffRole.admin, password_hash='x')])
    db.commit()
    o = Order(
        event_id=e.id, buyer_name='A', buyer_email='a@x.com', status=OrderStatus.paid, stripe_session_id=session_id,
        subtotal_cents=2000, fee_cents=0, total_cents=2000, expires_at=datetime.now(UTC),
        items=[OrderItem(ticket_type_id=ga.id, quantity=1, unit_price_cents=2000)],
    )
    db.add(o)
    db.flush()
    db.add(Ticket(order=o, event_id=e.id, ticket_type_id=ga.id, holder_name='A'))
    db.commit()


def test_wipes_test_orders_keeps_setup(db, monkeypatch):
    seed(db, 'cs_test_abc')
    monkeypatch.setattr(cli_module, 'SessionLocal', lambda: Session(db.get_bind()))
    # Wrong confirmation: nothing deleted
    r = runner.invoke(cli_module.cli, ['wipe-test-orders'], input='nope\n')
    assert r.exit_code == 1 and db.query(Order).count() == 1

    r = runner.invoke(cli_module.cli, ['wipe-test-orders'], input='WIPE\n')
    assert r.exit_code == 0, r.output
    db.expire_all()
    assert db.query(Order).count() == 0 and db.query(Ticket).count() == 0
    assert db.query(Event).count() == 1 and db.query(TicketType).count() == 1 and db.query(Staff).count() == 1


def test_refuses_when_live_orders_exist(db, monkeypatch):
    seed(db, 'cs_live_real_money')
    monkeypatch.setattr(cli_module, 'SessionLocal', lambda: Session(db.get_bind()))
    r = runner.invoke(cli_module.cli, ['wipe-test-orders', '--yes'])
    assert r.exit_code == 1 and 'LIVE' in r.output
    db.expire_all()
    assert db.query(Order).count() == 1
