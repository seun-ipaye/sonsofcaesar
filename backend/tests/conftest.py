import os

# Tests always use the throwaway test database, never dev or production
os.environ['DATABASE_URL'] = 'postgresql+psycopg://localhost/sonsofcaesar_test'

import pytest  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_tables():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """Tests never send real email: capture what would have been sent."""
    import resend

    sent = []
    monkeypatch.setattr(resend.Emails, 'send', lambda params: sent.append(params) or {'id': 'test'})
    return sent
