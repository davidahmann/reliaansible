"""
Configuration for Relia CLI, using environment variables with sensible defaults.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class CLISettings(BaseSettings):
    # Backend URL for API calls
    BACKEND_URL: str = Field("http://localhost:8000", validation_alias="RELIA_BACKEND_URL")

    # Local storage directories
    DATA_DIR: Path = Field(default_factory=lambda: Path.home() / ".relia-data")
    PLAYBOOK_DIR: Path = Field(default_factory=lambda: Path.cwd() / ".relia-playbooks")

    # Schema directory (for refresh)
    SCHEMA_DIR: Path = Field(default_factory=lambda: Path.cwd() / "backend" / "schemas")

    # Stale schema threshold (days)
    STALE_SCHEMA_DAYS: int = Field(7, validation_alias="RELIA_STALE_SCHEMA_DAYS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate a global settings object
settings = CLISettings()
