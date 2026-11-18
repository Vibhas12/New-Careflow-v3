"""Patients: paginated, filtered list and full detail – both scoped to what the signed-in user may see."""
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import selectinload

from app.api import present
from app.api.deps import DB, CurrentUser, client_ip
from app.api.routes import care_gaps as care_gaps_routes
from app.models import (Appointment, AuditLog, CareGapAlert, Consultation, DiagnosticTest, Document, MedicalHistory, Patient, Prescription, Referral,
                        Task, User)
from app.schemas import (ActivityOut, AppointmentOut, CarePlanOut, ConsultationIn, ConsultationOut, DocumentOut, HistoryOut, NextAppt, PatientDetail,
                         PatientListItem, PatientPage, PrescriptionOut, PriorityChangeIn, PriorityEntryOut, ReferralCreateIn, ReferralOut,
                         ReferralStatusIn, TestOut)
from fastapi import HTTPException
from pydantic import Field

from app.schemas import Schema
from app.services import care, care_gaps, messaging, patient_info
from app.services import priority as priority_svc
from app.services.access import get_visible_patient, scope_patients
from app.services.common import audit

router = APIRouter(prefix='/api/patients', tags=['patients'])

PRI_ORDER = {'high': 0, 'med': 1, 'low': 2}
SORTS = {'name': (Patient.last_name, Patient.first_name), 'id': (Patient.id,), 'reviewDue': (Patient.review_due, Patient.id)}


def _names(db, ids) -> dict[str, str]:
    ids = {i for i in ids if i}
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(ids))).all()) if ids else {}


def list_items(db, rows: list[Patient]) -> list[PatientListItem]:
    names = _names(db, [p.doctor_id for p in rows])
    sug = care_gaps.suggested_priorities(db, [p.id for p in rows])
    info = patient_info.compute(db, rows)
    return [PatientListItem.model_validate(p).model_copy(update={'doctor_name': names.get(p.doctor_id), 'suggested_priority': sug.get(p.id),
                                                                 **{k: v for k, v in info[p.id].items() if k != 'next_appt'},
                                                                 'next_appt': NextAppt(**info[p.id]['next_appt']) if info[p.id]['next_appt'] else None})
            for p in rows]


@router.get('', response_model=PatientPage)
def list_patients(user: CurrentUser, db: DB,
                  search: str | None = Query(None, max_length=100, description='Name, patient ID or condition'),
                  department: str | None = None, priority: Literal['high', 'med', 'low'] | None = None,
                  status: Literal['Active', 'Under follow-up', 'Awaiting results', 'Discharged'] | None = None,
                  doctor_id: str | None = Query(None, alias='doctorId'), mine: bool = False, include_discharged: bool = Query(False, alias='includeDischarged'),
                  sort: Literal['priority', 'name', 'id', 'reviewDue', 'nextAppt'] = 'priority',
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100, alias='pageSize')):
    q = scope_patients(select(Patient), user)
    if search:
        like = f'%{search.strip().lower()}%'
        q = q.where(or_(func.lower(Patient.first_name + ' ' + Patient.last_name).like(like), func.lower(Patient.id).like(like),
                        func.lower(Patient.primary_condition).like(like)))
    if department:
        q = q.where(Patient.department == department)
    if priority:
        q = q.where(Patient.priority == priority)
    if doctor_id:
        q = q.where(Patient.doctor_id == doctor_id)
    if mine and user.role == 'coordinator':
        q = q.where(Patient.coord_id == user.id)
    if status:
        q = q.where(patient_info.status_expr() == status)
    elif not include_discharged:
        q = q.where(Patient.discharged.is_(False))
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    if sort == 'priority':
        q = q.order_by(case(PRI_ORDER, value=Patient.priority), Patient.last_name, Patient.first_name)
    elif sort == 'nextAppt':
        nxt = patient_info.next_appt_date_expr()
        q = q.order_by(nxt.is_(None), nxt, Patient.last_name)
    else:
        q = q.order_by(*SORTS[sort])
    rows = list(db.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars())
    return PatientPage(items=list_items(db, rows), total=total, page=page, page_size=page_size)


@router.get('/{patient_id}', response_model=PatientDetail)
def get_patient(patient_id: str, request: Request, user: CurrentUser, db: DB):
    p = get_visible_patient(db, user, patient_id)
    db.refresh(p)
    by_pat = lambda M, order: list(db.execute(select(M).where(M.patient_id == p.id).order_by(*order)).scalars())
    tests = list(db.execute(select(DiagnosticTest).options(selectinload(DiagnosticTest.values))
                            .where(DiagnosticTest.patient_id == p.id).order_by(DiagnosticTest.ordered_on.desc())).scalars())
    names = _names(db, [p.doctor_id, p.coord_id])
    cols = {c.key: getattr(p, c.key) for c in Patient.__table__.columns}
    info = patient_info.compute(db, [p])[p.id]
    gaps = list(db.execute(select(CareGapAlert).where(CareGapAlert.patient_id == p.id, CareGapAlert.status.in_(('Open', 'Actioned')))).scalars())
    gaps.sort(key=lambda a: (a.status != 'Open', care_gaps.PRI_RANK[a.priority]))
    acts = db.execute(select(AuditLog).where(AuditLog.patient_id == p.id, AuditLog.action != 'Viewed patient record')
                      .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(7)).scalars()
    d = PatientDetail(**cols, **{k: v for k, v in info.items() if k != 'next_appt'}, **dict(
        next_appt=NextAppt(**info['next_appt']) if info['next_appt'] else None,
        care_gaps=care_gaps_routes.alerts_out(db, gaps),
        activity=[ActivityOut(ts=a.ts, user_name=a.user_name, action=a.action, detail=a.detail) for a in acts],
        documents=[DocumentOut.model_validate(x) for x in by_pat(Document, (Document.uploaded_at,))],
        doctor_name=names.get(p.doctor_id), coordinator_name=names.get(p.coord_id),
        suggested_priority=care_gaps.suggested_priorities(db, [p.id])[p.id],
        allergies=[a.substance for a in p.allergies], medications=[m.description for m in p.medications if m.status == 'Active'],
        diagnoses=[x.description for x in p.diagnoses], care_plan=CarePlanOut.model_validate(p.care_plan) if p.care_plan else None,
        appointments=[AppointmentOut.model_validate(x) for x in by_pat(Appointment, (Appointment.appt_date.desc(), Appointment.appt_time.desc()))],
        tests=[TestOut.model_validate(t) for t in tests],
        referrals=[ReferralOut.model_validate(x) for x in by_pat(Referral, (Referral.created_on.desc(),))],
        prescriptions=[PrescriptionOut.model_validate(x) for x in by_pat(Prescription, (Prescription.rx_date.desc(),))],
        consultations=[ConsultationOut.model_validate(x) for x in by_pat(Consultation, (Consultation.consult_date.desc(),))],
        history=[HistoryOut.model_validate(x) for x in by_pat(MedicalHistory, (MedicalHistory.event_date.desc(),))],
        tasks=present.tasks(db, list(db.execute(select(Task).options(selectinload(Task.events)).where(Task.patient_id == p.id)
                                                .order_by(Task.status == 'Completed', Task.due)).scalars())),
        can_change_priority=user.role == 'coordinator' or (user.role == 'doctor' and p.doctor_id == user.id)))
    audit(db, user, 'Viewed patient record', patient_id=p.id, ip=client_ip(request))   # access logging for clinical records
    db.commit()
    return d


@router.post('/{patient_id}/priority', response_model=PriorityEntryOut)
def change_priority(patient_id: str, body: PriorityChangeIn, request: Request, user: CurrentUser, db: DB):
    return priority_svc.change_priority(db, user, patient_id, body.new_priority, body.comment, ip=client_ip(request))


@router.get('/{patient_id}/priority-history', response_model=list[PriorityEntryOut])
def priority_history(patient_id: str, user: CurrentUser, db: DB):
    return priority_svc.history(db, user, patient_id)


@router.post('/{patient_id}/referrals', response_model=ReferralOut, status_code=201)
def create_referral(patient_id: str, body: ReferralCreateIn, user: CurrentUser, db: DB):
    r = care.create_referral(db, user, patient_id, body.referred_to, body.reason)
    care_gaps.rescan(db, [r.patient_id])
    return r


@router.post('/{patient_id}/consultations', response_model=ConsultationOut, status_code=201)
def record_consultation(patient_id: str, body: ConsultationIn, user: CurrentUser, db: DB):
    c = care.record_consultation(db, user, patient_id, d=body.date, notes=body.notes, diagnosis=body.diagnosis, prescription=body.prescription,
                                 plan=body.plan, follow_up=body.follow_up, instructions=body.instructions,
                                 create_follow_up_task=body.create_follow_up_task)
    care_gaps.rescan(db, [c.patient_id])
    return c


class CallIn(Schema):
    outcome: Literal['Reached patient', 'No answer', 'Left voicemail', 'Wrong number / unreachable']
    notes: str | None = Field(None, max_length=1000)


class ManualReminderIn(Schema):
    type: Literal['Appointment reminder', 'Diagnostic test reminder', 'Follow-up request', 'Medication reminder']
    channel: Literal['SMS', 'Email', 'App']
    message: str = Field(min_length=5, max_length=1000)
    appointment_id: str | None = None
    test_id: str | None = None


@router.post('/{patient_id}/calls', status_code=204)
def log_call(patient_id: str, body: CallIn, user: CurrentUser, db: DB):
    """Records the outcome of a phone call made outside the system (no call is placed) in the patient's activity/audit trail."""
    if user.role not in ('coordinator', 'doctor'):
        raise HTTPException(403, 'Your role cannot log patient calls')
    p = get_visible_patient(db, user, patient_id)
    text = f'Phone call: {body.outcome}' + (f' – {body.notes.strip()}' if body.notes and body.notes.strip() else '')
    audit(db, user, 'Patient call logged', patient_id=p.id, detail=text)
    db.commit()


@router.post('/{patient_id}/reminders', status_code=201)
def send_reminder(patient_id: str, body: ManualReminderIn, user: CurrentUser, db: DB):
    """Manual reminder – SIMULATED delivery (recorded with a Delivered/Failed outcome; nothing is sent)."""
    if user.role not in ('coordinator', 'doctor'):
        raise HTTPException(403, 'Your role cannot send reminders')
    p = get_visible_patient(db, user, patient_id)
    r = messaging.send_manual_reminder(db, user, p, kind='Diagnostic Test' if body.type == 'Diagnostic test reminder' else 'Manual', label=body.type,
                                       channel=body.channel, message=body.message, ref_id=body.appointment_id or body.test_id)
    db.commit()
    return {'id': r.id, 'status': r.status}


referrals_router = APIRouter(prefix='/api/referrals', tags=['patients'])


@referrals_router.post('/{referral_id}/status', response_model=ReferralOut)
def referral_status(referral_id: str, body: ReferralStatusIn, user: CurrentUser, db: DB):
    r = care.set_referral_status(db, user, referral_id, body.status)
    care_gaps.rescan(db, [r.patient_id])
    return r
