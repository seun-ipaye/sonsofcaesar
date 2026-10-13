from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.models import Staff
from app.schemas import LoginIn, StaffOut

router = APIRouter(prefix='/auth', tags=['auth'])


def staff_out(s: Staff) -> StaffOut:
    return StaffOut(name=s.name, email=s.email, role=s.role.value)


@router.post('/login', response_model=StaffOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    staff = auth.login(db, response, body.email, body.password, request.headers.get('user-agent'))
    return staff_out(staff)


@router.post('/logout')
def logout(response: Response, db: Session = Depends(get_db), soc_session: str | None = Cookie(default=None)):
    auth.logout(db, response, soc_session)
    return {'ok': True}


@router.get('/me', response_model=StaffOut)
def me(staff: Staff = Depends(auth.current_staff)):
    return staff_out(staff)
