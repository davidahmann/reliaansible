"""
Configuration for Relia OSS Backend, using environment variables with sensible defaults.
"""
from pathlib import Path
from typing import Optional
import logging
import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Import secrets manager
from .secrets import initialize_secrets, SecretBackend

# Configure module logger
logger = logging.getLogger(__name__)

# Initialize secrets backend
initialize_secrets(os.getenv("RELIA_SECRET_BACKEND", SecretBackend.ENV))

class Settings(BaseSettings):
    # Environment variables configuration
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore"
    )
    
    # Environment
    ENV: str = Field("dev", validation_alias="RELIA_ENV")
    
    # Security settings
    JWT_SECRET: Optional[str] = Field(None, validation_alias="RELIA_JWT_SECRET")
    ENFORCE_HTTPS: bool = Field(True, validation_alias="RELIA_ENFORCE_HTTPS")
    SECURE_COOKIES: bool = Field(True, validation_alias="RELIA_SECURE_COOKIES")
    HSTS_ENABLED: bool = Field(True, validation_alias="RELIA_HSTS_ENABLED")
    HSTS_MAX_AGE: int = Field(31536000, validation_alias="RELIA_HSTS_MAX_AGE")  # 1 year in seconds
    
    # LLM backend choice: 'openai' or 'bedrock'
    RELIA_LLM: str = Field("openai", validation_alias="RELIA_LLM")

    # Directories
    BASE_DIR: Path = Path(__file__).parent
    SCHEMA_DIR: Path = BASE_DIR / "schemas"
    PLUGIN_DIR: Path = BASE_DIR / "plugins"
    PLAYBOOK_DIR: Path = Path(__file__).parent.parent / ".relia-playbooks"
    DATA_DIR: Path = Field(Path(__file__).parent.parent / ".relia-data", validation_alias="RELIA_DATA_DIR")

    # Service settings
    API_TIMEOUT: int = Field(30, validation_alias="RELIA_API_TIMEOUT")
    MAX_CONTENT_LENGTH: int = Field(5 * 1024 * 1024, validation_alias="RELIA_MAX_CONTENT_LENGTH")  # 5MB
    RATE_LIMIT: int = Field(60, validation_alias="RELIA_RATE_LIMIT")  # Requests per minute
    
    # Task settings
    TASK_MAX_WORKERS: int = Field(4, validation_alias="RELIA_TASK_MAX_WORKERS")
    TASK_CLEANUP_HOURS: int = Field(24, validation_alias="RELIA_TASK_CLEANUP_HOURS")

    # Database settings
    DB_ENABLED: bool = Field(True, validation_alias="RELIA_DB_ENABLED")
    COLLECT_TELEMETRY: bool = Field(True, validation_alias="RELIA_COLLECT_TELEMETRY")
    COLLECT_FEEDBACK: bool = Field(True, validation_alias="RELIA_COLLECT_FEEDBACK")
    COLLECT_LLM_USAGE: bool = Field(True, validation_alias="RELIA_COLLECT_LLM_USAGE")

    # Monitoring settings
    MONITORING_ENABLED: bool = Field(True, validation_alias="RELIA_MONITORING_ENABLED")
    HEALTH_CHECK_INTERVAL: int = Field(60, validation_alias="RELIA_HEALTH_CHECK_INTERVAL")  # Seconds
    METRICS_RETENTION_DAYS: int = Field(7, validation_alias="RELIA_METRICS_RETENTION_DAYS")
    ALERT_HISTORY_SIZE: int = Field(1000, validation_alias="RELIA_ALERT_HISTORY_SIZE")
    
    # Email notifications for alerts
    EMAIL_ENABLED: bool = Field(False, validation_alias="RELIA_EMAIL_ENABLED")
    EMAIL_HOST: Optional[str] = Field(None, validation_alias="RELIA_EMAIL_HOST")
    EMAIL_PORT: int = Field(465, validation_alias="RELIA_EMAIL_PORT")
    EMAIL_USERNAME: Optional[str] = Field(None, validation_alias="RELIA_EMAIL_USERNAME")
    EMAIL_PASSWORD: Optional[str] = Field(None, validation_alias="RELIA_EMAIL_PASSWORD")
    EMAIL_FROM: str = Field("alerts@relia.local", validation_alias="RELIA_EMAIL_FROM")
    EMAIL_TO: str = Field("admin@relia.local", validation_alias="RELIA_EMAIL_TO")
    BASE_URL: str = Field("http://localhost:8000", validation_alias="RELIA_BASE_URL")
    
    # Version information
    VERSION: str = Field("0.1.0", validation_alias="RELIA_VERSION")

    # Validation parameters
    STALE_SCHEMA_DAYS: int = Field(7, validation_alias="RELIA_STALE_SCHEMA_DAYS")

    @field_validator("RELIA_LLM")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        if v not in ["openai", "bedrock"]:
            raise ValueError("RELIA_LLM must be 'openai' or 'bedrock'")
        return v

    @field_validator("ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in ["dev", "test", "prod"]:
            raise ValueError("ENV must be one of 'dev', 'test', 'prod'")
        return v

    @field_validator("PLAYBOOK_DIR", "DATA_DIR")
    @classmethod
    def create_directories(cls, v: Path) -> Path:
        """Ensure necessary directories exist"""
        if not v.exists():
            v.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {v}")
        return v

# Instantiate a global settings object
settings = Settings()