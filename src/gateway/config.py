"""Gateway runtime configuration.

All values come from env (injected from K8s Secrets / Config).
See docs/04 §2 and docs/06 §5 for wiring.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # ---- core ----
    database_url: str = "postgresql+asyncpg://urumi:urumi@localhost:5432/urumi"
    fernet_key: str = ""  # must be 44 urlsafe base64 chars; generated into gateway-secrets
    openai_api_key: str = ""

    # session / CSRF (dashboard)
    session_secret: str = ""  # itsdangerous signer; defaults to fernet_key if empty
    session_cookie_name: str = "urumi_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days

    # security / limits
    mcp_protocol_version: str = "2025-03-26"
    service_name: str = "urumi-gateway"
    service_version: str = "1.0.0"
    log_level: str = "INFO"

    # SSRF
    # Comma-separated extra allowed host suffixes, e.g. ".svc.cluster.local,.svc"
    allowed_host_suffixes: str = ".svc.cluster.local,.svc,.cluster.local"
    # If set, only hosts matching one of these suffixes OR localhost-for-dev? Actually
    # we disallow localhost always; this is suffix allow-list when non-empty.
    # Empty => allow any public host that passes private-net checks (useful for dev).
    allowed_domains: str = ""  # e.g. "example.com"

    # upstream defaults
    default_timeout_ms: int = 10000
    health_interval_seconds: int = 15
    health_timeout_seconds: int = 5
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: int = 60

    # audit queue
    audit_queue_maxsize: int = 10000
    audit_batch_size: int = 100
    audit_flush_interval_seconds: float = 1.0

    # rate limit
    rate_limit_per_minute: int = 60

    # CORS (dashboard dev)
    cors_allow_origins: str = ""

    @property
    def effective_session_secret(self) -> str:
        return self.session_secret or self.fernet_key or "dev-session-secret-change-me"

    def allowed_host_suffix_list(self) -> list[str]:
        if not self.allowed_host_suffixes.strip():
            return []
        return [s.strip() for s in self.allowed_host_suffixes.split(",") if s.strip()]

    def allowed_domains_list(self) -> list[str]:
        if not self.allowed_domains.strip():
            return []
        return [s.strip().lower() for s in self.allowed_domains.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    # Support FERNET_KEY / DATABASE_URL env names from the chart (upper-case)
    # in addition to lower-case pydantic names.
    overrides: dict[str, str] = {}
    if not os.environ.get("DATABASE_URL") and os.environ.get("database_url"):
        pass
    # Map upper-case Secrets to settings fields when lower-case not set
    mapping = {
        "FERNET_KEY": "fernet_key",
        "DATABASE_URL": "database_url",
        "OPENAI_API_KEY": "openai_api_key",
        "SESSION_SECRET": "session_secret",
    }
    for env_key, field in mapping.items():
        if env_key in os.environ and field not in os.environ:
            # pydantic-settings reads env case-insensitively by default? Be explicit
            # by injecting via env var alias: also set lower-case for safety.
            os.environ[field] = os.environ[env_key]
    return Settings()
