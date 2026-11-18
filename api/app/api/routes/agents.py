"""AI agents: availability, the signed-in user's remaining quota, and the run log (no prompts or outputs are ever stored)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents import base, limits
from app.api.deps import DB, CurrentUser, require_roles
from app.core.config import get_settings
from app.models import AgentRun, User

router = APIRouter(prefix='/api/agents', tags=['ai agents'])


@router.get('')
def agents_status(user: CurrentUser, db: DB):
    """Which agents are available to the UI right now, and the caller's own usage. Every role may read it."""
    agents = base.all_agents()
    cfg = get_settings()
    return {
        'enabled': cfg.agents_enabled and cfg.llm_configured,
        'onDemandOnly': True,
        'agents': [{'name': a.name, 'label': a.label, 'enabled': limits.is_enabled(a.name), 'reason': limits.unavailable_reason(a.name)}
                   for a in agents],
        'usage': limits.usage(db, user) if user.role != 'admin' else None,
    }


HUMAN_STEP = {
    'recommendation': 'Coordinator or doctor approves, modifies or dismisses the alert',
    'summary': 'Shown with an AI label – suggested next steps stay rule-based',
    'answer': 'Drafted tasks / reminders wait as Proposed until a person approves',
    'import_extract': 'Reviewer applies the suggestion, then confirms the import',
    'import_map': 'Reviewer applies the mapping, then confirms the import',
    'insights': 'Read-only explanation of aggregate figures',
    'reviewer': 'Advisory second opinion – the person decides',
}
CALLED = ('ok', 'failed', 'withheld')


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def _issue_kind(text: str) -> str:
    """Group verifier findings without their specifics: 'uses a number that is not in the figures (87)' → '… figures'."""
    import re
    return re.sub(r'\s*\([^)]*\)', '', re.sub(r'^\w+(\s\w+)?:\s', '', text)).strip()[:120]


@router.get('/pipeline', dependencies=[Depends(require_roles('admin'))])
def pipeline(db: DB, period: str = Query('7', alias='range'), limit: int = 40):
    """Operations view of the multi-agent pipeline (Settings → AI agent pipeline). Every AI run here was started by a person;
    no patient references are returned. Background jobs are listed separately – they never call the LLM."""
    from datetime import timedelta
    from app.jobs import last_runs
    from app.services.common import today, utcnow
    days = {'1': 1, '7': 7, '30': 30, '90': 90}.get(period)
    q = select(AgentRun).order_by(AgentRun.id.desc())
    if days:
        q = q.where(AgentRun.created_at >= utcnow() - timedelta(days=days))
    rows = list(db.execute(q).scalars())
    agents = {a.name: a for a in base.all_agents()}
    names = dict(db.execute(select(User.id, User.name)).all())
    roles = dict(db.execute(select(User.id, User.role)).all())
    called = [r for r in rows if r.status in CALLED]
    llm_ms = [s['ms'] for r in called for s in (r.steps or []) if s.get('kind') == 'llm' and s.get('ms') is not None]
    code_ms = [sum(s['ms'] for s in (r.steps or []) if s.get('kind') == 'code' and s.get('ms') is not None) for r in rows if r.steps]
    total_ms = [r.duration_ms for r in called if r.duration_ms is not None]
    count = lambda st: sum(1 for r in rows if r.status == st)
    kpis = {
        'runs': len(rows), 'aiCalls': len(called), 'accepted': count('ok'), 'withheld': count('withheld'), 'failed': count('failed'),
        'blocked': count('blocked'), 'limited': count('limited'), 'disabled': count('disabled'),
        'acceptanceRate': round(100 * count('ok') / len(called)) if called else None,
        'fallbackRate': round(100 * sum(1 for r in called if len(r.attempts or []) > 1) / len(called)) if called else None,
        'avgLlmMs': round(sum(llm_ms) / len(llm_ms)) if llm_ms else None, 'p95TotalMs': _p95(total_ms),
        'avgCodeMs': round(sum(code_ms) / len(code_ms), 1) if code_ms else None,
        'autonomousActions': 0,                        # by design: every output waits for a person (see HUMAN_STEP)
    }
    per_agent = []
    for name, a in agents.items():
        mine = [r for r in rows if r.agent == name]
        ms = [r.duration_ms for r in mine if r.status in CALLED and r.duration_ms is not None]
        per_agent.append({'name': name, 'label': a.label, 'enabled': limits.is_enabled(name), 'runs': len(mine),
                          **{k: sum(1 for r in mine if r.status == k) for k in ('ok', 'withheld', 'failed', 'blocked')},
                          'avgMs': round(sum(ms) / len(ms)) if ms else None, 'p95Ms': _p95(ms),
                          'lastRun': limits._aware(mine[0].created_at) if mine else None, 'humanStep': HUMAN_STEP.get(name, '')})
    span = min(days or 14, 14)
    labels = [(today() - timedelta(days=i)) for i in range(span - 1, -1, -1)]
    day = lambda r: r.created_at.date()
    by_day = {'labels': [f'{d.day} {d.strftime("%b")}' for d in labels], 'series': {
        'Accepted': [sum(1 for r in rows if r.status == 'ok' and day(r) == d) for d in labels],
        'Withheld': [sum(1 for r in rows if r.status == 'withheld' and day(r) == d) for d in labels],
        'Failed': [sum(1 for r in rows if r.status == 'failed' and day(r) == d) for d in labels],
        'Not sent': [sum(1 for r in rows if r.status in ('blocked', 'limited', 'disabled') and day(r) == d) for d in labels]}}
    issues: dict[str, int] = {}
    for r in rows:
        for i in r.issues or []:
            issues[_issue_kind(i)] = issues.get(_issue_kind(i), 0) + 1
    models: dict[str, int] = {}
    for r in called:
        for x in r.attempts or []:
            models.setdefault(x['model'], 0)
            if x['outcome'] == 'ok':
                models[x['model']] += 1
    recent = [{'id': r.id, 'ts': limits._aware(r.created_at), 'agent': r.agent, 'label': agents[r.agent].label if r.agent in agents else r.agent,
               'status': r.status, 'model': r.model, 'durationMs': r.duration_ms, 'attempts': r.attempts or [], 'issues': r.issues or [],
               'error': (r.error or '')[:300] or None, 'user': names.get(r.user_id), 'role': roles.get(r.user_id), 'steps': r.steps,
               'humanStep': HUMAN_STEP.get(r.agent, '')} for r in rows[:min(max(limit, 1), 100)]]
    return {'range': period, 'generatedAt': utcnow(), 'onDemandOnly': True, 'kpis': kpis, 'agents': per_agent, 'byDay': by_day,
            'topIssues': sorted(({'issue': k, 'count': v} for k, v in issues.items()), key=lambda x: -x['count'])[:6],
            'models': sorted(({'model': k, 'answered': v} for k, v in models.items()), key=lambda x: -x['answered']),
            'runs': recent, 'jobs': last_runs(db)}


@router.get('/runs')
def runs(user: CurrentUser, db: DB, limit: int = 50):
    """Run log. Coordinators and doctors see their own runs; administrators see everyone's runs without patient references."""
    q = select(AgentRun).order_by(AgentRun.id.desc()).limit(min(max(limit, 1), 200))
    if user.role != 'admin':
        q = q.where(AgentRun.user_id == user.id)
    rows = list(db.execute(q).scalars())
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_({r.user_id for r in rows if r.user_id}))).all())
    admin = user.role == 'admin'
    return [{'id': r.id, 'ts': limits._aware(r.created_at), 'agent': r.agent, 'user': names.get(r.user_id), 'status': r.status, 'model': r.model,
             'attempts': r.attempts, 'error': r.error, 'errorCode': r.error_code, 'issues': r.issues, 'durationMs': r.duration_ms,
             'patientId': None if admin else r.patient_id, 'entity': None if admin else r.entity} for r in rows]
