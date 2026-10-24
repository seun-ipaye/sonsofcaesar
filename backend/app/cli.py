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


# ---------- orders ----------


@cli.command()
def sync_order(order_id: str):
    """Ask Stripe whether an order was paid, and issue its tickets if so.
    Use it if a buyer says they paid but got nothing (e.g. a missed webhook)."""
    import stripe

    from app.config import settings
    from app.fulfillment import fulfill_order
    from app.models import Order

    with SessionLocal() as db:
        order = db.get(Order, order_id)
        if not order or not order.stripe_session_id:
            typer.secho('No such order (or it never reached Stripe).', fg='red')
            raise typer.Exit(1)
        session = stripe.checkout.Session.retrieve(order.stripe_session_id, api_key=settings.stripe_secret_key)
        typer.echo(f'Stripe says: {session.payment_status} ({session.status}); our status: {order.status.value}')
        if session.payment_status == 'paid':
            order = fulfill_order(db, str(order.id), session.payment_intent, session.amount_total)
            typer.secho(f'Order is {order.status.value} with {len(order.tickets)} tickets', fg='green')
            from app.emails import send_tickets_email

            if send_tickets_email(db, str(order.id)):
                typer.echo('Tickets email sent.')


@cli.command()
def wipe_test_orders(yes: bool = typer.Option(False, '--yes', help='Skip the confirmation (for scripts/tests)')):
    """Delete every TEST order and ticket (sandbox purchases), keeping events,
    tiers and staff. Refuses if any order was paid through live Stripe."""
    from sqlalchemy import delete, func

    from app.models import Order, Ticket

    with SessionLocal() as db:
        live = db.scalar(select(func.count()).where(Order.stripe_session_id.like('cs_live_%')))
        if live:
            typer.secho(
                f'Refusing: {live} order(s) went through LIVE Stripe. Real sales are never wiped.', fg='red'
            )
            raise typer.Exit(1)

        orders = db.scalar(select(func.count()).select_from(Order))
        tickets = db.scalar(select(func.count()).select_from(Ticket))
        checked_in = db.scalar(select(func.count()).where(Ticket.checked_in_at.is_not(None)))
        if not orders:
            typer.echo('Nothing to wipe: there are no orders.')
            return

        typer.echo(f'This deletes {orders} test orders and {tickets} tickets ({checked_in} checked in).')
        typer.echo('Events, tiers and staff logins are kept.')
        if not yes and typer.prompt('Type WIPE to confirm') != 'WIPE':
            typer.echo('Cancelled. Nothing was deleted.')
            raise typer.Exit(1)

        db.execute(delete(Ticket))
        db.execute(delete(Order))  # order lines go with their orders
        db.commit()
        typer.secho(f'Wiped {orders} orders and {tickets} tickets.', fg='green')


@cli.command()
def resend_email(order_id: str):
    """Send the tickets email again (e.g. buyer can't find it, or it failed)."""
    from app.emails import send_tickets_email

    with SessionLocal() as db:
        if send_tickets_email(db, order_id, force=True):
            typer.secho('Sent.', fg='green')
        else:
            typer.secho('Not sent: order not found or not paid.', fg='red')
            raise typer.Exit(1)


# ---------- backups ----------


@cli.command()
def backup(out: str = typer.Option(None, help='Save to this file instead of the backup bucket')):
    """Back up the whole database (to the private R2 bucket, or --out a file)."""
    from app import backup as b

    data, manifest = b.dump()
    rows = sum(manifest['tables'].values())
    if out:
        with open(out, 'wb') as f:
            f.write(data)
        typer.secho(f'Saved {out} ({len(data) // 1024 + 1} KB, {rows} rows)', fg='green')
        return
    key = b.upload(data, manifest)
    removed = b.prune()
    typer.secho(f'Backed up to {key} ({len(data) // 1024 + 1} KB, {rows} rows); removed {removed} old', fg='green')


@cli.command()
def list_backups():
    """Show backups in the bucket, newest first."""
    from app import backup as b

    for o in b.list_backups():
        typer.echo(f"  {o['key']:<32} {o['size'] // 1024 + 1:>6} KB")


@cli.command()
def restore_backup(
    into: str = typer.Option(..., help='URL of a NEW, EMPTY database to restore into'),
    key: str = typer.Option(None, help='Backup in the bucket, e.g. db/2026-10-15T0900Z.zip (default: newest)'),
    file: str = typer.Option(None, help='Or a local backup file'),
):
    """Restore a backup into an empty database. Never touches the live one."""
    from app import backup as b

    if file:
        with open(file, 'rb') as f:
            data = f.read()
    else:
        key = key or b.list_backups()[0]['key']
        data = b.download(key)
    manifest = b.restore(data, into)
    typer.secho(
        f"Restored backup from {manifest['created_at']} ({sum(manifest['tables'].values())} rows). "
        'Point DATABASE_URL at that database to use it.',
        fg='green',
    )


# ---------- staff ----------


@cli.command()
def add_staff(
    email: str = typer.Option(...),
    name: str = typer.Option(...),
    role: StaffRole = typer.Option(
        StaffRole.door,
        help='admin = everything, door = scan + lookup only, partner = view one event (use --event)',
    ),
    event: list[str] = typer.Option([], '--event', help='Partners: an event they can see (repeat for more)'),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    """Create a staff login. You'll be asked for the password (hidden)."""
    if len(password) < 10:
        typer.secho('Use at least 10 characters.', fg='red')
        raise typer.Exit(1)
    if role == StaffRole.partner and not event:
        typer.secho('Partners need at least one --event <link name>.', fg='red')
        raise typer.Exit(1)
    with SessionLocal() as db:
        email = email.strip().lower()
        if db.scalar(select(Staff).where(Staff.email == email)):
            typer.secho(f'{email} already has a login.', fg='red')
            raise typer.Exit(1)
        events = [get_event(db, slug) for slug in event]  # stops if a link name is wrong
        staff = Staff(email=email, name=name, role=role, password_hash=hash_password(password))
        db.add(staff)
        db.flush()
        if role == StaffRole.partner:
            from app.models import StaffEvent

            db.add_all([StaffEvent(staff_id=staff.id, event_id=e.id) for e in events])
        db.commit()
        extra = f" for {', '.join(e.name for e in events)}" if role == StaffRole.partner else ''
        typer.secho(f'Added {name} <{email}> as {role.value}{extra}', fg='green')


def _partner(db: Session, email: str) -> Staff:
    staff = db.scalar(select(Staff).where(Staff.email == email.strip().lower()))
    if not staff:
        typer.secho(f'No staff with email {email}', fg='red')
        raise typer.Exit(1)
    if staff.role != StaffRole.partner:
        typer.secho(f'{staff.name} is {staff.role.value}, not a partner.', fg='red')
        raise typer.Exit(1)
    return staff


@cli.command()
def grant_event(email: str, event_slug: str):
    """Let a partner see another event."""
    from app.models import StaffEvent

    with SessionLocal() as db:
        staff = _partner(db, email)
        event = get_event(db, event_slug)
        if not db.get(StaffEvent, (staff.id, event.id)):
            db.add(StaffEvent(staff_id=staff.id, event_id=event.id))
            db.commit()
        typer.secho(f'{staff.name} can see {event.name}', fg='green')


@cli.command()
def revoke_event(email: str, event_slug: str):
    """Stop a partner seeing an event (instantly)."""
    from app.models import StaffEvent

    with SessionLocal() as db:
        staff = _partner(db, email)
        event = get_event(db, event_slug)
        row = db.get(StaffEvent, (staff.id, event.id))
        if row:
            db.delete(row)
            db.commit()
        typer.secho(f'{staff.name} can no longer see {event.name}', fg='green')


@cli.command()
def set_password(
    email: str,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
):
    """Reset a staff password (logs them out everywhere)."""
    from app.auth import end_all_sessions

    if len(password) < 10:
        typer.secho('Use at least 10 characters.', fg='red')
        raise typer.Exit(1)
    with SessionLocal() as db:
        staff = db.scalar(select(Staff).where(Staff.email == email.strip().lower()))
        if not staff:
            typer.secho(f'No staff with email {email}', fg='red')
            raise typer.Exit(1)
        staff.password_hash = hash_password(password)
        end_all_sessions(db, staff.id)
        db.commit()
        typer.secho(f'Password updated for {staff.name}; they\'ve been logged out everywhere.', fg='green')


@cli.command()
def disable_staff(email: str, enable: bool = typer.Option(False, '--enable', help='Re-enable instead')):
    """Disable a staff login (instantly logs them out), or --enable it again."""
    from app.auth import end_all_sessions

    with SessionLocal() as db:
        staff = db.scalar(select(Staff).where(Staff.email == email.strip().lower()))
        if not staff:
            typer.secho(f'No staff with email {email}', fg='red')
            raise typer.Exit(1)
        staff.active = enable
        if not enable:
            end_all_sessions(db, staff.id)
        db.commit()
        typer.secho(f'{staff.name} is now {"enabled" if enable else "disabled and logged out"}', fg='green')


@cli.command('staff')
def list_staff():
    """Show staff logins."""
    with SessionLocal() as db:
        for s in db.scalars(select(Staff).order_by(Staff.created_at)):
            state = '' if s.active else typer.style(' (disabled)', fg='yellow')
            events = ''
            if s.role == StaffRole.partner:
                from app.models import StaffEvent

                names = db.scalars(
                    select(Event.name).join(StaffEvent, StaffEvent.event_id == Event.id).where(StaffEvent.staff_id == s.id)
                ).all()
                events = f"  sees: {', '.join(names) or 'nothing yet'}"
            typer.echo(f'  {s.name:<20} {s.email:<32} {s.role.value}{state}{events}')


if __name__ == '__main__':
    cli()
