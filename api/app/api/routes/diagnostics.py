"""Diagnostic tests: work lists by stage, and one endpoint per workflow step."""
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api import present
from app.api.deps import DB, CurrentUser
from app.models import DiagnosticTest, Patient
from app.schemas import RequestTestIn, ResultIn, ReviewIn, ScheduleTestIn, TestItem
from app.services import diagnostics as svc
from app.services.access import scope_patients
from app.services.care_gaps import rescan


def _done(db, t):
    rescan(db, [t.patient_id])
    return present.test(db, t)


router =APIRouter(prefix='/api/tests', tags=['diagnostic tests'])
Stage = Literal['requested', 'scheduled', 'awaiting-result', 'review', 'reviewed', 'all']
STAGE_STATUS = {'requested': ('Ordered',), 'scheduled': ('Scheduled',), 'awaiting-result': ('Completed',), 'review': ('Result Available',), 'reviewed': ('Reviewed',)}


@router.get('', response_model=list[TestItem])
def list_tests(user: CurrentUser, db: DB, stage: Stage = 'all', patient_id: str | None = Query(None, alias='patientId'), abnormal: bool | None = None):
    visible = scope_patients(select(Patient.id), user)            # admin → 403
    q = select(DiagnosticTest).options(selectinload(DiagnosticTest.values)).where(DiagnosticTest.patient_id.in_(visible))
    if stage != 'all':
        q = q.where(DiagnosticTest.status.in_(STAGE_STATUS[stage]))
    if patient_id:
        q = q.where(DiagnosticTest.patient_id == patient_id)
    if abnormal is not None:
        q = q.where(DiagnosticTest.abnormal.is_(abnormal))
    rows = list(db.execute(q.order_by(DiagnosticTest.ordered_on.desc(), DiagnosticTest.id.desc()).limit(500)).scalars())
    return present.tests(db, rows)


@router.post('', response_model=TestItem, status_code=201)
def request_test(body: RequestTestIn, user: CurrentUser, db: DB):
    return _done(db, svc.request(db, user, patient_id=body.patient_id, name=body.name, priority=body.priority, notes=body.notes))


@router.post('/{test_id}/schedule', response_model=TestItem)
def schedule(test_id: str, body: ScheduleTestIn, user: CurrentUser, db: DB):
    return _done(db, svc.schedule(db, user, svc.visible_test(db, user, test_id), body.date))


@router.post('/{test_id}/complete', response_model=TestItem)
def complete(test_id: str, user: CurrentUser, db: DB):
    return _done(db, svc.complete(db, user, svc.visible_test(db, user, test_id)))


@router.post('/{test_id}/result', response_model=TestItem, summary='Record a SIMULATED result (demo result feed)')
def result(test_id: str, body: ResultIn, user: CurrentUser, db: DB):
    return _done(db, svc.record_simulated_result(db, user, svc.visible_test(db, user, test_id), body.abnormal))


@router.post('/{test_id}/review', response_model=TestItem)
def review(test_id: str, body: ReviewIn, user: CurrentUser, db: DB):
    return _done(db, svc.review(db, user, svc.visible_test(db, user, test_id), body.note))
