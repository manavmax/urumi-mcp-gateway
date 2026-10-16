"""SQLAlchemy async models — docs/04 §3.

Tables: users, api_keys, servers, tools, audit_logs, tool_permissions
All PKs are UUIDs except audit_logs (BIGSERIAL).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # admin | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (CheckConstraint("role IN ('admin','member')", name="ck_users_role"),)

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False, default="urumi_sk_")
    # The ONLY stored credential material: sha256 hex digest of the raw key (64 chars).
    # Looked up by digest and compared with hmac.compare_digest (auth/keys.py); the raw
    # key is 256-bit random and shown once, so no slow KDF is warranted (ADR-025).
    sha256: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    last4: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_sha256", "sha256"),
        Index("ix_api_keys_user_id", "user_id"),
    )


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # ^[a-z0-9-]+$
    url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")  # none|bearer|header
    header_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credential_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="Unknown", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="ck_servers_slug"),
        CheckConstraint("auth_type IN ('none','bearer','header')", name="ck_servers_auth_type"),
    )


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    upstream_name: Mapped[str] = mapped_column(Text, nullable=False)
    exposed_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (UniqueConstraint("server_id", "upstream_name", name="uq_tools_server_upstream"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    server_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    server_slug: Mapped[str] = mapped_column(Text, nullable=False)
    tool_exposed_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_upstream_name: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error')",
            name="ck_audit_outcome",
        ),
        Index("ix_audit_ts", "ts"),
        Index("ix_audit_user_ts", "user_id", "ts"),
    )


class ToolPermission(Base):
    """Deny rule for the member role (docs/DECISIONS.md ADR-033, docs/09 §2).

    - role: which role the rule applies to (only 'member' is enforced today; admins
      always have all tools, so their rules would be pointless and are rejected).
    - server_slug: the upstream's slug the rule is about.
    - tool_name: the EXPOSED name (e.g. 'woo__create_product'), or NULL for a whole
      server. Exposed names include the slug prefix so a rule is unambiguous.
    - created_by: which admin wrote the rule (SET NULL when the user is deleted).
    - created_at: when the rule was written.
    A rule is read live on every tools/list and tools/call: no caching survives a
    policy change, so the next call always reflects the current policy.
    """

    __tablename__ = "tool_permissions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    server_slug: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('member')", name="ck_tool_permissions_role"),
        Index("ix_tool_permissions_role_server", "role", "server_slug"),
    )
