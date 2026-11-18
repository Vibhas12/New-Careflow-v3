"""Sign-in / sign-out / current user / password change. Sessions are opaque tokens in an HttpOnly cookie."""
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, client_ip
from app.core.config import get_settings
from app.core.security import hash_password, login_limiter, new_session_token, token_hash, verify_password
from app.models import AuthSession, User
from app.schemas import ChangePasswordIn, DemoAccount, LoginIn, UserOut
from app.services.common import audit, utcnow

router = APIRouter(prefix='/api/auth', tags=['auth'])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, role=u.role, title=u.title, email=u.email, departments=u.department_names,
                   must_change_password=u.must_change_password)


@router.post('/login', response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    cfg = get_settings()
    key = body.email.strip().lower()
    if login_limiter.blocked(key, cfg.login_max_failures, cfg.login_window_minutes * 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f'Too many failed sign-in attempts. Try again in {cfg.login_window_minutes} minutes.')
    u = db.execute(select(User).where(func.lower(User.email) == key, User.active.is_(True))).scalar_one_or_none()
    if u is None or not verify_password(body.password, u.password_hash):
        login_limiter.fail(key)
        audit(db, u, 'Sign-in failed', detail=key, ip=client_ip(request)); db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Incorrect email or password')
    login_limiter.reset(key)
    tok, h = new_session_token()
    now = utcnow()
    db.add(AuthSession(token_hash=h, user_id=u.id, created_at=now, expires_at=now + timedelta(hours=cfg.session_hours), last_seen_at=now,
                       ip=client_ip(request), user_agent=(request.headers.get('user-agent') or '')[:400]))
    audit(db, u, 'Signed in', ip=client_ip(request))
    db.commit()
    response.set_cookie(cfg.session_cookie, tok, max_age=cfg.session_hours * 3600, httponly=True, secure=cfg.cookie_secure,
                        samesite='lax', path='/')
    return user_out(u)


@router.post('/logout', status_code=204)
def logout(request: Request, response: Response, db: DB):
    cfg = get_settings()
    tok = request.cookies.get(cfg.session_cookie)
    if tok and (s := db.get(AuthSession, token_hash(tok))):
        audit(db, s.user, 'Signed out', ip=client_ip(request))
        db.delete(s); db.commit()
    response.delete_cookie(cfg.session_cookie, path='/')


@router.get('/me', response_model=UserOut)
def me(user: CurrentUser):
    return user_out(user)


@router.post('/change-password', status_code=204)
def change_password(body: ChangePasswordIn, request: Request, user: CurrentUser, db: DB):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Current password is incorrect')
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Choose a password different from the current one')
    user.password_hash, user.must_change_password, user.password_changed_at = hash_password(body.new_password), False, utcnow()
    # sign out every other session of this user
    cur = token_hash(request.cookies.get(get_settings().session_cookie, ''))
    for s in db.execute(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != cur)).scalars():
        db.delete(s)
    audit(db, user, 'Password changed', ip=client_ip(request))
    db.commit()


@router.get('/demo-accounts', response_model=list[DemoAccount])
def demo_accounts(db: DB):
    """Development convenience for the sign-in screen. Disabled in production."""
    if get_settings().env == 'production':
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Not found')
    return [DemoAccount(name=u.name, role=u.role, title=u.title, email=u.email)
            for u in db.execute(select(User).where(User.active.is_(True)).order_by(User.role, User.name)).scalars()]
