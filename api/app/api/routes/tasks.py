"""Tasks & follow-ups."""
from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api import present
from app.api.deps import DB, CurrentUser
from app.models import Task
from app.schemas import TaskCreateIn, TaskOut, TaskStatus, TaskUpdateIn
from app.services import tasks as svc
from app.services.care_gaps import rescan
from app.services.common import today

router = APIRouter(prefix='/api/tasks', tags=['tasks'])


@router.get('', response_model=list[TaskOut])
def list_tasks(user: CurrentUser, db: DB, assignee: str | None = Query(None, description='"me" or a user ID'), status: TaskStatus | None = None,
               patient_id: str | None = Query(None, alias='patientId'), overdue: bool = False, include_completed: bool = Query(True, alias='includeCompleted')):
    q = svc.scope_tasks(select(Task).options(selectinload(Task.events)), user)
    if assignee:
        q = q.where(Task.assignee == (user.id if assignee == 'me' else assignee))
    if status:
        q = q.where(Task.status == status)
    elif not include_completed:
        q = q.where(Task.status != 'Completed')
    if patient_id:
        q = q.where(Task.patient_id == patient_id)
    if overdue:
        q = q.where(Task.status != 'Completed', Task.due < today())
    rows = list(db.execute(q.order_by(Task.due.is_(None), Task.due, Task.id).limit(500)).scalars())
    return present.tasks(db, rows)


@router.post('', response_model=TaskOut, status_code=201)
def create_task(body: TaskCreateIn, user: CurrentUser, db: DB):
    t = svc.create(db, user, title=body.title, patient_id=body.patient_id, assignee=body.assignee, due=body.due, priority=body.priority,
                   kind=body.kind, description=body.description, source='Manual')
    rescan(db, [t.patient_id])
    return present.task(db, t)


@router.patch('/{task_id}', response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdateIn, user: CurrentUser, db: DB):
    t = svc.apply(db, user, svc.visible_task(db, user, task_id), status=body.status, assignee=body.assignee, due=body.due,
                  priority=body.priority, note=body.note)
    rescan(db, [t.patient_id])
    return present.task(db, t)
