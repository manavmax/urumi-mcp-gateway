"""Initial schema: users, api_keys, servers, tools, audit_logs

Revision ID: 001_initial
Revises:
Create Date: 2026-10-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('admin','member')", name="ck_users_role"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prefix", sa.Text, nullable=False, server_default="urumi_sk_"),
        sa.Column("hash", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False, unique=True),
        sa.Column("last4", sa.Text, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_api_keys_sha256", "api_keys", ["sha256"])
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    op.create_table(
        "servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("auth_type", sa.Text, nullable=False, server_default="none"),
        sa.Column("header_name", sa.Text, nullable=True),
        sa.Column("credential_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("credential_key_id", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.Text, nullable=False, server_default="Unknown"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("timeout_ms", sa.Integer, nullable=False, server_default="10000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="ck_servers_slug"),
        sa.CheckConstraint("auth_type IN ('none','bearer','header')", name="ck_servers_auth_type"),
    )

    op.create_table(
        "tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("upstream_name", sa.Text, nullable=False),
        sa.Column("exposed_name", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("input_schema", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("server_id", "upstream_name", name="uq_tools_server_upstream"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("server_slug", sa.Text, nullable=False),
        sa.Column("tool_exposed_name", sa.Text, nullable=False),
        sa.Column("tool_upstream_name", sa.Text, nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("client_ip", sa.Text, nullable=True),
        sa.CheckConstraint(
            "outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error')",
            name="ck_audit_outcome",
        ),
    )
    op.create_index("ix_audit_ts", "audit_logs", ["ts"])
    op.create_index("ix_audit_user_ts", "audit_logs", ["user_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_audit_user_ts", table_name="audit_logs")
    op.drop_index("ix_audit_ts", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("tools")
    op.drop_table("servers")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_sha256", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
