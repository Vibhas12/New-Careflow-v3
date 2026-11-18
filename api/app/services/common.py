"""Small shared helpers: UTC clock, human-readable IDs (PT-1001 …) and the audit log."""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, IdSequence, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return date.today()


def fmt_d(d: date | None) -> str:
    """'6 Nov 2026' – the date style used throughout the UI (no zero padding, portable across platforms)."""
    return f'{d.day} {d:%b %Y}' if d else '—'


def fail(status: int, msg: str):
    """Raise a client error. 403 = role, 404 = not visible, 409 = invalid state transition, 422 = invalid input."""
    raise HTTPException(status, msg)


def next_id(db: Session, prefix: str, start: int = 1000) -> str:
    """Allocates the next ID for a prefix inside the caller's transaction (row-locked on PostgreSQL)."""
    seq = db.execute(select(IdSequence).where(IdSequence.prefix == prefix).with_for_update()).scalar_one_or_none()
    if seq is None:
        seq = IdSequence(prefix=prefix, value=start)
        db.add(seq)
    seq.value += 1
    db.flush()
    return f'{prefix}-{seq.value}'


def audit(db: Session, user: User | None, action: str, *, patient_id: str | None = None, entity: str | None = None,
          detail: str | None = None, ip: str | None = None) -> None:
    """Written by the server in the same transaction as the change it describes – never by the browser."""
    db.add(AuditLog(ts=utcnow(), user_id=user.id if user else None, user_name=user.name if user else 'System',
                    role=user.role if user else 'system', action=action, patient_id=patient_id, entity=entity, detail=detail, ip=ip))
