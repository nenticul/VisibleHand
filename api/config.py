"""
Centralised configuration via pydantic-settings.

All runtime configuration flows through the Settings object so there is a
single, validated source of truth. Values are read from environment variables
(or a local .env file) at startup.
"""

import os
from functools import lru_cache
from typing import Literal

# Railway provides postgres:// but SQLAlchemy requires postgresql://
_raw_db_url = os.environ.get("DATABASE_URL", "")
if _raw_db_url.startswith("postgres://"):
    os.environ["DATABASE_URL"] = _raw_db_url.replace("postgres://", "postgresql://", 1)

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field
    _HAS_PYDANTIC_SETTINGS = True
except ImportError:  # graceful fallback if pydantic-settings is missing
    _HAS_PYDANTIC_SETTINGS = False
    import os


if _HAS_PYDANTIC_SETTINGS:

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env", env_file_encoding="utf-8", extra="ignore"
        )

        # ── Database ──────────────────────────────────────────────────────
        database_url: str = Field(
            default="postgresql://postgres:postgres@localhost:5432/visiblehand",
            description="PostgreSQL connection string",
        )
        db_pool_size: int = 10
        db_max_overflow: int = 20
        db_pool_pre_ping: bool = True

        # ── External data sources ─────────────────────────────────────────
        fred_api_key: str = ""
        acled_email: str = ""
        acled_password: str = ""   # account password; generates 24-h OAuth2 tokens
        acled_api_key: str = ""    # legacy static key — ignored when acled_password is set

        # ── Auth & rate limiting ──────────────────────────────────────────
        api_key: str = ""
        rate_limit: str = "120/minute"

        # ── Scoring & NLP ─────────────────────────────────────────────────
        nlp_model: str = "ProsusAI/finbert"
        score_cache_ttl: int = 3600  # seconds
        scoring_rolling_window: int = 10  # years

        # ── Ingestion ─────────────────────────────────────────────────────
        ingestion_hour_utc: int = 2
        ingestion_enabled: bool = True
        http_timeout: float = 30.0
        http_max_retries: int = 3

        # ── Observability ─────────────────────────────────────────────────
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
        environment: Literal["development", "production"] = "development"
        sentry_dsn: str = ""
        prometheus_enabled: bool = True
        structured_logging: bool = False  # JSON logs in production

        # ── NLP model ─────────────────────────────────────────────────────
        nlp_model_dir: str = "models/finbert-onnx"

    @lru_cache
    def get_settings() -> "Settings":
        return Settings()

else:  # minimal shim so the app still boots without pydantic-settings

    class _ShimSettings:
        def __init__(self) -> None:
            self.database_url = os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/visiblehand",
            )
            self.db_pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
            self.db_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
            self.db_pool_pre_ping = True
            self.fred_api_key = os.getenv("FRED_API_KEY", "")
            self.acled_email = os.getenv("ACLED_EMAIL", "")
            self.acled_password = os.getenv("ACLED_PASSWORD", "")
            self.acled_api_key = os.getenv("ACLED_API_KEY", "")
            self.api_key = os.getenv("API_KEY", "")
            self.rate_limit = os.getenv("RATE_LIMIT", "120/minute")
            self.nlp_model = os.getenv("NLP_MODEL", "ProsusAI/finbert")
            self.score_cache_ttl = int(os.getenv("SCORE_CACHE_TTL", "3600"))
            self.scoring_rolling_window = int(os.getenv("SCORING_ROLLING_WINDOW", "10"))
            self.ingestion_hour_utc = int(os.getenv("INGESTION_HOUR_UTC", "2"))
            self.ingestion_enabled = os.getenv("INGESTION_ENABLED", "true").lower() == "true"
            self.http_timeout = float(os.getenv("HTTP_TIMEOUT", "30"))
            self.http_max_retries = int(os.getenv("HTTP_MAX_RETRIES", "3"))
            self.log_level = os.getenv("LOG_LEVEL", "INFO")
            self.environment = os.getenv("ENVIRONMENT", "development")
            self.sentry_dsn = os.getenv("SENTRY_DSN", "")
            self.prometheus_enabled = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"
            self.structured_logging = os.getenv("STRUCTURED_LOGGING", "false").lower() == "true"
            self.nlp_model_dir = os.getenv("NLP_MODEL_DIR", "models/finbert-onnx")

    @lru_cache
    def get_settings() -> "_ShimSettings":
        return _ShimSettings()
