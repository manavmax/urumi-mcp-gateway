"""servers health-tracking columns (observability item 1)

Adds last_checked_at, last_ok_at, last_latency_ms and last_error_category to the
servers table. These let the dashboard show a "checked X ago, last ok Y ago,
Z ms" second line under the status badge and drive the next-best-action banner.
`last_error` is unchanged in type but from now on only ever holds a safe human
label derived from the category (never raw exception text, which could embed a
URL with credentials, a header or a token).

Revision ID: 004_servers_health_tracking
Revises: 003_tool_permissions
Create Date: 2026-10-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_servers_health_tracking"
down_revision: str | None = "003_tool_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("servers", sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("servers", sa.Column("last_latency_ms", sa.Integer, nullable=True))
    op.add_column("servers", sa.Column("last_error_category", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "last_error_category")
    op.drop_column("servers", "last_latency_ms")
    op.drop_column("servers", "last_ok_at")
    op.drop_column("servers", "last_checked_at")
