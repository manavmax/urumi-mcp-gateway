"""rate limits per key/user (Phase 2, ADR-057)

Adds:
  - rate_limit_counters: atomic minute-window counters (one row per
    scope='key:<id>'|'user:<id>' + minute). Consumption is a single
    INSERT ... ON CONFLICT DO UPDATE count=count+1 RETURNING count, so the
    limit holds across every gateway replica (state lives in Postgres).
  - api_keys.rate_limit_per_minute: optional per-key override (NULL = default).
  - audit_logs: the outcome CHECK gains 'rate_limited' (constraint swap).

Revision ID: 007_rate_limits
Revises: 006_chat_uploads
Create Date: 2026-10-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_rate_limits"
down_revision: str | None = "006_chat_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_rate_limit_window", "rate_limit_counters", ["window_start"])
    op.add_column(
        "api_keys",
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
    )
    # outcome CHECK gains 'rate_limited' (drop + re-add: ALTER CONSTRAINT cannot
    # change a CHECK's expression in one step)
    op.drop_constraint("ck_audit_outcome", "audit_logs", type_="check")
    op.create_check_constraint(
        "ck_audit_outcome",
        "audit_logs",
        "outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error','rate_limited')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_outcome", "audit_logs", type_="check")
    op.create_check_constraint(
        "ck_audit_outcome",
        "audit_logs",
        "outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error')",
    )
    op.drop_column("api_keys", "rate_limit_per_minute")
    op.drop_index("ix_rate_limit_window", table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
