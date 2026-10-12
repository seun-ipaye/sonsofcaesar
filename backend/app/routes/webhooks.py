"""Stripe calls this when things happen to a payment.

Every request is checked against the webhook signing secret, so nobody can fake
a "payment succeeded" message to get free tickets.
"""

import logging

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.emails import send_tickets_email
from app.fulfillment import expire_order, fulfill_order, refund_order

router = APIRouter(prefix='/webhooks', tags=['webhooks'])
log = logging.getLogger(__name__)


def email_tickets(order_id: str) -> None:
    # Runs after we've answered Stripe, so a slow or failed email never delays
    # or blocks the payment. If it fails, resend with: app.cli resend-email <order>
    try:
        with SessionLocal() as db:
            send_tickets_email(db, order_id)
    except Exception:
        log.exception('Could not email tickets for order %s', order_id)


@router.post('/stripe')
async def stripe_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, request.headers.get('stripe-signature', ''), settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, 'Invalid signature')

    obj = event['data']['object']
    kind = event['type']

    if kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        # "completed" can also mean "waiting on a slow payment method"; only act once it's paid
        if obj.get('payment_status') == 'paid':
            order = fulfill_order(
                db,
                order_id=obj.get('client_reference_id') or obj['metadata']['order_id'],
                payment_intent_id=obj.get('payment_intent'),
                amount_paid=obj.get('amount_total'),
            )
            if order and order.status.value == 'paid' and not order.emailed_at:
                background.add_task(email_tickets, str(order.id))
    elif kind in ('checkout.session.expired', 'checkout.session.async_payment_failed'):
        expire_order(db, obj.get('client_reference_id') or obj['metadata']['order_id'])
    elif kind == 'charge.refunded':
        refund_order(db, obj['payment_intent'], fully_refunded=obj['amount_refunded'] >= obj['amount'])
    else:
        log.info('Ignoring Stripe event %s', kind)

    # 200 tells Stripe "got it"; anything else makes Stripe retry for days
    return {'received': True}
