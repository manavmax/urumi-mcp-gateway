"""Configuration for the demo Time MCP server (no credentials required)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    service_name: str = "demo-time"
    service_version: str = "1.0.0"
    mcp_protocol_version: str = "2025-03-26"
    log_level: str = "INFO"
    # ADR-054: optional default timezone for get_current_time when the caller
    # omits one (Helm demoTime.defaultTimezone -> env DEFAULT_TIMEZONE).
    # Empty keeps the historical UTC default.
    default_timezone: str = "UTC"


@lru_cache
def get_settings() -> Settings:
    return Settings()
