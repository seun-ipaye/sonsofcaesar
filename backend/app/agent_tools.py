"""What the support agent can look up and do.

Treat everything returned here as if the person chatting can read it, because the
model may repeat it. So each tool returns a short allowlist of fields, and never:
ticket codes, QR codes, holder names, full emails, order ids of other people or
secret addresses.
"""

import json
import logging
import re
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.emails import mask_email, send_tickets_email
from app.knowledge import search_knowledge as search_chunks
from app.models import Event, Order, OrderStatus, Ticket, TicketStatus
from app.routes.events import event_out, upcoming_on_sale
from app.routes.tickets import MAX_RESENDS

log = logging.getLogger(__name__)
TZ = ZoneInfo('America/Toronto')

# Anyone can type someone else's email here, so the agent gets less than the order
# page: rarer sends, and the last resends are kept for the page's wrong-email form.
AGENT_RESEND_COOLDOWN = timedelta(hours=1)
AGENT_MAX_RESENDS = MAX_RESENDS - 2

EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')

# The same words whether or not an order exists, so this can't reveal who bought tickets
RESEND_REPLY = (
    "If there's a paid order for an upcoming event under that email, its tickets have been sent to it. "
    'The email can take a few minutes and may land in spam. If nothing arrives, give the name on your '
    'ticket at the door or DM @socfrvr.'
)


def _when(moment: datetime) -> str:
    return moment.astimezone(TZ).strftime('%A, %B %-d, %Y at %-I:%M %p')


def _dollars(cents: int | None) -> str | None:
    return None if cents is None else f'${cents / 100:,.2f}'


def search_knowledge(db: Session, query: str) -> dict:
    query = query.strip()
    if not query:
        return {'error': 'query is empty'}
    return {'results': [{'title': c.heading, 'text': c.content} for c in search_chunks(db, query[:500])]}


def _tier_prices(tier) -> dict:
    if tier.gendered:
        return {'ladies_price': _dollars(tier.price_ladies_cents), 'men_price': _dollars(tier.price_men_cents)}
    return {'price': _dollars(tier.price_cents)}


def get_event_info(db: Session) -> dict:
    """Listed, upcoming events: the same public data as the tickets page."""
    events = []
    for event in db.scalars(upcoming_on_sale(db)):
        out = event_out(db, event)
        events.append(
            {
                'name': out.name,
                'starts': _when(out.starts_at),
                'venue': out.venue,
                'description': out.description,
                'tickets_page': f'/tickets/{out.slug}',
                'tiers': [{'name': t.name, 'status': t.status, **_tier_prices(t)} for t in out.tiers],
                'combos': [
                    {
                        'name': c.name,
                        'status': c.status,
                        'price': _dollars(c.price_cents),
                        'events': [p.event_name for p in c.parts],
                    }
                    for c in out.combos
                ],
            }
        )
    return {'events': events}


def get_order_status(db: Session, order_id: str) -> dict:
    """The long random id is the proof of access, like the order link itself."""
    try:
        order = db.get(Order, uuid.UUID(order_id.strip()))
    except ValueError:
        order = None
    if not order:
        return {'error': 'order not found'}

    tickets = order.tickets
    return {
        'status': order.status.value,
        'email_hint': mask_email(order.buyer_email),
        'tickets_emailed': order.emailed_at is not None,
        'tickets': len(tickets),
        'tickets_scanned': sum(t.checked_in_at is not None for t in tickets),
        'tickets_void': sum(t.status == TicketStatus.void for t in tickets),
        'by_event': [
            {'event': name, 'tickets': count} for name, count in Counter(t.event.name for t in tickets).items()
        ],
    }


def resend_my_tickets(db: Session, email: str) -> dict:
    """Re-send to the address already on each matching order. It can never send
    anywhere else, so at worst a stranger gets someone their own tickets again."""
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        return {'error': "that doesn't look like an email address"}

    now = datetime.now(UTC)
    order_ids = db.scalars(
        select(Order.id)
        .join(Ticket)
        .join(Event, Ticket.event_id == Event.id)
        .where(
            func.lower(Order.buyer_email) == email,
            Order.status == OrderStatus.paid,
            func.coalesce(Event.ends_at, Event.starts_at) > now,
        )
        .distinct()
    ).all()

    for order_id in order_ids:
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        too_soon = order.last_resent_at and now - order.last_resent_at < AGENT_RESEND_COOLDOWN
        if order.resend_count >= AGENT_MAX_RESENDS or too_soon:
            db.rollback()
            continue
        order.resend_count += 1
        order.last_resent_at = now
        db.commit()
        try:
            send_tickets_email(db, order_id, force=True)
        except Exception:
            db.rollback()
            log.exception('Agent resend failed for order %s', order_id)
    return {'message': RESEND_REPLY}


_RUNNERS: dict[str, Callable[..., dict]] = {
    'search_knowledge': search_knowledge,
    'get_event_info': get_event_info,
    'get_order_status': get_order_status,
    'resend_my_tickets': resend_my_tickets,
}

TOOLS: list[dict[str, Any]] = [
    {
        'name': 'search_knowledge',
        'description': (
            'Search the Sons of Caesar support docs: delivery of tickets, the door, buying, transfers, refunds, '
            'age and ID rules, privacy. Use it for any policy or how-to question. Results may not be relevant; '
            'only rely on one if it actually answers the question.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': 'What the person wants to know'}},
            'required': ['query'],
        },
    },
    {
        'name': 'get_event_info',
        'description': (
            'List upcoming events with dates, public venue, ticket tiers, prices and whether each is on sale. '
            'Use it for any question about what is on, when, or how much.'
        ),
        'input_schema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_order_status',
        'description': (
            "Check one order's status using its order id, the long id in the person's order link. "
            'Only use an id the person gave you. It shows no ticket codes or addresses.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'order_id': {'type': 'string', 'description': 'The order id (a UUID)'}},
            'required': ['order_id'],
        },
    },
    {
        'name': 'resend_my_tickets',
        'description': (
            'Re-send tickets to the email on the order, when someone says their tickets did not arrive. Takes the '
            "email they bought with. It cannot send to a different address and won't say whether an order exists. "
            'Only use it when the person asks for their tickets again.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'email': {'type': 'string', 'description': 'The email used at checkout'}},
            'required': ['email'],
        },
    },
]


def run_tool(db: Session, name: str, arguments: dict) -> str:
    """Run a tool the model asked for and return JSON for it. A failure comes back as
    a plain error so the agent can hand off, with the details kept in the logs."""
    runner = _RUNNERS.get(name)
    if not runner:
        return json.dumps({'error': f'unknown tool {name}'})
    try:
        return json.dumps(runner(db, **arguments))
    except TypeError:
        log.warning('Agent called %s with bad arguments', name)
        return json.dumps({'error': 'bad arguments'})
    except Exception:
        db.rollback()
        log.exception('Agent tool %s failed', name)
        return json.dumps({'error': 'this is not working right now'})
