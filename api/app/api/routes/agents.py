"""AI agents: availability, the signed-in user's remaining quota, and the run log (no prompts or outputs are ever stored)."""
from fastapi import APIRouter
from sqlalchemy import select

from app.agents import base, limits
from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.models import AgentRun, User

router = APIRouter(prefix='/api/agents', tags=['ai agents'])


@router.get('')
def agents_status(user: CurrentUser, db: DB):
    """Which agents are available to the UI right now, and the caller's own usage. Every role may read it."""
    base.get('recommendation')                      # make sure every agent module is registered
    cfg = get_settings()
    return {
        'enabled': cfg.agents_enabled and cfg.llm_configured,
        'onDemandOnly': True,
        'agents': [{'name': a.name, 'label': a.label, 'enabled': limits.is_enabled(a.name), 'reason': limits.unavailable_reason(a.name)}
                   for a in base.REGISTRY.values()],
        'usage': limits.usage(db, user) if user.role != 'admin' else None,
    }


@router.get('/runs')
def runs(user: CurrentUser, db: DB, limit: int = 50):
    """Run log. Coordinators and doctors see their own runs; administrators see everyone's runs without patient references."""
    q = select(AgentRun).order_by(AgentRun.id.desc()).limit(min(max(limit, 1), 200))
    if user.role != 'admin':
        q = q.where(AgentRun.user_id == user.id)
    rows = list(db.execute(q).scalars())
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_({r.user_id for r in rows if r.user_id}))).all())
    admin = user.role == 'admin'
    return [{'id': r.id, 'ts': r.created_at, 'agent': r.agent, 'user': names.get(r.user_id), 'status': r.status, 'model': r.model,
             'attempts': r.attempts, 'error': r.error, 'errorCode': r.error_code, 'issues': r.issues, 'durationMs': r.duration_ms,
             'patientId': None if admin else r.patient_id, 'entity': None if admin else r.entity} for r in rows]
