"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App settings loaded from environment / .env file."""

    app_name: str = "MomBoard"
    version: str = "0.1.0"
    env: str = "development"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/momboard.db"

    # Auth
    session_secret: str = "change-me-in-production"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model_normalizer: str = "gpt-4o-mini"
    llm_model_tagger: str = "gpt-4o"
    llm_model_analyst: str = "gpt-4o"
    llm_model_synthesizer: str = "gpt-4o"

    # Worker
    worker_poll_interval: float = 2.0
    worker_max_retries: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
