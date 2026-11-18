"""Health check and the staff directory."""
from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.deps import DB, CurrentUser
from app.core.catalog import APPT_TYPES, DEPARTMENTS, SLOTS, TEST_TYPES
from app.models import Patient, User
from app.schemas import Catalog, Health, UserBrief

router = APIRouter(prefix='/api', tags=['system'])


@router.get('/health', response_model=Health)
def health(db: DB):
    try:
        mig = db.execute(text('SELECT version_num FROM alembic_version')).scalar()
    except Exception:
        db.rollback(); mig = None
    return Health(ok=True, database=db.get_bind().dialect.name, migration=mig, patients=db.execute(select(func.count(Patient.id))).scalar_one())


@router.get('/catalog', response_model=Catalog)
def catalog(user: CurrentUser):
    """Reference lists for forms (departments, appointment/test types, bookable slots, task statuses)."""
    return Catalog(departments=DEPARTMENTS, appointment_types=APPT_TYPES, test_types=TEST_TYPES, slots=SLOTS,
                   task_statuses=['New', 'In Progress', 'Waiting for Patient', 'Completed'])


@router.get('/users', response_model=list[UserBrief])
def users(user: CurrentUser, db: DB):
    """Names, roles and departments of active staff (for assignee pickers and doctor names) – no contact details."""
    return [UserBrief(id=u.id, name=u.name, role=u.role, title=u.title, departments=u.department_names)
            for u in db.execute(select(User).where(User.active.is_(True)).order_by(User.name)).scalars()]
