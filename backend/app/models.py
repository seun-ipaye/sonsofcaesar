"""Database tables.

Money is always stored in cents (integers) to avoid rounding errors: $20.00 -> 2000.
Times are stored with time zones (UTC in the database).
"""

import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(cls: type[enum.Enum]) -> Enum:
    # Stored as text with a check constraint, so adding a value later is an easy migration
    return Enum(cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


def new_ticket_code() -> str:
    """Random, unguessable code that goes in the QR (~128 bits)."""
    return secrets.token_urlsafe(16)


class OrderStatus(str, enum.Enum):
    pending = 'pending'  # checkout started; tickets held until expires_at
    paid = 'paid'
    expired = 'expired'  # never paid; hold released
    refunded = 'refunded'


class TicketStatus(str, enum.Enum):
    valid = 'valid'
    void = 'void'  # refunded or cancelled; rejected at the door


class StaffRole(str, enum.Enum):
    admin = 'admin'  # everything
    door = 'door'  # scan + lookup only


SECRET_VENUE_TEXT = 'Address sent after purchase'


class Event(Base):
    __tablename__ = 'events'

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(String(300))
    poster_url: Mapped[str | None] = mapped_column(String(500))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Listed on /tickets (people can see it). Buying also waits for sales_start, if set.
    on_sale: Mapped[bool] = mapped_column(default=False)
    sales_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Secret address (e.g. a house party): the public page says "Address sent after
    # purchase"; only valid ticket holders see `address`, on their tickets and emails.
    secret_address: Mapped[bool] = mapped_column(default=False, server_default='false')
    address: Mapped[str | None] = mapped_column(String(300))
    address_emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket_types: Mapped[list['TicketType']] = relationship(
        back_populates='event', order_by='TicketType.sort_order'
    )


class TicketType(Base):
    """A tier, e.g. Early Bird / GA / VIP."""

    __tablename__ = 'ticket_types'
    __table_args__ = (
        CheckConstraint('price_cents >= 0', name='price_not_negative'),
        CheckConstraint('quantity >= 0', name='quantity_not_negative'),
        CheckConstraint('max_per_order >= 1', name='max_per_order_positive'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey('events.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)  # total available for this tier
    max_per_order: Mapped[int] = mapped_column(Integer, default=4)
    sales_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(default=True)

    event: Mapped[Event] = relationship(back_populates='ticket_types')


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int] = mapped_column(ForeignKey('events.id'), index=True)
    buyer_name: Mapped[str] = mapped_column(String(200))
    buyer_email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.pending, index=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    subtotal_cents: Mapped[int] = mapped_column(Integer)  # tickets only
    fee_cents: Mapped[int] = mapped_column(Integer)  # service fee added on top
    total_cents: Mapped[int] = mapped_column(Integer)  # what the buyer paid
    currency: Mapped[str] = mapped_column(String(3), default='cad')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # end of the stock hold
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # tickets email sent
    # "Didn't get your tickets?" resends, limited to stop the form being used for spam
    resend_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    last_resent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped[Event] = relationship()
    items: Mapped[list['OrderItem']] = relationship(back_populates='order', cascade='all, delete-orphan')
    tickets: Mapped[list['Ticket']] = relationship(back_populates='order')


class OrderItem(Base):
    """How many of which tier an order is for (and at what price at the time)."""

    __tablename__ = 'order_items'
    __table_args__ = (CheckConstraint('quantity >= 1', name='quantity_positive'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey('ticket_types.id'), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    # Name for each ticket in this line, in order (kept until payment creates the tickets)
    holder_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Optional email per ticket ("send it to them too"), same order; None = don't send
    holder_emails: Mapped[list[str | None]] = mapped_column(JSON, default=list, server_default='[]')

    order: Mapped[Order] = relationship(back_populates='items')
    ticket_type: Mapped[TicketType] = relationship()


class Ticket(Base):
    """One admission. The code is what's in the QR."""

    __tablename__ = 'tickets'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, default=new_ticket_code)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('orders.id'), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey('events.id'), index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey('ticket_types.id'), index=True)
    holder_name: Mapped[str] = mapped_column(String(200))
    # Set when the buyer sent this ticket to a friend; they get their own email
    holder_email: Mapped[str | None] = mapped_column(String(320))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # friend's email sent
    status: Mapped[TicketStatus] = mapped_column(_enum(TicketStatus), default=TicketStatus.valid)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by_id: Mapped[int | None] = mapped_column(ForeignKey('staff.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates='tickets')
    event: Mapped[Event] = relationship()
    ticket_type: Mapped[TicketType] = relationship()
    checked_in_by: Mapped['Staff | None'] = relationship()


class Staff(Base):
    __tablename__ = 'staff'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[StaffRole] = mapped_column(_enum(StaffRole), default=StaffRole.door)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffSession(Base):
    """A logged-in device. The browser holds a random token in a cookie; we store
    only its hash, so a database leak can't be used to log in."""

    __tablename__ = 'staff_sessions'

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey('staff.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    staff: Mapped[Staff] = relationship()


class LoginFailure(Base):
    """Wrong-password attempts, for locking out password guessing."""

    __tablename__ = 'login_failures'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


def public_venue(event: Event) -> str | None:
    """What the public sees as the venue: never the secret address."""
    return SECRET_VENUE_TEXT if event.secret_address else event.venue
