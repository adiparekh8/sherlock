"""Process-wide settings. Read once from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./sherlock.db"
    data_dir: Path = Path("data")

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    llm_cache_dir: Path = Path("llm_cache")
    uploaded_documents_dir: Path = Path(".sherlock/uploads")

    google_application_credentials: str | None = None
    docai_processor_name: str | None = None

    sherlock_api_url: str = "http://127.0.0.1:8000"
    sherlock_demo_actor: str = ""  # pre-fills the reviewer name in the UI so decision buttons are live

    @property
    def docai_enabled(self) -> bool:
        return bool(self.google_application_credentials and self.docai_processor_name)


@lru_cache
def get_settings() -> Settings:
    return Settings()
