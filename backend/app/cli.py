"""Admin commands, until the admin panel exists.

Run from the backend folder:

    .venv/bin/python -m app.cli --help
    .venv/bin/python -m app.cli list

Times are typed in Toronto time (e.g. "2026-11-20 22:00") and stored as UTC.
Prices are typed in dollars (e.g. 20 or 19.99) and stored in cents.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.inventory import remaining, taken_counts
from app.models import Event, Staff, StaffRole, TicketType
from app.security import hash_password

TZ = ZoneInfo('America/Toronto')

cli = typer.Typer(no_args_is_help=True, help='Sons of Caesar ticketing admin.')


# ---------- helpers ----------


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    except ValueError:
        raise typer.BadParameter(f'"{value}" should look like "2026-11-20 22:00"')


def parse_price(value: str) -> int:
    try:
        cents = Decimal(value.replace('$', '')) * 100
    except InvalidOperation:
        raise typer.BadParameter(f'"{value}" is not a price')
    if cents < 0 or cents != cents.to_integral_value():
        raise typer.BadParameter(f'"{value}" is not a valid price')
    return int(cents)


def fmt_time(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime('%a %b %-d, %Y %-I:%M%p') if dt else '—'


def fmt_money(cents: int) -> str:
    return f'${cents / 100:,.2f}'


def get_event(db: Session, slug: str) -> Event:
    event = db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        typer.secho(f'No event with slug "{slug}". Run "list" to see them.', fg='red')
        raise typer.Exit(1)
    return event


def get_tier(db: Session, tier_id: int) -> TicketType:
    tier = db.get(TicketType, tier_id)
    if not tier:
        typer.secho(f'No tier with id {tier_id}. Run "list" to see them.', fg='red')
        raise typer.Exit(1)
    return tier


# ---------- events ----------


@cli.command()
def create_event(
    slug: str = typer.Option(..., help='Short id used in links, e.g. "vol-iii"'),
    name: str = typer.Option(..., help='e.g. "VOL III"'),
    starts_at: str = typer.Option(..., help='Toronto time, "2026-11-20 22:00"'),
    ends_at: str = typer.Option(None, help='Toronto time, optional'),
    venue: str = typer.Option(None),
    description: str = typer.Option(None),
    poster_url: str = typer.Option(None),
):
    """Create an event (not on sale until you run "on-sale")."""
    with SessionLocal() as db:
        if db.scalar(select(Event).where(Event.slug == slug)):
            typer.secho(f'An event with slug "{slug}" already exists.', fg='red')
            raise typer.Exit(1)
        event = Event(
            slug=slug,
            name=name,
            starts_at=parse_time(starts_at),
            ends_at=parse_time(ends_at),
            venue=venue,
            description=description,
            poster_url=poster_url,
        )
        db.add(event)
        db.commit()
        typer.secho(f'Created event "{name}" ({slug}), {fmt_time(event.starts_at)}', fg='green')


@cli.command()
def on_sale(slug: str, off: bool = typer.Option(False, '--off', help='Take it off sale instead')):
    """Put an event on sale (or --off to stop sales)."""
    with SessionLocal() as db:
        event = get_event(db, slug)
        event.on_sale = not off
        db.commit()
        typer.secho(f'{event.name} is now {"OFF sale" if off else "ON sale"}', fg='yellow' if off else 'green')


# ---------- tiers ----------


@cli.command()
def add_tier(
    event_slug: str,
    name: str = typer.Option(..., help='e.g. "Early Bird"'),
    price: str = typer.Option(..., help='Dollars before the service fee, e.g. 20'),
    quantity: int = typer.Option(..., help='How many are available'),
    max_per_order: int = typer.Option(4),
    sales_start: str = typer.Option(None, help='Toronto time, optional'),
    sales_end: str = typer.Option(None, help='Toronto time, optional'),
    description: str = typer.Option(None),
):
    """Add a ticket tier to an event."""
    with SessionLocal() as db:
        event = get_event(db, event_slug)
        tier = TicketType(
            event=event,
            name=name,
            price_cents=parse_price(price),
            quantity=quantity,
            max_per_order=max_per_order,
            sales_start=parse_time(sales_start),
            sales_end=parse_time(sales_end),
            description=description,
            sort_order=len(event.ticket_types),
        )
        db.add(tier)
        db.commit()
        typer.secho(
            f'Added "{name}" to {event.name}: {fmt_money(tier.price_cents)} x {quantity} (tier id {tier.id})',
            fg='green',
        )


@cli.command()
def edit_tier(
    tier_id: int,
    name: str = typer.Option(None),
    price: str = typer.Option(None),
    quantity: int = typer.Option(None),
    max_per_order: int = typer.Option(None),
    sales_start: str = typer.Option(None, help='Toronto time, or "none" to clear'),
    sales_end: str = typer.Option(None, help='Toronto time, or "none" to clear'),
    hide: bool = typer.Option(None, '--hide/--show', help='Hide a tier from sale without deleting it'),
):
    """Change a tier. Only the options you pass are changed."""
    with SessionLocal() as db:
        tier = get_tier(db, tier_id)
        if name is not None:
            tier.name = name
        if price is not None:
            tier.price_cents = parse_price(price)
        if quantity is not None:
            taken = taken_counts(db, [tier.id])[tier.id]
            if quantity < taken:
                typer.secho(f'{taken} are already sold or held; quantity can\'t go below that.', fg='red')
                raise typer.Exit(1)
            tier.quantity = quantity
        if max_per_order is not None:
            tier.max_per_order = max_per_order
        if sales_start is not None:
            tier.sales_start = None if sales_start == 'none' else parse_time(sales_start)
        if sales_end is not None:
            tier.sales_end = None if sales_end == 'none' else parse_time(sales_end)
        if hide is not None:
            tier.active = not hide
        db.commit()
        typer.secho(f'Updated tier {tier.id} ({tier.name})', fg='green')


# ---------- overview ----------


@cli.command('list')
def list_events():
    """Show every event with its tiers and how many are left."""
    with SessionLocal() as db:
        events = db.scalars(select(Event).order_by(Event.starts_at)).all()
        if not events:
            typer.echo('No events yet. Create one with "create-event".')
            return
        for event in events:
            status = typer.style('ON SALE', fg='green') if event.on_sale else typer.style('not on sale', fg='yellow')
            typer.echo(f'\n{typer.style(event.name, bold=True)}  [{event.slug}]  {status}')
            typer.echo(f'  {fmt_time(event.starts_at)}' + (f' @ {event.venue}' if event.venue else ''))
            taken = taken_counts(db, [t.id for t in event.ticket_types])
            for t in event.ticket_types:
                window = ''
                if t.sales_start or t.sales_end:
                    window = f'  sales {fmt_time(t.sales_start)} → {fmt_time(t.sales_end)}'
                hidden = typer.style('  (hidden)', fg='yellow') if not t.active else ''
                typer.echo(
                    f'  #{t.id:<3} {t.name:<14} {fmt_money(t.price_cents):>8}  '
                    f'{taken[t.id]:>3} taken / {t.quantity:<4} ({remaining(t, taken[t.id])} left)  '
                    f'max {t.max_per_order}/order{window}{hidden}'
                )
            if not event.ticket_types:
                typer.echo('  (no tiers yet; add one with "add-tier")')
        typer.echo()


# ---------- staff ----------


@cli.command()
def add_staff(
    email: str = typer.Option(...),
    name: str = typer.Option(...),
    role: StaffRole = typer.Option(StaffRole.door, help='admin = everything, door = scan + lookup only'),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    """Create a staff login. You'll be asked for the password (hidden)."""
    if len(password) < 10:
        typer.secho('Use at least 10 characters.', fg='red')
        raise typer.Exit(1)
    with SessionLocal() as db:
        email = email.strip().lower()
        if db.scalar(select(Staff).where(Staff.email == email)):
            typer.secho(f'{email} already has a login.', fg='red')
            raise typer.Exit(1)
        db.add(Staff(email=email, name=name, role=role, password_hash=hash_password(password)))
        db.commit()
        typer.secho(f'Added {name} <{email}> as {role.value}', fg='green')


@cli.command('staff')
def list_staff():
    """Show staff logins."""
    with SessionLocal() as db:
        for s in db.scalars(select(Staff).order_by(Staff.created_at)):
            state = '' if s.active else typer.style(' (disabled)', fg='yellow')
            typer.echo(f'  {s.name:<20} {s.email:<32} {s.role.value}{state}')


if __name__ == '__main__':
    cli()
