"""Alembic environment: the database URL comes from app settings (CAREFLOW_DATABASE_URL), never from alembic.ini."""
from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def url() -> str:
    return config.attributes.get('database_url') or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=url().startswith('sqlite'))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(url())
    with engine.connect() as connection:
        sqlite = connection.dialect.name == 'sqlite'
        if sqlite:
            # SQLite batch migrations rebuild tables (copy → drop → rename). With foreign keys ON, dropping the old table
            # fires ON DELETE CASCADE on child tables and would silently delete their rows. Switch enforcement off for
            # the migration (on the raw connection – PRAGMA foreign_keys is ignored inside a transaction).
            connection.connection.driver_connection.execute('PRAGMA foreign_keys=OFF')
        # render_as_batch lets ALTER TABLE migrations work on SQLite as well as PostgreSQL
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=sqlite)
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            connection.commit()
            bad = connection.connection.driver_connection.execute('PRAGMA foreign_key_check').fetchall()
            connection.connection.driver_connection.execute('PRAGMA foreign_keys=ON')
            if bad:
                raise RuntimeError(f'Foreign-key violations after migration: {bad[:5]}')


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
