from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# allow DATABASE_URL env override (k8s secret)
db_url = os.environ.get("DATABASE_URL") or os.environ.get("database_url")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
# also map FERNET style upper-case DATABASE_URL
for k in ("DATABASE_URL",):
    if k in os.environ and "DATABASE_URL" not in os.environ:
        pass

from db.models import Base

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    # Phase 4 (ADR-059): with 2+ gateway replicas starting together, two
    # concurrent `alembic upgrade head` runs can race the same DDL. A Postgres
    # ADVISORY XACT LOCK serializes them: the second replica waits for the
    # first pod's migration transaction to commit, then re-runs (a no-op at
    # head). The lock is released automatically at transaction end.
    #
    # ADR-061 FIX: the lock MUST be taken INSIDE alembic's migration
    # transaction. Taken before it (the ADR-059 code), the lock SELECT
    # autobegins a transaction; alembic then records the connection as already
    # in an external transaction and NEVER commits (begin_transaction returns
    # a no-op context), so every migration was silently rolled back when the
    # connection closed - logged "done", changed nothing. The lock inside the
    # migration transaction still serializes replicas and releases at commit.
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(715273)")
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # belt and braces: commit-as-you-go means an open autobegin transaction
        # would otherwise roll back at close (the ADR-061 bug), and a no-op
        # when the migration transaction already committed
        await connection.commit()
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
