from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def run_migrations_online() -> None:
    url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, poolclass=pool.NullPool, connect_args={"connect_timeout": 10})
    # The explicit outer transaction is essential: taking the session advisory
    # lock autobegins a SQLAlchemy transaction, so relying only on Alembic's
    # context transaction would roll all DDL back when the connection closes.
    with engine.begin() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_lock(hashtext('gocomet_alembic'))")
        context.configure(connection=connection, target_metadata=None, compare_type=True)
        try:
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(hashtext('gocomet_alembic'))")
    engine.dispose()


run_migrations_online()
