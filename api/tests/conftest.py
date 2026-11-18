"""Test setup: a fresh SQLite database per test session, migrated with Alembic and loaded with the demo seed."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix='careflow_test_'))
os.environ['CAREFLOW_DATABASE_URL'] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"   # must be set before the app is imported
os.environ['CAREFLOW_ENV'] = 'test'
os.environ['CAREFLOW_UPLOAD_DIR'] = str(_tmp / 'uploads')
os.environ['CAREFLOW_SCHEDULER'] = 'off'
os.environ['CAREFLOW_LLM_ENABLED'] = 'false'          # never call the real LLM from tests (api/.env may hold a key)
os.environ['CAREFLOW_AGENT_CALLS_PER_USER_PER_HOUR'] = '100000'   # the shared test DB accumulates runs; test_agents tests the cap itself

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
PASSWORD = 'careflow-demo'
EMAILS = {'coordinator': 'priya.nair@careflow.demo', 'doctor': 'sarah.wilson@careflow.demo', 'doctor2': 'arjun.patel@careflow.demo'}


@pytest.fixture(scope='session', autouse=True)
def database():
    cfg = Config(str(API_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(API_DIR / 'alembic'))
    command.upgrade(cfg, 'head')
    from app.db import SessionLocal
    from app.seed import seed
    with SessionLocal() as db:
        assert seed(db)
    yield


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.core.security import login_limiter
    login_limiter.reset()


def make_client(role: str | None = None) -> TestClient:
    from app.main import app
    c = TestClient(app, headers={'X-Requested-With': 'careflow'})
    if role:
        email = EMAILS.get(role) or role
        r = c.post('/api/auth/login', json={'email': email, 'password': PASSWORD})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture
def anon():
    return make_client()


@pytest.fixture
def coord():
    return make_client('coordinator')


@pytest.fixture
def doctor():
    return make_client('doctor')


@pytest.fixture
def fake_llm(monkeypatch):
    """Agents switched on with a fake provider (no network). Configure with fake_llm.respond(Schema, value)."""
    from app.agents.testing import install_fake_llm
    return install_fake_llm(monkeypatch)


@pytest.fixture
def admin():
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        email = db.query(User).filter(User.role == 'admin').first().email
    return make_client(email)
