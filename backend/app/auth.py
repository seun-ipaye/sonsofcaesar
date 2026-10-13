"""Staff login: database-backed sessions in a secure cookie.

- Door staff stay logged in 12 hours (one night), admins 7 days.
- Disabling a staff member or logging out ends the session instantly.
- 10 wrong passwords for an email within 15 minutes locks that email for 15 minutes.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import LoginFailure, Staff, StaffRole, StaffSession
from app.security import hash_password, verify_password

COOKIE = 'soc_session'
SESSION_LENGTH = {StaffRole.door: timedelta(hours=12), StaffRole.admin: timedelta(days=7)}
MAX_FAILURES = 10
LOCKOUT = timedelta(minutes=15)

# Checked when the email doesn't exist, so a wrong email takes as long as a wrong
# password (otherwise response times would reveal which emails have accounts)
_DUMMY_HASH = hash_password('not-a-real-password')


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cookie_secure() -> bool:
    # Real HTTPS in production; plain http on localhost while developing
    return settings.api_url.startswith('https://')


def login(db: Session, response: Response, email: str, password: str, user_agent: str | None) -> Staff:
    email = email.strip().lower()
    now = datetime.now(UTC)

    recent_failures = db.scalar(
        select(func.count()).select_from(LoginFailure).where(LoginFailure.email == email, LoginFailure.at > now - LOCKOUT)
    )
    if recent_failures >= MAX_FAILURES:
        raise HTTPException(429, 'Too many attempts. Try again in 15 minutes.')

    staff = db.scalar(select(Staff).where(Staff.email == email))
    ok = verify_password(staff.password_hash if staff else _DUMMY_HASH, password)
    if not (staff and ok and staff.active):
        db.add(LoginFailure(email=email))
        db.commit()
        raise HTTPException(401, 'Wrong email or password')

    token = secrets.token_urlsafe(32)
    length = SESSION_LENGTH[staff.role]
    db.add(
        StaffSession(
            token_hash=_hash_token(token),
            staff_id=staff.id,
            expires_at=now + length,
            user_agent=(user_agent or '')[:300],
        )
    )
    # A successful login clears that email's failures and tidies expired sessions
    db.execute(delete(LoginFailure).where(LoginFailure.email == email))
    db.execute(delete(StaffSession).where(StaffSession.expires_at < now))
    db.commit()

    response.set_cookie(
        COOKIE,
        token,
        max_age=int(length.total_seconds()),
        httponly=True,
        secure=_cookie_secure(),
        samesite='lax',
        path='/',
    )
    return staff


def logout(db: Session, response: Response, token: str | None) -> None:
    if token:
        db.execute(delete(StaffSession).where(StaffSession.token_hash == _hash_token(token)))
        db.commit()
    response.delete_cookie(COOKIE, path='/', secure=_cookie_secure(), httponly=True, samesite='lax')


def end_all_sessions(db: Session, staff_id: int) -> None:
    db.execute(delete(StaffSession).where(StaffSession.staff_id == staff_id))


def current_staff(
    request: Request,
    db: Session = Depends(get_db),
    soc_session: str | None = Cookie(default=None),
) -> Staff:
    """FastAPI dependency: the logged-in staff member, or 401."""
    if not soc_session:
        raise HTTPException(401, 'Not logged in')
    session = db.scalar(select(StaffSession).where(StaffSession.token_hash == _hash_token(soc_session)))
    if not session or session.expires_at < datetime.now(UTC) or not session.staff.active:
        raise HTTPException(401, 'Not logged in')
    return session.staff


def require_admin(staff: Staff = Depends(current_staff)) -> Staff:
    if staff.role != StaffRole.admin:
        raise HTTPException(403, 'Admins only')
    return staff
