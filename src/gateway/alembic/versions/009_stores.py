"""stores table + internal upstream flag (Phase 5, ADR-060)

Adds:
  - stores: one row per provisioned storefront (owner, slug, namespace,
    status Provisioning/Ready/Failed/Deleting, failure_reason, url). The
    user-facing projection of the provisioner's namespace + helm release.
  - servers.internal: auto-registered store upstreams are flagged internal and
    are removed by the store lifecycle, not by admin CRUD.

Revision ID: 009_stores
Revises: 008_login_lockout
Create Date: 2026-10-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_stores"
down_revision: str | None = "008_login_lockout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="Provisioning"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('Provisioning','Ready','Failed','Deleting')", name="ck_store_status"),
    )
    op.create_index("ix_stores_owner", "stores", ["owner_user_id"])
    op.add_column("servers", sa.Column("internal", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("servers", "internal")
    op.drop_index("ix_stores_owner", table_name="stores")
    op.drop_table("stores")
