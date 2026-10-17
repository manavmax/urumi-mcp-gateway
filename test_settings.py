#!/usr/bin/env python3
"""Test to verify the Settings class methods."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    
    gateway_llm_min_version: str = ""
    gateway_llm_exclude: str = ""
    
    def min_version_filter(self) -> str:
        return self.gateway_llm_min_version.strip()
    
    def exclude_patterns(self) -> list[str]:
        if not self.gateway_llm_exclude.strip():
            return []
        return [s.strip() for s in self.gateway_llm_exclude.split(",") if s.strip()]
    
    def discovered_models_enabled(self) -> bool:
        # This would normally check openai_api_key and openai_base_url
        return True

# Test it
settings = TestSettings()
print(f"Has min_version_filter: {hasattr(settings, 'min_version_filter')}")
print(f"min_version_filter: {settings.min_version_filter()}")
print(f"Has exclude_patterns: {hasattr(settings, 'exclude_patterns')}")
print(f"exclude_patterns: {settings.exclude_patterns()}")
print(f"Has discovered_models_enabled: {hasattr(settings, 'discovered_models_enabled')}")
print(f"discovered_models_enabled: {settings.discovered_models_enabled()}")