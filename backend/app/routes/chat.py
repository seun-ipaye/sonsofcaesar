"""The public support chat. Anyone can call it and each call costs money, so it has
an off switch, limits per visitor and a daily spending cap, all checked before Claude."""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agent import AgentResult, run_agent
from app.config import settings
from app.db import get_db
from app.models import ChatLog

router = APIRouter(tags=['chat'])
log = logging.getLogger(__name__)

PER_MINUTE = 6
PER_HOUR = 30
KEEP_LOGS = timedelta(days=30)
OFFLINE = "Chat is offline right now. DM @socfrvr on Instagram and they'll help."

# Dollars per million tokens (input, output). Unknown models count at the highest
# price, so a model change can't quietly slip past the cap.
PRICES = {'claude-opus-5-5': (4.0, 20.0), 'claude-sonnet-5-5': (2.0, 10.0), 'claude-haiku-5-5': (0.1, 0.5)}
DEFAULT_PRICE = (4.0, 20.0)

EMAIL = re.compile(r'[^@\s]+@[^@\s]+')
ORDER_ID = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE)


class ChatMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def takes_turns_ending_with_a_question(self):
        for i, message in enumerate(self.messages):
            if message.role != ('user' if i % 2 == 0 else 'assistant'):
                raise ValueError('messages must alternate, starting with the user')
        if self.messages[-1].role != 'user':
            raise ValueError('the last message must be from the user')
        if len(self.messages[-1].content) > 1000:
            raise ValueError('message is too long')
        return self


class ChatOut(BaseModel):
    reply: str


def client_ip(request: Request) -> str:
    # Railway's proxy passes the visitor's address in this header
    return request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')


def hash_ip(ip: str, now: datetime) -> str:
    return hashlib.sha256(f'{now.date()}:{ip}'.encode()).hexdigest()


def redact(text: str) -> str:
    return ORDER_ID.sub('[order id]', EMAIL.sub('[email]', text))


def cost_of(result: AgentResult) -> float:
    per_input, per_output = PRICES.get(settings.agent_model, DEFAULT_PRICE)
    return (result.input_tokens * per_input + result.output_tokens * per_output) / 1_000_000


def _check_limits(db: Session, ip_hash: str, now: datetime) -> None:
    if not settings.chat_enabled:
        raise HTTPException(503, OFFLINE)

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = db.scalar(select(func.coalesce(func.sum(ChatLog.cost_usd), 0.0)).where(ChatLog.at >= midnight))
    if spent >= settings.chat_daily_budget_usd:
        log.warning('Chat daily budget reached')
        raise HTTPException(503, OFFLINE)

    def recent(window: timedelta) -> int:
        return db.scalar(
            select(func.count()).select_from(ChatLog).where(ChatLog.ip_hash == ip_hash, ChatLog.at > now - window)
        )

    if recent(timedelta(minutes=1)) >= PER_MINUTE or recent(timedelta(hours=1)) >= PER_HOUR:
        raise HTTPException(429, "You're sending messages quickly. Try again in a bit, or DM @socfrvr.")


@router.post('/chat', response_model=ChatOut)
def chat(body: ChatIn, request: Request, db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    ip_hash = hash_ip(client_ip(request), now)
    _check_limits(db, ip_hash, now)
    db.commit()  # don't hold a database connection while waiting on Claude

    result = run_agent(db, [message.model_dump() for message in body.messages])
    cost = cost_of(result)

    db.execute(delete(ChatLog).where(ChatLog.at < now - KEEP_LOGS))
    db.add(
        ChatLog(
            ip_hash=ip_hash,
            question=redact(body.messages[-1].content),
            reply=redact(result.reply),
            outcome=result.outcome,
            tools_used=result.tools_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
        )
    )
    db.commit()
    log.info('Chat %s tools=%s tokens=%s/%s cost=$%.4f', result.outcome, result.tools_used,
             result.input_tokens, result.output_tokens, cost)
    return ChatOut(reply=result.reply)
