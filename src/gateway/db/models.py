"""SQLAlchemy async models — docs/04 §3.

Tables: users, api_keys, servers, tools, audit_logs, tool_permissions, admin_events,
chat_uploads. All PKs are UUIDs except audit_logs and admin_events (BIGSERIAL).
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
    # Phase 2 (ADR-057): optional per-key rate limit override (calls/minute).
    # NULL = the gateway default (gateway.rateLimit.perKeyPerMinute). Admin-set
    # through PATCH /api/keys/{id}; never any credential material.
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # last_error holds ONLY a safe human label (from gw_mcp.categorize.category_label),
    # never raw exception text - an exception message may embed a URL with credentials,
    # a header or a token, and nothing like that may be stored or returned.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Observability (docs/11_OBSERVABILITY.md): when this server was last checked /
    # last known healthy, the last measured latency, and the stable error category
    # (connection_refused|timeout|dns_failure|tls_error|http_error:<code>|
    # invalid_response|auth_rejected|other). Updated on every health check and on
    # every upstream call outcome; admins-only in API responses.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(Text, nullable=True)
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
            "outcome IN ('success','upstream_error','permission_denied','timeout','circuit_open','validation_error','rate_limited')",
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


class AdminEvent(Base):
    """Append-only admin action trail (docs/DECISIONS.md ADR-034).

    One row per admin action, written in the SAME transaction as the action it
    records: a failed action cannot leave a success event behind, because the
    rollback takes the event with it. There is deliberately NO update/delete API
    for this table - the only writer is this recorder, and the only sanctioned
    wipe is `make demo-reset` (TRUNCATE, same documented exception as audit_logs).

    Secrecy contract (checked by tests/test_admin_events.py, which plants secret
    strings and searches every stored/returned byte for them):
      - credentials are recorded ONLY as credential_changed/credential_removed flags
      - API keys appear ONLY as prefix + last4 (never the raw key, never the digest)
      - no passwords, no request bodies, no headers, no URLs with tokens
    `target_ref` is a non-secret reference (slug, email, user id, key prefix+last4)
    and `details` holds small non-secret facts (field names, role, direction, owner id).
    login.failed stores the attempted email and time only, and one source (attempted
    email) can write at most LOGIN_FAILED_EVENT_LIMIT rows per window (audit/
    admin_events.py) so a flood of bad logins cannot flood the trail.
    """

    __tablename__ = "admin_events"

    id: Mapped[int] = mapped_column(
        # BigInteger in Postgres (prod); on sqlite a plain BIGINT PK is NOT a rowid
        # alias, so app-inserted test rows would fail with a NULL id. Integer on
        # sqlite keeps the unit-test harness (embedded sqlite) working; the DDL on
        # Postgres is unchanged.
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    # SET NULL so the trail survives a deleted actor (the action happened; who it
    # was is shown as unknown afterwards, never erased).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. server.create, key.revoke
    target_type: Mapped[str] = mapped_column(Text, nullable=False)  # server|user|key|permission|login
    target_ref: Mapped[str] = mapped_column(Text, nullable=False)  # non-secret: slug, email, id, prefix...last4
    outcome: Mapped[str] = mapped_column(Text, nullable=False)  # success|failure
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("outcome IN ('success','failure')", name="ck_admin_events_outcome"),
        Index("ix_admin_events_ts", "ts"),
        Index("ix_admin_events_action_ts", "action", "ts"),
        Index("ix_admin_events_actor_ts", "actor_user_id", "ts"),
    )


class RateLimitCounter(Base):
    """Atomic minute-window rate counters (Phase 2, ADR-057).

    One row per (scope, minute) where scope is 'key:<api_key_id>' or
    'user:<user_id>'. Consumption is a single INSERT ... ON CONFLICT DO UPDATE
    count = count + 1 RETURNING count, so the increment is atomic across any
    number of gateway replicas (the counter state lives in Postgres, not
    process memory). Rows older than a couple of minutes are swept by the
    background purge loop. No secrets, no payload - only counts.
    """

    __tablename__ = "rate_limit_counters"

    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_rate_limit_window", "window_start"),)


class ChatUpload(Base):
    """Ephemeral chat image upload (F3, ADR-035).

    Bytes live for at most `chat_upload_ttl_seconds` (15 minutes), are bound to
    the uploading user (every read is owner-checked; a user can only use their
    own upload ids), and the row is deleted after a successful attach. Expired
    rows are purged by a background loop and on every new upload. The model never
    receives these bytes as text: the gateway expands the row into a vision part
    of the LLM call only, and audit rows never carry image bytes.
    """

    __tablename__ = "chat_uploads"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chat_uploads_expires_at", "expires_at"),
        Index("ix_chat_uploads_user_id", "user_id"),
    )
