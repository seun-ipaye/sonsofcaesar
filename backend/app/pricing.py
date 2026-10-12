"""Service fee: added on top so that after Stripe's cut, we keep the full ticket price.

Stripe (Canadian cards) takes 2.9% + 30¢ of the TOTAL charged, so we solve
    total - (total * 2.9% + 30¢) = subtotal
    total = (subtotal + 30¢) / (1 - 2.9%)
and round up to the next cent so we're never short.

International cards cost Stripe a bit more; on those we absorb the difference.
"""

import math

STRIPE_PERCENT = 0.029
STRIPE_FIXED_CENTS = 30


def service_fee_cents(subtotal_cents: int) -> int:
    if subtotal_cents <= 0:
        return 0  # free tickets: no payment, no fee
    total = math.ceil((subtotal_cents + STRIPE_FIXED_CENTS) / (1 - STRIPE_PERCENT))
    return total - subtotal_cents
