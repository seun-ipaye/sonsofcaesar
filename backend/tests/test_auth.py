from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth import require_admin
from app.main import app
from app.models import LoginFailure, Staff, StaffRole, StaffSession
from app.security import hash_password


# A throwaway admin-only route, to test the role check
@app.get('/_test/admin-only')
def _admin_only(staff=Depends(require_admin)):
    return {'hi': staff.name}


@pytest.fixture
def staff(db):
    admin = Staff(email='boss@example.com', name='Boss', role=StaffRole.admin, password_hash=hash_password('admin-pass-123'))
    door = Staff(email='door@example.com', name='Tolu', role=StaffRole.door, password_hash=hash_password('door-pass-123'))
    db.add_all([admin, door])
    db.commit()
    return admin, door


def login(client, email, password):
    return client.post('/auth/login', json={'email': email, 'password': password})


def test_login_me_logout(db, staff):
    c = TestClient(app)
    assert c.get('/auth/me').status_code == 401

    r = login(c, ' Boss@Example.com ', 'admin-pass-123')  # email is case/space-insensitive
    assert r.status_code == 200 and r.json()['role'] == 'admin'
    cookie = r.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Max-Age=604800' in cookie  # 7 days

    assert c.get('/auth/me').json()['name'] == 'Boss'
    # The database holds a hash, never the token itself
    token = c.cookies.get('soc_session')
    assert db.query(StaffSession).one().token_hash != token

    c.post('/auth/logout')
    assert c.get('/auth/me').status_code == 401
    assert db.query(StaffSession).count() == 0


def test_door_staff_session_is_12_hours(db, staff):
    r = login(TestClient(app), 'door@example.com', 'door-pass-123')
    assert 'Max-Age=43200' in r.headers['set-cookie']


def test_wrong_password_and_unknown_email_look_the_same(db, staff):
    c = TestClient(app)
    a = login(c, 'boss@example.com', 'nope')
    b = login(c, 'nobody@example.com', 'nope')
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {'detail': 'Wrong email or password'}


def test_lockout_after_10_failures(db, staff):
    c = TestClient(app)
    for _ in range(10):
        assert login(c, 'boss@example.com', 'wrong').status_code == 401
    # Even the right password is refused during the lockout
    assert login(c, 'boss@example.com', 'admin-pass-123').status_code == 429
    # ...which ends after 15 minutes
    for f in db.query(LoginFailure):
        f.at = datetime.now(UTC) - timedelta(minutes=16)
    db.commit()
    assert login(c, 'boss@example.com', 'admin-pass-123').status_code == 200


def test_disabling_staff_kicks_them_out(db, staff):
    c = TestClient(app)
    login(c, 'door@example.com', 'door-pass-123')
    assert c.get('/auth/me').status_code == 200
    door = db.query(Staff).filter_by(email='door@example.com').one()
    door.active = False
    db.commit()
    assert c.get('/auth/me').status_code == 401
    assert login(c, 'door@example.com', 'door-pass-123').status_code == 401


def test_expired_session_rejected(db, staff):
    c = TestClient(app)
    login(c, 'boss@example.com', 'admin-pass-123')
    s = db.query(StaffSession).one()
    s.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert c.get('/auth/me').status_code == 401


def test_admin_only_routes(db, staff):
    door, boss = TestClient(app), TestClient(app)
    login(door, 'door@example.com', 'door-pass-123')
    login(boss, 'boss@example.com', 'admin-pass-123')
    assert door.get('/_test/admin-only').status_code == 403
    assert boss.get('/_test/admin-only').json() == {'hi': 'Boss'}
    assert TestClient(app).get('/_test/admin-only').status_code == 401
