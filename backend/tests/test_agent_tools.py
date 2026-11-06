import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import resend

from app import agent_tools as tools
from app.models import Event, Order, OrderItem, OrderStatus, Ticket, TicketStatus, TicketType

SECRET = '12 Hidden Lane'


@pytest.fixture
def event(db):
    e = Event(
        slug='night', name='Night', starts_at=datetime.now(UTC) + timedelta(days=5), on_sale=True,
        secret_address=True, address=SECRET,
    )
    db.add(TicketType(event=e, name='GA', price_cents=2000, quantity=10))
    db.commit()
    return e


def make_order(db, event, email='ada@example.com', status=OrderStatus.paid, **fields):
    tier = event.ticket_types[0]
    order = Order(
        event_id=event.id, buyer_name='Ada Secretname', buyer_email=email, status=status,
        subtotal_cents=2000, fee_cents=100, total_cents=2100,
        expires_at=datetime.now(UTC) + timedelta(minutes=30), **fields,
        items=[OrderItem(ticket_type_id=tier.id, quantity=1, unit_price_cents=2000)],
    )
    db.add(order)
    db.flush()
    db.add(Ticket(order_id=order.id, event_id=event.id, ticket_type_id=tier.id, holder_name='Holder Secretname'))
    db.commit()
    return order


def test_event_info_is_public_data_only(db, event):
    db.add(Event(slug='hidden', name='Hidden', starts_at=datetime.now(UTC) + timedelta(days=9), on_sale=False))
    db.add(Event(slug='past', name='Past', starts_at=datetime.now(UTC) - timedelta(days=9), on_sale=True))
    db.commit()

    result = tools.get_event_info(db)

    assert [e['name'] for e in result['events']] == ['Night']
    assert result['events'][0]['tiers'][0]['price'] == '$20.00'
    assert SECRET not in json.dumps(result)


def test_event_info_shows_both_gender_prices(db, event):
    db.add(TicketType(event=event, name='Mix', price_cents=0, quantity=5, gendered=True,
                      price_ladies_cents=1000, price_men_cents=1500))
    db.commit()
    tier = next(t for t in tools.get_event_info(db)['events'][0]['tiers'] if t['name'] == 'Mix')
    assert (tier['ladies_price'], tier['men_price']) == ('$10.00', '$15.00')


def test_order_status_never_reveals_private_fields(db, event):
    order = make_order(db, event)
    text = json.dumps(tools.get_order_status(db, str(order.id)), ensure_ascii=False)

    assert '"status": "paid"' in text and 'ad•••@example.com' in text
    code = order.tickets[0].code
    for private in (code, code[-4:], SECRET, 'Secretname', 'ada@example.com'):
        assert private not in text


@pytest.mark.parametrize('bad', ['ada@example.com', 'not-an-id', '', str(uuid.uuid4())])
def test_order_status_needs_the_real_id(db, event, bad):
    make_order(db, event)
    assert tools.get_order_status(db, bad) == {'error': 'order not found'}


def test_resend_goes_to_the_address_on_the_order(db, event, sent_emails):
    order = make_order(db, event)
    result = tools.resend_my_tickets(db, '  ADA@example.com ')

    assert [m['to'] for m in sent_emails] == [['ada@example.com']]
    assert result == {'message': tools.RESEND_REPLY}
    db.expire_all()
    assert db.get(Order, order.id).buyer_email == 'ada@example.com'
    assert db.get(Order, order.id).resend_count == 1


def test_resend_reply_is_the_same_with_or_without_an_order(db, event, sent_emails):
    make_order(db, event)
    assert tools.resend_my_tickets(db, 'ada@example.com') == tools.resend_my_tickets(db, 'nobody@example.com')
    assert len(sent_emails) == 1


def test_resend_has_a_cooldown_and_keeps_some_resends_for_the_order_page(db, event, sent_emails):
    order = make_order(db, event)
    tools.resend_my_tickets(db, 'ada@example.com')
    tools.resend_my_tickets(db, 'ada@example.com')
    assert len(sent_emails) == 1  # cooldown

    db.expire_all()
    fresh = db.get(Order, order.id)
    fresh.last_resent_at = datetime.now(UTC) - timedelta(hours=2)
    fresh.resend_count = tools.AGENT_MAX_RESENDS
    db.commit()
    tools.resend_my_tickets(db, 'ada@example.com')
    assert len(sent_emails) == 1  # the remaining resends are the order page's


@pytest.mark.parametrize('status', [OrderStatus.pending, OrderStatus.expired, OrderStatus.refunded])
def test_resend_skips_orders_that_are_not_paid(db, event, sent_emails, status):
    make_order(db, event, status=status)
    tools.resend_my_tickets(db, 'ada@example.com')
    assert sent_emails == []


def test_resend_skips_past_events(db, event, sent_emails):
    event.starts_at = datetime.now(UTC) - timedelta(days=2)
    make_order(db, event)
    tools.resend_my_tickets(db, 'ada@example.com')
    assert sent_emails == []


def test_resend_email_failure_gives_the_same_reply(db, event, monkeypatch):
    make_order(db, event)

    def down(params):
        raise RuntimeError('resend down')

    monkeypatch.setattr(resend.Emails, 'send', down)
    assert tools.resend_my_tickets(db, 'ada@example.com') == {'message': tools.RESEND_REPLY}


def test_resend_rejects_a_non_email(db, sent_emails):
    assert 'error' in tools.resend_my_tickets(db, 'ada')
    assert sent_emails == []


def test_search_returns_only_title_and_text(db, monkeypatch):
    from app.models import KnowledgeChunk

    chunk = KnowledgeChunk(source='a.md', heading='Refunds', content='Final.', content_hash='x', embedding=[0.0] * 1024)
    monkeypatch.setattr(tools, 'search_chunks', lambda db, query: [chunk])
    assert tools.search_knowledge(db, 'refund?') == {'results': [{'title': 'Refunds', 'text': 'Final.'}]}


def test_every_tool_definition_has_a_runner():
    assert {t['name'] for t in tools.TOOLS} == set(tools._RUNNERS)


def test_run_tool_returns_json_for_failures_without_details(db, monkeypatch):
    assert json.loads(tools.run_tool(db, 'drop_tables', {})) == {'error': 'unknown tool drop_tables'}
    assert json.loads(tools.run_tool(db, 'get_order_status', {'wrong': 1})) == {'error': 'bad arguments'}

    def boom(db, query):
        raise RuntimeError('password=hunter2')

    monkeypatch.setitem(tools._RUNNERS, 'search_knowledge', boom)
    result = tools.run_tool(db, 'search_knowledge', {'query': 'x'})
    assert 'hunter2' not in result and 'error' in result
