"""login lockout shared across replicas (Phase 4, ADR-059)

Adds login_failures: one row per failed dashboard login per (kind, key) where
kind is 'user' (attempted email) or 'ip'. The lockout check counts rows inside
the window, so every gateway replica enforces the SAME lockout (the in-memory
predecessor allowed attempts x replicas). Never stores passwords.

Also: alembic's env.py takes a Postgres advisory lock around migrations so two
replicas starting together cannot race the upgrade (code change only, no schema).

Revision ID: 008_login_lockout
Revises: 007_rate_limits
Create Date: 2026-10-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_login_lockout"
down_revision: str | None = "007_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_failures_key_ts", "login_failures", ["kind", "key", "ts"])


def downgrade() -> None:
    op.drop_index("ix_login_failures_key_ts", table_name="login_failures")
    op.drop_table("login_failures")
