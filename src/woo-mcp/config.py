"""Configuration for the Woo MCP server.

All values come from the environment (the K8s Deployment injects the `woo-secrets`
Secret, so `WOO_URL` / `WOO_CONSUMER_KEY` / `WOO_CONSUMER_SECRET` map directly).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, env-var driven."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Credentials / target store (injected from the woo-secrets Secret)
    woo_url: str = "http://wordpress:80"
    woo_consumer_key: str = ""
    woo_consumer_secret: str = ""

    # HTTP behaviour
    woo_timeout_seconds: float = 10.0
    woo_max_response_bytes: int = 2_000_000
    woo_per_page_default: int = 10
    woo_per_page_max: int = 100

    # Image upload caps (F3): 5 MB byte cap, 4096 px per-side cap; enforced by
    # image_validate before any bytes reach WordPress.
    image_max_bytes: int = 5 * 1024 * 1024

    # Service metadata (surfaced by /healthz and the MCP serverInfo)
    service_name: str = "woo-mcp"
    service_version: str = "1.0.0"
    mcp_protocol_version: str = "2025-03-26"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (single source of truth)."""

    return Settings()
