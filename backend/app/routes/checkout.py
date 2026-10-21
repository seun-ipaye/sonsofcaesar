"""Start a purchase: hold the tickets, then send the buyer to Stripe's payment page.

Tickets themselves are only created once Stripe confirms payment (the webhook, step 6).
"""

import uuid
from datetime import UTC, datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.inventory import remaining, taken_counts
from app.models import GENDER_LABEL, Combo, Event, Gender, Order, OrderItem, OrderStatus, TicketType
from app.pricing import service_fee_cents
from app.routes.events import tier_status, upcoming_on_sale
from app.schemas import CheckoutIn, CheckoutOut, ComboCheckoutIn

router = APIRouter(prefix='/checkout', tags=['checkout'])

# Stripe's shortest allowed checkout lifetime is 30 minutes. Our hold lasts a
# little longer, so Stripe always closes the payment page before we release stock.
STRIPE_SESSION_MINUTES = 30
HOLD_MINUTES = 32


def line_name(event: Event, tier: TicketType, gender: Gender | None) -> str:
    # e.g. "Asylum · GA · Ladies"
    parts = [event.name, tier.name] + ([GENDER_LABEL[gender]] if gender else [])
    return ' · '.join(parts)


def create_stripe_session(order: Order, event: Event, tiers: dict[int, TicketType]) -> stripe.checkout.Session:
    line_items = [
        {
            'quantity': item.quantity,
            'price_data': {
                'currency': order.currency,
                'unit_amount': item.unit_price_cents,
                'product_data': {'name': line_name(event, tiers[item.ticket_type_id], item.gender)},
            },
        }
        for item in order.items
    ]
    line_items.append(
        {
            'quantity': 1,
            'price_data': {
                'currency': order.currency,
                'unit_amount': order.fee_cents,
                'product_data': {'name': 'Service fee'},
            },
        }
    )
    return _stripe_session(order, line_items, cancel_path=f'/tickets/{event.slug}')


def _stripe_session(order: Order, line_items: list[dict], cancel_path: str) -> stripe.checkout.Session:
    return stripe.checkout.Session.create(
        api_key=settings.stripe_secret_key,
        mode='payment',
        line_items=line_items,
        customer_email=order.buyer_email,
        client_reference_id=str(order.id),
        metadata={'order_id': str(order.id)},
        payment_intent_data={'metadata': {'order_id': str(order.id)}},
        expires_at=int((datetime.now(UTC) + timedelta(minutes=STRIPE_SESSION_MINUTES)).timestamp()),
        success_url=f'{settings.site_url}/order/{order.id}',
        cancel_url=f'{settings.site_url}{cancel_path}?cancelled={order.id}',
    )


def create_combo_session(order: Order, combo: Combo) -> stripe.checkout.Session:
    events = ' + '.join(p.ticket_type.event.name for p in sorted(combo.parts, key=lambda p: p.ticket_type.event.starts_at))
    line_items = [
        {
            'quantity': order.combo_quantity,
            'price_data': {
                'currency': order.currency,
                'unit_amount': combo.price_cents,
                'product_data': {'name': f'{combo.name} · {events}'},
            },
        },
        {
            'quantity': 1,
            'price_data': {
                'currency': order.currency,
                'unit_amount': order.fee_cents,
                'product_data': {'name': 'Service fee'},
            },
        },
    ]
    return _stripe_session(order, line_items, cancel_path=f'/tickets/{combo.slug}')


@router.post('', response_model=CheckoutOut)
def start_checkout(body: CheckoutIn, db: Session = Depends(get_db)):
    now = datetime.now(UTC)

    if not settings.stripe_is_live and not settings.test_payments_allowed:
        raise HTTPException(503, 'Ticket sales open soon.')

    event = db.scalars(upcoming_on_sale(db).where(Event.slug == body.event_slug)).first()
    if not event:
        raise HTTPException(404, 'This event is not on sale')

    # One line per (tier, gender). Gender-priced tiers can have a Ladies line and a
    # Men line; both draw from the tier's one shared quantity.
    lines: dict[tuple[int, Gender | None], dict] = {}
    buyer_name = body.name.strip()
    for item in body.items:
        gender = Gender(item.gender) if item.gender else None
        key = (item.tier_id, gender)
        if key in lines:
            raise HTTPException(400, 'Each ticket type should appear once')
        if len(item.names) > item.quantity or len(item.emails) > item.quantity:
            raise HTTPException(400, 'More names than tickets')
        given = [(n or '').strip()[:200] for n in item.names]
        lines[key] = {
            'quantity': item.quantity,
            'names': [(given[i] if i < len(given) and given[i] else buyer_name) for i in range(item.quantity)],
            'emails': [
                (item.emails[i].lower() if i < len(item.emails) and item.emails[i] else None)
                for i in range(item.quantity)
            ],
        }

    per_tier: dict[int, int] = {}
    for (tier_id, _), line in lines.items():
        per_tier[tier_id] = per_tier.get(tier_id, 0) + line['quantity']

    # Lock these tiers until we commit. A second buyer going for the same tiers
    # waits here, then sees this order's hold, so the last ticket can't sell twice.
    # (Sorted by id so two buyers always lock in the same order.)
    tiers = {
        t.id: t
        for t in db.scalars(
            select(TicketType)
            .where(TicketType.id.in_(sorted(per_tier)), TicketType.event_id == event.id)
            .order_by(TicketType.id)
            .with_for_update()
        )
    }
    taken = taken_counts(db, list(tiers))

    for (tier_id, gender) in lines:
        tier = tiers.get(tier_id)
        if not tier or not tier.active:
            raise HTTPException(400, 'That ticket type is not available')
        if tier.gendered and gender is None:
            raise HTTPException(400, f'Choose Ladies or Men for {tier.name}')
        if not tier.gendered and gender is not None:
            raise HTTPException(400, f'{tier.name} is not priced by gender')

    for tier_id, qty in per_tier.items():
        tier = tiers[tier_id]
        left = remaining(tier, taken[tier_id])
        status = tier_status(tier, left, now)
        if status == 'not_yet':
            if event.sales_start and now < event.sales_start:
                raise HTTPException(400, 'Tickets for this event are not on sale yet')
            raise HTTPException(400, f'{tier.name} is not on sale yet')
        if status == 'ended':
            raise HTTPException(400, f'{tier.name} sales have ended')
        if qty > tier.max_per_order:
            raise HTTPException(400, f'Max {tier.max_per_order} {tier.name} per order')
        if qty > left:
            # Deliberately no number: stock levels stay private
            raise HTTPException(
                409, f'{tier.name} is sold out' if left == 0 else f'Not enough {tier.name} tickets left'
            )

    subtotal = sum(tiers[tid].price_for(g) * line['quantity'] for (tid, g), line in lines.items())
    if subtotal == 0:
        raise HTTPException(400, 'Free tickets are not supported yet')
    fee = service_fee_cents(subtotal)

    order = Order(
        event_id=event.id,
        buyer_name=buyer_name,
        buyer_email=body.email.lower(),
        subtotal_cents=subtotal,
        fee_cents=fee,
        total_cents=subtotal + fee,
        expires_at=now + timedelta(minutes=HOLD_MINUTES),
        items=[
            OrderItem(
                ticket_type_id=tid,
                gender=g,
                quantity=line['quantity'],
                unit_price_cents=tiers[tid].price_for(g),
                holder_names=line['names'],
                holder_emails=line['emails'],
            )
            for (tid, g), line in lines.items()
        ],
    )
    db.add(order)
    db.flush()  # gives the order its id, still inside the lock

    try:
        session = create_stripe_session(order, event, tiers)
    except stripe.StripeError:
        db.rollback()  # nothing is held if Stripe failed
        raise HTTPException(502, 'Payment provider error, please try again')

    order.stripe_session_id = session.id
    db.commit()  # saves the hold and releases the lock
    return CheckoutOut(order_id=str(order.id), checkout_url=session.url)


@router.post('/{order_id}/cancel')
def cancel_checkout(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Buyer clicked "back" on Stripe: close their payment page and release the hold
    now, instead of keeping the tickets off sale for 30 minutes."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != OrderStatus.pending:
        return {'released': False}
    try:
        stripe.checkout.Session.expire(order.stripe_session_id, api_key=settings.stripe_secret_key)
    except stripe.InvalidRequestError:
        # Stripe won't expire it, e.g. they actually paid in another tab. Leave it alone.
        db.rollback()
        return {'released': False}
    order.status = OrderStatus.expired
    db.commit()
    return {'released': True}


@router.post('/combo', response_model=CheckoutOut)
def start_combo_checkout(body: ComboCheckoutIn, db: Session = Depends(get_db)):
    """Buy combo passes: each pass holds one ticket from every part tier."""
    from app.combos import combo_state
    from app.routes.combos import visible

    now = datetime.now(UTC)
    if not settings.stripe_is_live and not settings.test_payments_allowed:
        raise HTTPException(503, 'Ticket sales open soon.')

    combo = db.scalar(select(Combo).where(Combo.slug == body.combo_slug).with_for_update())
    if not combo or not visible(db, combo):
        raise HTTPException(404, 'This combo is not on sale')
    # Lock the part tiers too (same order as regular checkout: by id), so a combo and
    # a regular ticket can't both take the last spot
    tier_ids = sorted(p.ticket_type_id for p in combo.parts)
    db.scalars(select(TicketType).where(TicketType.id.in_(tier_ids)).order_by(TicketType.id).with_for_update()).all()

    status, buyable = combo_state(db, combo, now)
    if status == 'not_yet':
        raise HTTPException(400, f'{combo.name} is not on sale yet')
    if status == 'ended':
        raise HTTPException(400, f'{combo.name} sales have ended')
    if body.quantity > combo.max_per_order:
        raise HTTPException(400, f'Max {combo.max_per_order} {combo.name} per order')
    if status == 'sold_out' or body.quantity > buyable:
        raise HTTPException(409, f'{combo.name} is sold out' if status == 'sold_out' else f'Not enough {combo.name} left')
    if len(body.names) > body.quantity or len(body.emails) > body.quantity:
        raise HTTPException(400, 'More names than passes')

    buyer_name = body.name.strip()
    given = [(n or '').strip()[:200] for n in body.names]
    names = [(given[i] if i < len(given) and given[i] else buyer_name) for i in range(body.quantity)]
    emails = [(body.emails[i].lower() if i < len(body.emails) and body.emails[i] else None) for i in range(body.quantity)]

    subtotal = combo.price_cents * body.quantity
    if subtotal == 0:
        raise HTTPException(400, 'Free tickets are not supported yet')
    fee = service_fee_cents(subtotal)
    order = Order(
        event_id=None,  # spans several events; each ticket has its own
        combo_id=combo.id,
        combo_quantity=body.quantity,
        buyer_name=buyer_name,
        buyer_email=body.email.lower(),
        subtotal_cents=subtotal,
        fee_cents=fee,
        total_cents=subtotal + fee,
        expires_at=now + timedelta(minutes=HOLD_MINUTES),
        # One line per part tier: holds that tier's stock, and becomes that night's
        # tickets on payment. The price lives on the combo, so these lines are $0.
        items=[
            OrderItem(
                ticket_type_id=part.ticket_type_id,
                quantity=body.quantity,
                unit_price_cents=0,
                holder_names=names,
                holder_emails=emails,
            )
            for part in combo.parts
        ],
    )
    db.add(order)
    db.flush()

    try:
        session = create_combo_session(order, combo)
    except stripe.StripeError:
        db.rollback()
        raise HTTPException(502, 'Payment provider error, please try again')

    order.stripe_session_id = session.id
    db.commit()
    return CheckoutOut(order_id=str(order.id), checkout_url=session.url)
