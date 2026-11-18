"""Doctor Performance (doctors: own figures; administrators: any doctor or all) and Executive Overview (administrators).
Aggregates only. "Explain with AI" recomputes the figures on the server and sends only those aggregates to the insights agent."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agents import orchestrator
from app.api.deps import DB, CurrentUser, require_roles
from app.core.catalog import DEPARTMENTS
from app.services import insight_agents, metrics

router = APIRouter(prefix='/api/metrics', tags=['metrics'])


def _perf(db, user, doctor_id: str | None, dept: str | None, range_key: str) -> tuple[dict, str]:
    if user.role == 'doctor':
        doctor_id = user.id                                  # doctors only ever see their own figures
    if dept and dept not in DEPARTMENTS:
        raise HTTPException(422, 'Unknown department')
    if range_key not in metrics.RANGES:
        raise HTTPException(422, 'Unknown date range')
    data = metrics.performance(db, doctor_id=doctor_id, dept=dept, range_key=range_key)
    scope = ('your own patients' if user.role == 'doctor' else 'the selected doctor' if doctor_id else 'all doctors') + (f', {dept}' if dept else '')
    return {**data, 'doctorId': doctor_id, 'dept': dept}, scope


@router.get('/performance', dependencies=[Depends(require_roles('doctor', 'admin'))])
def performance(user: CurrentUser, db: DB, doctorId: str | None = None, dept: str | None = None, range: str = '90'):
    return {**_perf(db, user, doctorId, dept, range)[0], 'doctors': metrics.doctors(db) if user.role == 'admin' else [], 'departments': DEPARTMENTS}


@router.get('/executive', dependencies=[Depends(require_roles('admin'))])
def executive(db: DB, range: str = '90'):
    if range not in metrics.RANGES:
        raise HTTPException(422, 'Unknown date range')
    return metrics.executive(db, range_key=range)


class ExplainIn(BaseModel):
    doctorId: str | None = None
    dept: str | None = None
    range: str = '90'


def _explained(res: dict) -> dict:
    if not res['ok']:
        raise HTTPException(502, f'The AI explanation is not available: {res["error"]}')
    return res


@router.post('/performance/explain', dependencies=[Depends(require_roles('doctor', 'admin'))])
def explain_performance(body: ExplainIn, user: CurrentUser, db: DB):
    t = time.perf_counter()
    data, scope = _perf(db, user, body.doctorId, body.dept, body.range)
    pre = [orchestrator.timed_step('Metrics (aggregates only)', t, f'{len(data["kpis"])} figures · {len(data["weekly"]["labels"])} weeks')]
    return _explained(insight_agents.explain(db, user, 'doctor_performance', data, scope, pre))


@router.post('/executive/explain', dependencies=[Depends(require_roles('admin'))])
def explain_executive(body: ExplainIn, user: CurrentUser, db: DB):
    if body.range not in metrics.RANGES:
        raise HTTPException(422, 'Unknown date range')
    t = time.perf_counter()
    data = metrics.executive(db, range_key=body.range)
    pre = [orchestrator.timed_step('Metrics (aggregates only)', t, f'{len(data["kpis"])} figures · {len(data["departments"])} departments · '
                                                                 f'{len(data["weekly"]["labels"])} weeks')]
    return _explained(insight_agents.explain(db, user, 'executive_overview', data, 'whole organisation', pre))
