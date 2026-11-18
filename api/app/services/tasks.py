"""Tasks & follow-ups. Every change is written to the task's event history and the audit log.

Visibility: coordinators and administrators see all tasks; doctors see tasks assigned to them or about their own patients.
Creating: coordinators and doctors. Updating status / reassigning: anyone who can see the task (admins manage workload).
"""
from datetime import date

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models import Patient, Task, TaskEvent, User
from app.services import messaging as msg
from app.services.access import get_visible_patient
from app.services.common import audit, fail, next_id, today, utcnow, fmt_d

STATUSES = ('New', 'In Progress', 'Waiting for Patient', 'Completed')


def scope_tasks(stmt: Select, user: User) -> Select:
    if user.role == 'doctor':
        own = select(Patient.id).where(Patient.doctor_id == user.id)
        return stmt.where(or_(Task.assignee == user.id, Task.patient_id.in_(own)))
    return stmt


def visible_task(db: Session, user: User, task_id: str) -> Task:
    t = db.execute(scope_tasks(select(Task), user).where(Task.id == task_id)).scalar_one_or_none()
    if t is None:
        fail(404, 'Task not found')
    return t


def _assignee(db: Session, uid: str | None) -> User:
    u = db.get(User, uid) if uid else None
    if u is None or not u.active:
        fail(422, 'Choose an active staff member to assign the task to')
    return u


def _event(t: Task, user: User | None, text: str):
    t.events.append(TaskEvent(seq=len(t.events), ts=utcnow(), by_name=user.name if user else 'System', text=text))


def create(db: Session, user: User, *, title: str, assignee: str | None, due: date, priority: str = 'med', patient_id: str | None = None,
           kind: str = 'followup', source: str = 'Manual', description: str | None = None, test_id: str | None = None, commit: bool = True) -> Task:
    if user.role not in ('coordinator', 'doctor'):
        fail(403, 'Your role cannot create tasks')
    if patient_id:
        get_visible_patient(db, user, patient_id)
    who = _assignee(db, assignee)
    t = Task(id=next_id(db, 'TSK', 7000), title=title.strip(), patient_id=patient_id, priority=priority, assignee=who.id, created=today(), due=due,
             status='New', kind=kind, source=source, description=(description or '').strip() or None, test_id=test_id)
    db.add(t)
    _event(t, user, f'Task created ({source}) and assigned to {who.name}')
    db.flush()
    audit(db, user, 'Task created', patient_id=patient_id, entity=t.id, detail=f'{t.title} → {who.name} ({source})')
    msg.notify(db, who.id, 'New task assigned', t.title, actor=user, patient_id=patient_id, route='tasks', level='high' if priority == 'high' else 'info')
    if commit:
        db.commit()
    return t


def apply(db: Session, user: User, t: Task, *, status: str | None = None, assignee: str | None = None, due: date | None = None,
          priority: str | None = None, note: str | None = None, commit: bool = True) -> Task:
    changes = []
    if status and status != t.status:
        if status not in STATUSES:
            fail(422, 'Unknown task status')
        changes.append(f'Status: {t.status} → {status}')
        t.completed_on = today() if status == 'Completed' else None
        t.status = status
    if assignee and assignee != t.assignee:
        new, old = _assignee(db, assignee), db.get(User, t.assignee) if t.assignee else None
        changes.append(f'Reassigned {old.name if old else "—"} → {new.name}')
        t.assignee = new.id
        msg.notify(db, new.id, 'Task reassigned to you', t.title, actor=user, patient_id=t.patient_id, route='tasks')
    if due and due != t.due:
        changes.append(f'Due date {fmt_d(t.due)} → {fmt_d(due)}' if t.due else f'Due date set to {fmt_d(due)}')
        t.due = due
    if priority and priority != t.priority:
        changes.append(f'Priority {t.priority} → {priority}')
        t.priority = priority
    if note and note.strip():
        changes.append(f'Note: {note.strip()}')
    if not changes:
        fail(409, 'Nothing to change')
    text = '; '.join(changes)
    _event(t, user, text)
    audit(db, user, 'Task updated', patient_id=t.patient_id, entity=t.id, detail=text)
    if commit:
        db.commit()
    return t
