"""chat_uploads ephemeral chat image uploads (F3, ADR-035)

Adds the chat_uploads table: one row per chat image upload, holding the
re-encoded image bytes for at most 15 minutes (chat_upload_ttl_seconds), bound
to the uploading user and deleted after a successful attach. Expired rows are
purged by a background loop and on every new upload. Audit rows never carry
image bytes.

Revision ID: 006_chat_uploads
Revises: 005_admin_events
Create Date: 2026-10-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_chat_uploads"
down_revision: str | None = "005_admin_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bytes", sa.LargeBinary, nullable=False),
        sa.Column("mime", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_uploads_expires_at", "chat_uploads", ["expires_at"])
    op.create_index("ix_chat_uploads_user_id", "chat_uploads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_uploads_user_id", table_name="chat_uploads")
    op.drop_index("ix_chat_uploads_expires_at", table_name="chat_uploads")
    op.drop_table("chat_uploads")
