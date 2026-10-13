"""Shapes of what the API sends back (and, later, accepts)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

TierStatus = Literal['on_sale', 'sold_out', 'not_yet', 'ended']


class TierOut(BaseModel):
    id: int
    name: str
    description: str | None
    price_cents: int
    # Fee if you buy just one; the real fee is worked out on the whole order
    fee_for_one_cents: int
    max_per_order: int
    remaining: int
    status: TierStatus
    sales_start: datetime | None
    sales_end: datetime | None


class EventOut(BaseModel):
    slug: str
    name: str
    description: str | None
    venue: str | None
    poster_url: str | None
    starts_at: datetime
    ends_at: datetime | None
    currency: str = 'cad'
    tiers: list[TierOut]


class CheckoutItem(BaseModel):
    tier_id: int
    quantity: int = Field(ge=1, le=20)
    # One name per ticket; missing/blank ones fall back to the buyer's name
    names: list[str | None] = Field(default_factory=list, max_length=20)
    # Optional per ticket: also email that ticket to this address (null = don't)
    emails: list[EmailStr | None] = Field(default_factory=list, max_length=20)


class CheckoutIn(BaseModel):
    event_slug: str
    items: list[CheckoutItem] = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr


class CheckoutOut(BaseModel):
    order_id: str
    checkout_url: str


class TicketOut(BaseModel):
    code: str
    tier: str
    holder_name: str
    status: str  # valid / void
    checked_in_at: datetime | None


class TicketEventOut(BaseModel):
    name: str
    venue: str | None
    starts_at: datetime
    ends_at: datetime | None


class TicketPageOut(TicketOut):
    event: TicketEventOut


class OrderPageOut(BaseModel):
    id: str
    status: str  # pending / paid / expired / refunded
    buyer_name: str
    email_hint: str  # masked, e.g. se•••@gmail.com
    resends_left: int
    total_cents: int
    event: TicketEventOut
    tickets: list[TicketOut]


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class StaffOut(BaseModel):
    name: str
    email: str
    role: str


class ResendIn(BaseModel):
    email: EmailStr


class CheckinIn(BaseModel):
    event_slug: str
    code: str = Field(max_length=200)


class CheckinTicket(BaseModel):
    code: str
    holder_name: str
    tier: str
    status: str
    checked_in_at: datetime | None
    checked_in_by: str | None
    buyer_email_hint: str


class CheckinResult(BaseModel):
    # ok = let them in; already = used before; void = refunded;
    # wrong_event = ticket for another event; not_found = not one of ours
    result: Literal['ok', 'already', 'void', 'wrong_event', 'not_found']
    ticket: CheckinTicket | None = None
    other_event: str | None = None


class CheckinStats(BaseModel):
    checked_in: int
    total: int


class StaffEventOut(BaseModel):
    slug: str
    name: str
    starts_at: datetime


# ---------- admin ----------


class AdminTierOut(BaseModel):
    id: int
    name: str
    description: str | None
    price_cents: int
    quantity: int
    max_per_order: int
    sales_start: datetime | None
    sales_end: datetime | None
    active: bool
    sold: int  # valid tickets issued
    held: int  # in checkouts happening right now
    checked_in: int
    revenue_cents: int  # ticket price x sold (what you keep)


class SalesDay(BaseModel):
    day: str  # YYYY-MM-DD, Toronto time
    tickets: int
    revenue_cents: int


class AdminEventOut(BaseModel):
    slug: str
    name: str
    description: str | None
    venue: str | None
    poster_url: str | None
    starts_at: datetime
    ends_at: datetime | None
    on_sale: bool
    tickets_sold: int
    capacity: int
    checked_in: int
    orders: int
    revenue_cents: int  # ticket sales you keep
    fees_cents: int  # service fees collected (cover Stripe)
    refunded_orders: int
    tiers: list[AdminTierOut]
    sales_by_day: list[SalesDay]


class AdminEventListItem(BaseModel):
    slug: str
    name: str
    starts_at: datetime
    on_sale: bool
    tickets_sold: int
    capacity: int


class AttendeeOut(BaseModel):
    code: str
    holder_name: str
    holder_email: str | None
    tier: str
    status: str
    checked_in_at: datetime | None
    checked_in_by: str | None
    order_id: str
    buyer_name: str
    buyer_email: str
    paid_at: datetime | None


class EventIn(BaseModel):
    slug: str = Field(pattern=r'^[a-z0-9]+(-[a-z0-9]+)*$', max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    venue: str | None = None
    poster_url: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None


class EventPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    venue: str | None = None
    poster_url: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    on_sale: bool | None = None


class TierIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    price_cents: int = Field(ge=0)
    quantity: int = Field(ge=0)
    max_per_order: int = Field(default=4, ge=1, le=20)
    sales_start: datetime | None = None
    sales_end: datetime | None = None


class TierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=0)
    max_per_order: int | None = Field(default=None, ge=1, le=20)
    sales_start: datetime | None = None
    sales_end: datetime | None = None
    active: bool | None = None
