"""hosted_servers table (Phase 6, ADR-062): admin-chosen container images
deployed by the provisioner into hosted-<name> namespaces.

Revision ID: 010_hosted_servers
Revises: 009_stores
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "010_hosted_servers"
down_revision = "009_stores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosted_servers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("env_names", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, server_default="Provisioning"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hosted_servers_status", "hosted_servers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_hosted_servers_status", table_name="hosted_servers")
    op.drop_table("hosted_servers")
