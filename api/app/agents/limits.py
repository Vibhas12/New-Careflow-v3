"""Switches and limits applied before any agent may call the LLM.

* Kill switch (rollback level L1): CAREFLOW_AGENTS_ENABLED=false → every agent off; CAREFLOW_AGENTS_DISABLED=["name"] → that agent off.
  Off also hides stored AI output (callers check is_enabled()), so the app behaves like V3.0.0 without AI wording.
* Per-user cap: CAREFLOW_AGENT_CALLS_PER_USER_PER_HOUR provider calls per rolling hour (all agents together).
* Cooldown: after the provider answered 429 on every model (the shared key's quota), nobody calls it for
  CAREFLOW_AGENT_COOLDOWN_SECONDS.
Counts come from the agent_runs table, so they survive restarts and are shared by several API instances.
"""
from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentRun, User
from app.models.agents import CALLED_LLM
from app.services.common import utcnow


class AgentError(Exception):
    status = 503

    def __init__(self, message: str, headers: dict | None = None):
        super().__init__(message)
        self.message, self.headers = message, headers or {}


class AgentDisabled(AgentError):
    status = 503


class AgentLimited(AgentError):
    status = 429


def unavailable_reason(name: str) -> str | None:
    cfg = get_settings()
    if not cfg.llm_configured:
        return 'The AI agents are not configured (set CAREFLOW_GEMINI_API_KEY)'
    if not cfg.agents_enabled:
        return 'AI agents are switched off (CAREFLOW_AGENTS_ENABLED=false)'
    if name in cfg.agents_disabled:
        return f'The “{name}” AI agent is switched off (CAREFLOW_AGENTS_DISABLED)'
    return None


def is_enabled(name: str) -> bool:
    return unavailable_reason(name) is None


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)      # SQLite returns naive UTC


def cooldown_until(db: Session):
    secs = get_settings().agent_cooldown_seconds
    if secs <= 0:
        return None
    last = db.execute(select(func.max(AgentRun.created_at)).where(AgentRun.status == 'failed', AgentRun.error_code == 429,
                                                                    AgentRun.created_at >= utcnow() - timedelta(seconds=secs))).scalar()
    return _aware(last) + timedelta(seconds=secs) if last else None


def used_this_hour(db: Session, user: User) -> int:
    return db.execute(select(func.count()).select_from(AgentRun).where(AgentRun.user_id == user.id, AgentRun.status.in_(CALLED_LLM),
                                                                       AgentRun.created_at >= utcnow() - timedelta(hours=1))).scalar() or 0


def check(db: Session, user: User) -> None:
    """Raise AgentLimited when the cooldown is active or the user reached the hourly cap."""
    now = utcnow()
    until = cooldown_until(db)
    if until and until > now:
        wait = max(1, int((until - now).total_seconds()))
        raise AgentLimited(f'The AI provider is rate-limited right now – please try again in {wait} s', {'Retry-After': str(wait)})
    cap = get_settings().agent_calls_per_user_per_hour
    if used_this_hour(db, user) >= cap:
        raise AgentLimited(f'You have reached the limit of {cap} AI requests per hour – please try again later', {'Retry-After': '600'})


def usage(db: Session, user: User) -> dict:
    cap, used, until = get_settings().agent_calls_per_user_per_hour, used_this_hour(db, user), cooldown_until(db)
    return {'perHour': cap, 'usedThisHour': used, 'remaining': max(0, cap - used),
            'cooldownUntil': until.isoformat() if until and until > utcnow() else None}
