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
    names: list[str] = Field(default_factory=list, max_length=20)


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
