from tests.conftest import EMAILS, PASSWORD, make_client


def test_health_reports_migration(anon):
    r = anon.get('/api/health')
    assert r.status_code == 200
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from tests.conftest import API_DIR
    cfg = Config(str(API_DIR / 'alembic.ini')); cfg.set_main_option('script_location', str(API_DIR / 'alembic'))
    assert r.json()['migration'] == ScriptDirectory.from_config(cfg).get_current_head() and r.json()['patients'] == 15


def test_login_sets_httponly_cookie_and_me_works(anon):
    r = anon.post('/api/auth/login', json={'email': EMAILS['coordinator'], 'password': PASSWORD})
    assert r.status_code == 200 and r.json()['role'] == 'coordinator'
    cookie = r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie
    assert 'token' not in r.json()                                  # the session token is never exposed to JavaScript
    assert anon.get('/api/auth/me').json()['email'] == EMAILS['coordinator']


def test_wrong_password_and_lockout(anon):
    for _ in range(5):
        assert anon.post('/api/auth/login', json={'email': EMAILS['doctor'], 'password': 'nope'}).status_code == 401
    r = anon.post('/api/auth/login', json={'email': EMAILS['doctor'], 'password': PASSWORD})
    assert r.status_code == 429                                     # blocked even with the right password


def test_requires_auth(anon):
    assert anon.get('/api/patients').status_code == 401
    assert anon.get('/api/auth/me').status_code == 401


def test_csrf_header_required_for_writes():
    from fastapi.testclient import TestClient
    from app.main import app
    raw = TestClient(app)                                           # no X-Requested-With header
    assert raw.post('/api/auth/login', json={'email': EMAILS['coordinator'], 'password': PASSWORD}).status_code == 403


def test_logout_invalidates_session(coord):
    assert coord.post('/api/auth/logout').status_code == 204
    assert coord.get('/api/auth/me').status_code == 401


def test_change_password_signs_out_other_sessions():
    a, b = make_client('doctor2'), make_client('doctor2')
    r = a.post('/api/auth/change-password', json={'currentPassword': PASSWORD, 'newPassword': 'a-much-longer-pass'})
    assert r.status_code == 204
    assert a.get('/api/auth/me').status_code == 200                 # current session kept
    assert b.get('/api/auth/me').status_code == 401                 # other sessions revoked
    a.post('/api/auth/change-password', json={'currentPassword': 'a-much-longer-pass', 'newPassword': 'careflow-demo-2'})
    # restore the demo password for other tests
    from app.core.security import hash_password
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == EMAILS['doctor2']).one(); u.password_hash = hash_password(PASSWORD); db.commit()
