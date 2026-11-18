"""SQLAlchemy engine, session factory and declarative base."""
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# deterministic constraint names so Alembic migrations are stable across databases
NAMING = {'ix': 'ix_%(column_0_label)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s', 'ck': 'ck_%(table_name)s_%(constraint_name)s',
          'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s'}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def make_engine(url: str):
    kw = {'pool_pre_ping': True}
    if url.startswith('sqlite'):
        kw['connect_args'] = {'check_same_thread': False}
    eng = create_engine(url, **kw)
    if url.startswith('sqlite'):
        @event.listens_for(eng, 'connect')
        def _fk_on(dbapi_conn, _):          # SQLite needs foreign keys switched on per connection
            cur = dbapi_conn.cursor()
            cur.execute('PRAGMA foreign_keys=ON')
            cur.execute('PRAGMA journal_mode=WAL')
            cur.execute('PRAGMA busy_timeout=30000')
            cur.close()
            # let SQLAlchemy own transactions so SAVEPOINTs (per-record import isolation) work with pysqlite
            dbapi_conn.isolation_level = None

        @event.listens_for(eng, 'begin')
        def _begin(conn):
            conn.exec_driver_sql('BEGIN')
    return eng


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
