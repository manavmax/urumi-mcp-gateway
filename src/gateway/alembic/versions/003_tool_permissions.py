"""tool_permissions: deny rules for the member role (ADR-033)

Per-role tool permissions (stand-out item 2). A deny rule is (role, server_slug,
tool_name). tool_name is the EXPOSED name (e.g. 'woo__create_product'), or NULL for
a whole-server deny. Only role='member' is allowed (admins always have all tools).
Rules are read live on every tools/list and tools/call — no caching survives a
policy change.

Revision ID: 003_tool_permissions
Revises: 002_api_keys_sha256_only
Create Date: 2026-10-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_tool_permissions"
down_revision: str | None = "002_api_keys_sha256_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("server_slug", sa.Text, nullable=False),
        sa.Column("tool_name", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('member')", name="ck_tool_permissions_role"),
    )
    op.create_index("ix_tool_permissions_role_server", "tool_permissions", ["role", "server_slug"])


def downgrade() -> None:
    op.drop_index("ix_tool_permissions_role_server", table_name="tool_permissions")
    op.drop_table("tool_permissions")
