"""Configuration for the demo Notes MCP server.

The server is token-protected: `NOTES_API_TOKEN` is injected from a Kubernetes Secret
(the same way `woo-secrets` supplies the Woo Consumer Key). If the variable is empty the
process refuses to serve at all, so a deployment can never silently become public.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Bearer token required on every /mcp request (from the demo-notes-token Secret).
    notes_api_token: str = ""

    service_name: str = "demo-notes"
    service_version: str = "1.0.0"
    mcp_protocol_version: str = "2025-03-26"
    log_level: str = "INFO"

    def require_token(self) -> str:
        token = self.notes_api_token.strip()
        if not token:
            raise RuntimeError(
                "NOTES_API_TOKEN is not set - refusing to serve; inject it from the "
                "demo-notes-token Secret (demo-mcp-notes requires a bearer token)"
            )
        return token


@lru_cache
def get_settings() -> Settings:
    return Settings()
