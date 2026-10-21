"""Gateway runtime configuration.

All values come from env (injected from K8s Secrets / Config).
See docs/04 §2 and docs/06 §5 for wiring.
"""

from __future__ import annotations

import os
from functools import lru_cache

# Single source of truth for the per-turn model-failure cap default; the Helm value
# gateway.llm.maxModelsPerTurn overrides it at runtime (OpenAI-compatible env var
# OPENAI_MAX_MODELS_PER_TURN).
from chat.llm_fallback import DEFAULT_MAX_MODELS_PER_TURN
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # ---- core ----
    database_url: str = "postgresql+asyncpg://urumi:urumi@localhost:5432/urumi"
    fernet_key: str = ""  # must be 44 urlsafe base64 chars; generated into gateway-secrets

    # LLM wiring for the chat assistant (charts values gateway.llm.*). The key is a
    # Secret reference (`gateway-llm`, or gateway.llm.existingSecret); the endpoint and
    # model are plain values because they are not secrets.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # Priority-ordered fallback chain (comma-separated, e.g. "gemini-3.5-flash,gemini-3-pro").
    # gateway.llm.models. The FIRST model is always gateway.llm.model (kept for
    # back-compat); remaining entries are tried in order on transient LLM errors
    # (429/5xx/timeout/connection) so a "high demand" model fails over to the next one.
    openai_models: str = ""
    # Models allowed to FAIL in one chat turn before the turn gives up (gateway.llm.
    # maxModelsPerTurn). Only failures count, never the model that served a step, and the
    # model that served step N is tried first for step N+1 (sticky) - see llm_fallback.
    openai_max_models_per_turn: int = DEFAULT_MAX_MODELS_PER_TURN

    # gateway administrator bootstrap (password comes from the chart-generated
    # `gateway-admin` Secret - never from a values file or a source default).
    admin_email: str = "admin@urumi.local"
    admin_password: str = ""  # empty => no bootstrap/sync, never a fallback password

    # session / CSRF (dashboard)
    session_secret: str = ""  # itsdangerous signer; defaults to fernet_key if empty
    session_cookie_name: str = "urumi_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days
    # Hardening (ADR-044): Secure flag on the session cookie. False locally (kind +
    # nip.io is plain http); prod (TLS at the Ingress) sets
    # gateway.sessionCookieSecure: true -> SESSION_COOKIE_SECURE=1.
    session_cookie_secure: bool = False

    # Hardening (ADR-044): login lockout. After `login_lockout_attempts` failures
    # within `login_lockout_window_seconds`, per username AND per client IP, login
    # returns 429 until the window drains. The counter is in-memory, so it is PER
    # REPLICA (documented in THREAT_MODEL.md; scaling to >1 replica needs a shared
    # store and is listed as an accepted residual there).
    login_lockout_attempts: int = 5
    login_lockout_window_seconds: int = 300

    # security / limits
    mcp_protocol_version: str = "2025-03-26"
    service_name: str = "urumi-gateway"
    service_version: str = "1.0.0"
    log_level: str = "INFO"

    # Timezone fallback (ADR-054): when a chat client sends no tz (or an invalid
    # one), the system prompt stamps THIS zone instead of dropping the local-time
    # context entirely. Helm gateway.defaultTimezone; the base default is UTC and
    # values-local sets Asia/Kolkata for the demo.
    default_timezone: str = "UTC"

    # Prometheus /metrics guard (ADR-056): when non-empty, GET /metrics requires
    # `Authorization: Bearer <token>` (constant-time compare). The endpoint is
    # in-cluster-only either way (NetworkPolicy + no Ingress route).
    metrics_bearer: str = ""

    # SSRF
    # Comma-separated extra allowed host suffixes, e.g. ".svc.cluster.local,.svc"
    allowed_host_suffixes: str = ".svc.cluster.local,.svc,.cluster.local"
    # If set, only hosts matching one of these suffixes OR localhost-for-dev? Actually
    # we disallow localhost always; this is suffix allow-list when non-empty.
    # Empty => allow any public host that passes private-net checks (useful for dev).
    allowed_domains: str = ""  # e.g. "example.com"

    # upstream defaults
    default_timeout_ms: int = 10000
    # Health loop interval / per-check timeout (Helm gateway.health.intervalSeconds /
    # timeoutSeconds, default 5s / 2s - docs/11_OBSERVABILITY.md). 5s lets a bare
    # `kubectl delete pod` Unreachable window be observed, and the recovery flip lands
    # within ~10s of the pod coming back (while Unreachable the loop keeps running).
    health_interval_seconds: int = 5
    health_timeout_seconds: int = 2
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: int = 60

    # audit queue
    audit_queue_maxsize: int = 10000
    audit_batch_size: int = 100
    audit_flush_interval_seconds: float = 1.0

    # rate limit
    rate_limit_per_minute: int = 60

    # F3 chat image uploads: 5 MB byte cap (env-tunable), 15 minute upload TTL.
    image_upload_max_bytes: int = 5 * 1024 * 1024
    chat_upload_ttl_seconds: int = 15 * 60

    # D3 request-level caps on ONE chat request (expanded in expand_messages):
    # at most chat_max_messages turns, and at most chat_max_total_chars total text
    # characters across every message and text part in the request.
    chat_max_messages: int = 40
    chat_max_total_chars: int = 100000

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

    def model_chain(self) -> list[str]:
        """Priority-ordered LLM model fallback chain, first = openai_model (back-compat).

        `gateway.llm.model` is the first/default model; `gateway.llm.models` (comma-separated)
        extends it. Entries are deduplicated keeping the first occurrence so a model listed
        both as the default and in the chain is only tried once, and the default always
        wins the first slot.
        """
        chain: list[str] = []
        for m in [self.openai_model, *[x.strip() for x in self.openai_models.split(",") if x.strip()]]:
            if m and m not in chain:
                chain.append(m)
        return chain or [self.openai_model]

    def max_models_per_turn(self) -> int:
        """Live per-turn cap on FAILED models (Helm gateway.llm.maxModelsPerTurn).

        Clamped: a zero/negative or unparsable Helm value must not disable the cap, it
        falls back to the default instead of letting one turn burn the whole chain.
        """
        try:
            value = int(self.openai_max_models_per_turn)
        except (TypeError, ValueError):
            return DEFAULT_MAX_MODELS_PER_TURN
        return value if value > 0 else DEFAULT_MAX_MODELS_PER_TURN


@lru_cache
def get_settings() -> Settings:
    # Map the upper-case Secret/env the chart injects onto the lower-case pydantic
    # field name, but never overwrite a lower-case value the operator already set.
    mapping = {
        "FERNET_KEY": "fernet_key",
        "DATABASE_URL": "database_url",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_BASE_URL": "openai_base_url",
        "OPENAI_MODEL": "openai_model",
        "OPENAI_MODELS": "openai_models",
        "OPENAI_MAX_MODELS_PER_TURN": "openai_max_models_per_turn",
        "HEALTH_INTERVAL_SECONDS": "health_interval_seconds",
        "HEALTH_TIMEOUT_SECONDS": "health_timeout_seconds",
        "SESSION_SECRET": "session_secret",
        "SESSION_COOKIE_SECURE": "session_cookie_secure",
        "LOGIN_LOCKOUT_ATTEMPTS": "login_lockout_attempts",
        "LOGIN_LOCKOUT_WINDOW_SECONDS": "login_lockout_window_seconds",
        "GATEWAY_ADMIN_PASSWORD": "admin_password",
        "IMAGE_UPLOAD_MAX_BYTES": "image_upload_max_bytes",
        "GATEWAY_DEFAULT_TIMEZONE": "default_timezone",
        "METRICS_BEARER": "metrics_bearer",
    }
    for env_key, field in mapping.items():
        if env_key in os.environ and field not in os.environ:
            # pydantic-settings reads env case-insensitively by default? Be explicit
            # by injecting via env var alias: also set lower-case for safety.
            os.environ[field] = os.environ[env_key]
    return Settings()
