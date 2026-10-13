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
from app.models import Event, Order, OrderItem, OrderStatus, TicketType
from app.pricing import service_fee_cents
from app.routes.events import tier_status, upcoming_on_sale
from app.schemas import CheckoutIn, CheckoutOut

router = APIRouter(prefix='/checkout', tags=['checkout'])

# Stripe's shortest allowed checkout lifetime is 30 minutes. Our hold lasts a
# little longer, so Stripe always closes the payment page before we release stock.
STRIPE_SESSION_MINUTES = 30
HOLD_MINUTES = 32


def create_stripe_session(order: Order, event: Event, tiers: dict[int, TicketType]) -> stripe.checkout.Session:
    line_items = [
        {
            'quantity': item.quantity,
            'price_data': {
                'currency': order.currency,
                'unit_amount': item.unit_price_cents,
                'product_data': {'name': f'{event.name} · {tiers[item.ticket_type_id].name}'},
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
        cancel_url=f'{settings.site_url}/tickets?cancelled={order.id}',
    )


@router.post('', response_model=CheckoutOut)
def start_checkout(body: CheckoutIn, db: Session = Depends(get_db)):
    now = datetime.now(UTC)

    event = db.scalars(upcoming_on_sale(db).where(Event.slug == body.event_slug)).first()
    if not event:
        raise HTTPException(404, 'This event is not on sale')

    wanted: dict[int, int] = {}
    names: dict[int, list[str]] = {}
    emails: dict[int, list[str | None]] = {}
    buyer_name = body.name.strip()
    for item in body.items:
        if item.tier_id in wanted:
            raise HTTPException(400, 'Each ticket type should appear once')
        if len(item.names) > item.quantity or len(item.emails) > item.quantity:
            raise HTTPException(400, 'More names than tickets')
        wanted[item.tier_id] = item.quantity
        given = [(n or '').strip()[:200] for n in item.names]
        names[item.tier_id] = [(given[i] if i < len(given) and given[i] else buyer_name) for i in range(item.quantity)]
        emails[item.tier_id] = [
            (item.emails[i].lower() if i < len(item.emails) and item.emails[i] else None) for i in range(item.quantity)
        ]

    # Lock these tiers until we commit. A second buyer going for the same tiers
    # waits here, then sees this order's hold, so the last ticket can't sell twice.
    # (Sorted by id so two buyers always lock in the same order.)
    tiers = {
        t.id: t
        for t in db.scalars(
            select(TicketType)
            .where(TicketType.id.in_(sorted(wanted)), TicketType.event_id == event.id)
            .order_by(TicketType.id)
            .with_for_update()
        )
    }
    taken = taken_counts(db, list(tiers))

    for tier_id, qty in wanted.items():
        tier = tiers.get(tier_id)
        if not tier or not tier.active:
            raise HTTPException(400, 'That ticket type is not available')
        left = remaining(tier, taken[tier_id])
        status = tier_status(tier, left, now)
        if status == 'not_yet':
            raise HTTPException(400, f'{tier.name} is not on sale yet')
        if status == 'ended':
            raise HTTPException(400, f'{tier.name} sales have ended')
        if qty > tier.max_per_order:
            raise HTTPException(400, f'Max {tier.max_per_order} {tier.name} per order')
        if qty > left:
            raise HTTPException(
                409, f'{tier.name} is sold out' if left == 0 else f'Only {left} {tier.name} left'
            )

    subtotal = sum(tiers[tid].price_cents * qty for tid, qty in wanted.items())
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
                ticket_type_id=tid, quantity=qty, unit_price_cents=tiers[tid].price_cents,
                holder_names=names[tid],
                holder_emails=emails[tid],
            )
            for tid, qty in wanted.items()
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
