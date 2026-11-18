"""The signed-in user's own in-app notifications."""
from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.models import Notification
from app.schemas import NotificationList, NotificationOut
from app.services.common import fail

router = APIRouter(prefix='/api/notifications', tags=['notifications'])


@router.get('', response_model=NotificationList)
def mine(user: CurrentUser, db: DB, limit: int = 30):
    items = db.execute(select(Notification).where(Notification.to_user == user.id).order_by(Notification.ts.desc()).limit(min(limit, 100))).scalars()
    unread = db.execute(select(func.count()).where(Notification.to_user == user.id, Notification.is_read.is_(False))).scalar_one()
    return NotificationList(items=[NotificationOut.model_validate(n) for n in items], unread=unread)


@router.post('/{nid}/read', status_code=204)
def read_one(nid: str, user: CurrentUser, db: DB):
    n = db.get(Notification, nid)
    if n is None or n.to_user != user.id:
        fail(404, 'Notification not found')
    n.is_read = True
    db.commit()


@router.post('/read-all', status_code=204)
def read_all(user: CurrentUser, db: DB):
    db.execute(update(Notification).where(Notification.to_user == user.id, Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
