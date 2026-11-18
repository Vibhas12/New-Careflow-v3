"""Turn ORM rows into response models, resolving patient and staff names in one query per list."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, DiagnosticTest, Patient, Task, User
from app.schemas import AppointmentItem, TaskEventOut, TaskOut, TestItem


def _names(db: Session, model, ids, label):
    ids = {i for i in ids if i}
    return {r[0]: label(r) for r in db.execute(select(*model).where(model[0].in_(ids)))} if ids else {}


def staff_names(db: Session, ids) -> dict[str, str]:
    return _names(db, (User.id, User.name), ids, lambda r: r[1])


def patient_names(db: Session, ids) -> dict[str, str]:
    return _names(db, (Patient.id, Patient.first_name, Patient.last_name), ids, lambda r: f'{r[1]} {r[2]}')


def appointments(db: Session, rows: list[Appointment]) -> list[AppointmentItem]:
    pn, sn = patient_names(db, [a.patient_id for a in rows]), staff_names(db, [a.doctor_id for a in rows])
    return [AppointmentItem.model_validate(a).model_copy(update={'patient_name': pn.get(a.patient_id, a.patient_id), 'doctor_name': sn.get(a.doctor_id)})
            for a in rows] if rows else []


def tests(db: Session, rows: list[DiagnosticTest]) -> list[TestItem]:
    pn, sn = patient_names(db, [t.patient_id for t in rows]), staff_names(db, [t.ordered_by for t in rows])
    dept = _names(db, (Patient.id, Patient.department), [t.patient_id for t in rows], lambda r: r[1])
    return [TestItem.model_validate(t).model_copy(update={'patient_name': pn.get(t.patient_id, t.patient_id), 'ordered_by_name': sn.get(t.ordered_by),
                                                          'department': dept.get(t.patient_id)})
            for t in rows]


def tasks(db: Session, rows: list[Task]) -> list[TaskOut]:
    pn, sn = patient_names(db, [t.patient_id for t in rows]), staff_names(db, [t.assignee for t in rows])
    out = []
    for t in rows:
        o = TaskOut.model_validate(t, from_attributes=True).model_copy(update={
            'patient_name': pn.get(t.patient_id), 'assignee_name': sn.get(t.assignee),
            'events': [TaskEventOut.model_validate(e) for e in t.events]})
        out.append(o)
    return out


def appointment(db, a):
    return appointments(db, [a])[0]


def test(db, t):
    return tests(db, [t])[0]


def task(db, t):
    return tasks(db, [t])[0]
