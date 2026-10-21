import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.routes import admin, admin_combos, auth, checkin, checkout, combos, events, tickets, webhooks

# Show our own log lines (payments, refunds) in the terminal and Railway's logs.
# Attached to our "app" logger directly, since uvicorn sets up logging its own way.
_log = logging.getLogger('app')
_log.setLevel(logging.INFO)
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter('%(levelname)s:     %(name)s: %(message)s'))
    _log.addHandler(_handler)
    _log.propagate = False  # don't print each line twice

ALEMBIC_INI = Path(__file__).resolve().parent.parent / 'alembic.ini'


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bring the database up to date on startup. Doesn't depend on the host's
    # deploy settings, and does nothing if it's already current.
    command.upgrade(Config(str(ALEMBIC_INI)), 'head')
    yield


app = FastAPI(title='Sons of Caesar API', lifespan=lifespan)

# Lets the website (a different address) call the API from the browser,
# including sending the staff login cookie
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(events.router)
app.include_router(checkout.router)
app.include_router(webhooks.router)
app.include_router(tickets.router)
app.include_router(auth.router)
app.include_router(checkin.router)
app.include_router(admin.router)
app.include_router(combos.router)
app.include_router(admin_combos.router)


@app.get('/health')
def health():
    """Server is up, plus whether the database is reachable and migrated.
    Shows no secrets: just a yes/no, the migration version and table names."""
    db: dict = {'connected': False}
    try:
        with engine.connect() as conn:
            db['connected'] = True
            db['tables'] = sorted(
                conn.execute(
                    text("select table_name from information_schema.tables where table_schema = 'public'")
                ).scalars()
            )
            db['migration'] = (
                conn.execute(text('select version_num from alembic_version')).scalar()
                if 'alembic_version' in db['tables']
                else None
            )
    except Exception as e:
        db['error'] = type(e).__name__
    # Configuration check without revealing any secret: just what's set, and the Stripe mode
    key = settings.stripe_secret_key
    config = {
        'stripe': 'live' if settings.stripe_is_live else ('test' if key.startswith(('sk_test_', 'rk_test_')) else 'missing'),
        'stripe_webhook_secret': settings.stripe_webhook_secret.startswith('whsec_'),
        'email': settings.resend_api_key.startswith('re_'),
        'site_url': settings.site_url,
        'api_url': settings.api_url,
        'test_payments_allowed': settings.test_payments_allowed,
    }
    return {'status': 'ok', 'db': db, 'config': config}
