"""Request dependencies: database session, current user (from the HttpOnly session cookie) and role guards."""
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import token_hash
from app.db import get_db
from app.models import AuthSession, User
from app.services.common import utcnow

DB = Annotated[Session, Depends(get_db)]


def _aware(dt):
    # SQLite returns naive datetimes; values are always stored in UTC
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_current_user(request: Request, db: DB) -> User:
    tok = request.cookies.get(get_settings().session_cookie)
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Authentication required')
    s = db.get(AuthSession, token_hash(tok))
    now = utcnow()
    if s is None or _aware(s.expires_at) <= now or not s.user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Session expired – please sign in again')
    if s.last_seen_at is None or now - _aware(s.last_seen_at) > timedelta(minutes=5):   # avoid a write on every request
        s.last_seen_at = now
        db.commit()
    request.state.user = s.user
    return s.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'Your role is not authorised for this action')
        return user
    return guard


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
