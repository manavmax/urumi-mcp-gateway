"""admin_events append-only admin action trail (ADR-034)

Adds the admin_events table: one row per admin action (server.create/update/
enable/disable/delete, user.invite/delete, key.create/revoke, permission.change,
login.failed) with actor, target and outcome. Written in the SAME transaction as
the action it records, so a rolled-back action cannot leave a success event.
No update/delete API exists for it; `make demo-reset` TRUNCATEs it like audit_logs.

Secrecy: credentials only as changed/removed flags, API keys only as prefix+last4,
no passwords, no request bodies. See docs/DECISIONS.md ADR-034 and THREAT_MODEL.md.

Revision ID: 005_admin_events
Revises: 004_servers_health_tracking
Create Date: 2026-10-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_admin_events"
down_revision: str | None = "004_servers_health_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text, nullable=False),
        sa.Column("target_ref", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.CheckConstraint("outcome IN ('success','failure')", name="ck_admin_events_outcome"),
    )
    op.create_index("ix_admin_events_ts", "admin_events", ["ts"])
    op.create_index("ix_admin_events_action_ts", "admin_events", ["action", "ts"])
    op.create_index("ix_admin_events_actor_ts", "admin_events", ["actor_user_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_admin_events_actor_ts", table_name="admin_events")
    op.drop_index("ix_admin_events_action_ts", table_name="admin_events")
    op.drop_index("ix_admin_events_ts", table_name="admin_events")
    op.drop_table("admin_events")
