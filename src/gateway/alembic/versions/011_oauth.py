"""oauth_clients / oauth_codes / oauth_tokens (Phase 7, ADR-063).

Minimal-correct MCP authorization: dynamic client registration (RFC 7591),
authorization code flow with PKCE S256 ONLY, resource-indicator binding
(RFC 8707), short-lived opaque access tokens + hashed refresh tokens, mapped
to gateway users so permissions, rate limits and audit work exactly as with
API keys.

Revision ID: 011_oauth
Revises: 010_hosted_servers
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "011_oauth"
down_revision = "010_hosted_servers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("client_secret_hash", sa.Text(), nullable=True),
        sa.Column("redirect_uris", pg.JSONB(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_endpoint_auth_method", sa.Text(), nullable=False, server_default="none"),
        sa.Column("grant_types", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("code_hash", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
        sa.Column("challenge", sa.Text(), nullable=False),
        sa.Column("challenge_method", sa.Text(), nullable=False, server_default="S256"),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "oauth_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "client_id",
            sa.Text(),
            sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rotated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("family", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_oauth_tokens_user", "oauth_tokens", ["user_id"])
    op.create_index("ix_oauth_tokens_family", "oauth_tokens", ["family"])


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_family", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_user", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
