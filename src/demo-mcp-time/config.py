"""Configuration for the demo Time MCP server (no credentials required)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    service_name: str = "demo-time"
    service_version: str = "1.0.0"
    mcp_protocol_version: str = "2025-03-26"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
