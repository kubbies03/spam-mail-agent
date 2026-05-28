from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DISTILBERT_MODEL_DIR = BASE_DIR / "models" / "distilbert_multilingual"
LEGACY_DISTILBERT_MODEL_DIR = BASE_DIR / "docs" / "22590"


class Settings(BaseSettings):
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    data_dir: Path = BASE_DIR / "data"
    model_dir: Path = BASE_DIR / "models"
    log_dir: Path = BASE_DIR / "logs"

    gmail_imap_host: str = "imap.gmail.com"
    gmail_imap_port: int = 993
    gmail_user: str = ""
    gmail_app_password: str = ""
    gmail_folders: str = "INBOX,[Gmail]/Spam"
    poll_interval_seconds: int = 60
    max_concurrency: int = 4

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'spam_agent.db'}"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 86400

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    llm_timeout_seconds: int = 20

    virustotal_api_key: str = ""
    classifier_threshold: float = Field(default=0.82, ge=0, le=1)
    phishing_escalation_threshold: float = Field(default=0.50, ge=0, le=1)
    spam_escalation_threshold: float = Field(default=0.65, ge=0, le=1)
    url_analysis_limit: int = Field(default=8, ge=1, le=50)
    virustotal_enabled: bool = True
    virustotal_decisive_threshold: float = Field(default=0.75, ge=0, le=1)
    virustotal_cooldown_seconds: int = Field(default=900, ge=0)
    gemini_enabled: bool = True
    gemini_cooldown_seconds: int = Field(default=900, ge=0)
    known_sender_domains: str = (
        "facebookmail.com,mail.instagram.com,linkedin.com,mail.linkedin.com,github.com,"
        "notifications.github.com,noreply.github.com,slack.com,notifications.slack.com,"
        "atlassian.net,info.atlassian.com,jira.atlassian.com,accounts.google.com,"
        "google.com,youtube.com,discord.com,mail.discord.com,x.com,twitter.com"
    )
    distilbert_model_dir: Path = Field(
        default=DEFAULT_DISTILBERT_MODEL_DIR,
        validation_alias="DISTILBERT_MODEL_DIR",
    )
    suspicious_tlds: set[str] = {"zip", "mov", "top", "xyz", "click", "quest", "country"}
    trusted_domains: set[str] = {"gmail.com", "outlook.com", "yahoo.com", "icloud.com"}

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.data_dir.is_absolute():
        settings.data_dir = (BASE_DIR / settings.data_dir).resolve()
    if not settings.model_dir.is_absolute():
        settings.model_dir = (BASE_DIR / settings.model_dir).resolve()
    if not settings.log_dir.is_absolute():
        settings.log_dir = (BASE_DIR / settings.log_dir).resolve()
    if not settings.distilbert_model_dir.is_absolute():
        settings.distilbert_model_dir = (BASE_DIR / settings.distilbert_model_dir).resolve()
    if not settings.distilbert_model_dir.exists() and LEGACY_DISTILBERT_MODEL_DIR.exists():
        settings.distilbert_model_dir = LEGACY_DISTILBERT_MODEL_DIR.resolve()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings
