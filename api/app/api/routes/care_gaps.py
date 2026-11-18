"""Care gaps & alerts. Coordinators and doctors see and act on alerts in their scope; administrators get aggregate counts only."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, or_, select

from app.api import present
from app.api.deps import DB, CurrentUser, require_roles
from fastapi import HTTPException

from app.core.config import get_settings
from app.jobs import last_runs, run_all
from app.models import AuditLog, CareGapAlert, Patient
from app.schemas import AlertApproveIn, AlertOut, AlertSummary, Schema
from app.services import care_gaps as svc
from app.services import recommendation_agent as agent
from app.services.common import audit
from app.services.access import scope_patients

router = APIRouter(prefix='/api/care-gaps', tags=['care gaps'])
jobs_router = APIRouter(prefix='/api/jobs', tags=['jobs'])
Status = Literal['Open', 'Actioned', 'Dismissed', 'Resolved', 'All']


class DismissIn(Schema):
    reason: str = Field(min_length=5, max_length=500)


def alerts_out(db, rows: list[CareGapAlert]) -> list[AlertOut]:
    pn, sn = present.patient_names(db, [a.patient_id for a in rows]), present.staff_names(db, [a.assignee for a in rows])
    out = []
    for a in rows:
        st = agent.status(a)
        out.append(AlertOut.model_validate(a).model_copy(update={
            'patient_name': pn.get(a.patient_id, a.patient_id), 'assignee_name': sn.get(a.assignee), 'ai_status': st,
            # only show wording that matches the alert's current facts
            **({} if st == 'ready' else {'ai_text': None, 'ai_rationale': None, 'ai_task_title': None})}))
    return out


@router.get('', response_model=list[AlertOut])
def list_alerts(user: CurrentUser, db: DB, status: Status = 'Open', rule: str | None = None, priority: Literal['high', 'med', 'low'] | None = None,
                patient_id: str | None = Query(None, alias='patientId'), mine: bool = False, assignee: str | None = None):
    visible = scope_patients(select(Patient.id), user)                     # admin → 403 (use /summary)
    if mine and user.role == 'coordinator':
        visible = visible.where(Patient.coord_id == user.id)
    q = select(CareGapAlert).where(CareGapAlert.patient_id.in_(visible))
    if status != 'All':
        q = q.where(CareGapAlert.status == status)
    if rule:
        q = q.where(CareGapAlert.rule == rule)
    if priority:
        q = q.where(CareGapAlert.priority == priority)
    if patient_id:
        q = q.where(CareGapAlert.patient_id == patient_id)
    if assignee:
        q = q.where(CareGapAlert.assignee == (user.id if assignee == 'me' else assignee))
    rows = sorted(db.execute(q.limit(1000)).scalars(), key=lambda a: (svc.PRI_RANK[a.priority], a.first_seen))
    return alerts_out(db, rows)                          # listing never calls the LLM (AI wording is on request only)


@router.post('/{alert_id}/recommendation', response_model=AlertOut)
def reword(alert_id: str, user: CurrentUser, db: DB):
    """(Re)generate the AI wording for one alert – the ONLY path that calls the LLM for care gaps, triggered by a person's click
    (coordinator / doctor, own scope). Falls back to the rule template on failure; there is no automatic retry."""
    a = svc._alert_for(db, user, alert_id)
    if not get_settings().llm_configured:
        raise HTTPException(503, 'The AI recommendation agent is not configured (set CAREFLOW_GEMINI_API_KEY)')
    if not agent.word(db, a):
        raise HTTPException(502, f'The AI agent could not word this recommendation: {a.ai_error}')
    audit(db, user, 'AI recommendation generated', patient_id=a.patient_id, entity=a.id, detail=f'{a.category} · {a.ai_model}')
    db.commit()
    return alerts_out(db, [a])[0]


@router.get('/summary', response_model=AlertSummary)
def summary(user: CurrentUser, db: DB, mine: bool = False):
    """Counts per rule – available to every role (administrators see no patient-level detail)."""
    q = select(CareGapAlert.rule, CareGapAlert.priority, CareGapAlert.status, func.count()).group_by(CareGapAlert.rule, CareGapAlert.priority, CareGapAlert.status)
    if user.role != 'admin':
        visible = scope_patients(select(Patient.id), user)
        if mine and user.role == 'coordinator':
            visible = visible.where(Patient.coord_id == user.id)
        q = q.where(CareGapAlert.patient_id.in_(visible))
    cats = {r: {'rule': r, 'category': v[0], 'description': v[2], 'open': 0, 'high': 0} for r, v in svc.RULES.items()}
    by_status: dict[str, int] = {}
    for rule, pri, st, n in db.execute(q):
        by_status[st] = by_status.get(st, 0) + n
        if st == 'Open' and rule in cats:
            cats[rule]['open'] += n
            cats[rule]['high'] += n if pri == 'high' else 0
    return AlertSummary(categories=list(cats.values()), total_open=by_status.get('Open', 0), by_status=by_status)


@router.get('/activity')
def activity(user: CurrentUser, db: DB, limit: int = 8):
    """Recent alert decisions (approve / dismiss / automatic resolution) in the user's scope – the Care Gaps 'Activity log'."""
    q = select(AuditLog).where(or_(AuditLog.action.ilike('%recommendation%'), AuditLog.action.ilike('%alert%'), AuditLog.action.ilike('%care gap%')))
    if user.role != 'admin':
        q = q.where(AuditLog.patient_id.in_(scope_patients(select(Patient.id), user)))
    rows = db.execute(q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(min(limit, 50))).scalars()
    return [{'ts': a.ts, 'action': a.action, 'detail': a.detail if user.role != 'admin' else (a.entity or ''), 'user': a.user_name} for a in rows]


@router.post('/{alert_id}/approve', response_model=AlertOut)
def approve(alert_id: str, body: AlertApproveIn, user: CurrentUser, db: DB):
    a = svc.approve(db, user, alert_id, title=body.title, text=body.text, assignee=body.assignee, due=body.due, priority=body.priority)
    return alerts_out(db, [a])[0]


@router.post('/{alert_id}/dismiss', response_model=AlertOut)
def dismiss(alert_id: str, body: DismissIn, user: CurrentUser, db: DB):
    return alerts_out(db, [svc.dismiss(db, user, alert_id, body.reason)])[0]


@router.post('/scan', dependencies=[Depends(require_roles('coordinator', 'admin'))])
def scan(db: DB):
    """Re-run all rules now (they also run on the scheduler and after every relevant action)."""
    return svc.rescan(db, None)


@jobs_router.get('', dependencies=[Depends(require_roles('coordinator', 'admin'))])
def jobs_status(db: DB):
    return last_runs(db)


@jobs_router.post('/run', dependencies=[Depends(require_roles('admin'))])
def jobs_run():
    return run_all('manual (admin)')
