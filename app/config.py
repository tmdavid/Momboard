"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App settings loaded from environment / .env file."""

    app_name: str = "MomBoard"
    version: str = "0.2.0"
    env: str = "development"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/momboard.db"

    # Auth
    session_secret: str = "change-me-in-production"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model_normalizer: str = "gpt-5-mini"
    llm_model_tagger: str = "gpt-5-mini"
    llm_model_analyst: str = "gpt-5-mini"
    llm_model_synthesizer: str = "gpt-5-mini"

    # LLM backend selection: "openai", "local" (Ollama), or "bedrock"
    llm_backend: str = "openai"
    llm_base_url: str = ""  # Required when llm_backend=local (e.g. http://ollama:11434)
    llm_local_flavor: str = "ollama"  # Local backend flavor
    llm_local_model: str = "qwen3:8b"  # Default model for all agents when backend=local
    llm_local_timeout: float = 300.0  # Per-request timeout for slower local inference
    llm_max_context: int = 32768  # Context window budget (tokens) — drives chunking

    # Bedrock (LLM_BACKEND=bedrock)
    # Credentials come from the standard AWS provider chain (instance role, SSO, env);
    # no access keys are stored here by design. For strict data residency, use an EU
    # region plus the "eu." cross-Region inference profile (default below) and a Bedrock
    # VPC endpoint so inference never leaves the account's EU footprint.
    aws_region: str = "eu-central-1"
    # Cheapest current-generation Anthropic model, EU-resident inference profile.
    bedrock_model_default: str = "eu.anthropic.claude-haiku-5-5"
    bedrock_timeout: float = 120.0  # Per-request timeout for Bedrock Converse calls
    # Per-agent overrides. Empty => fall back to bedrock_model_default.
    # Pipeline agents:
    bedrock_model_normalizer: str = ""
    bedrock_model_tagger: str = ""
    bedrock_model_analyst: str = ""
    bedrock_model_synthesizer: str = ""
    bedrock_model_hypothesis_linker: str = ""
    # Free-form (generate()) features:
    bedrock_model_chat: str = ""
    bedrock_model_corpus_chat: str = ""
    bedrock_model_brief: str = ""
    bedrock_model_digest: str = ""
    bedrock_model_persona: str = ""
    bedrock_model_simulator: str = ""
    bedrock_model_lens: str = ""
    bedrock_model_drift_checker: str = ""

    # Worker
    worker_poll_interval: float = 2.0
    worker_max_retries: int = 3
    worker_concurrency: int = 1  # Number of jobs processed concurrently (asyncio)

    # T31: Digest Slack delivery
    slack_webhook_url: str = ""

    # T24: Google Drive polling
    gdrive_folder_id: str = ""
    gdrive_service_account_json: str = ""
    gdrive_poll_interval_minutes: int = 30

    # T41: Staleness thresholds (days)
    staleness_fresh_days: int = 90
    staleness_aging_days: int = 180

    # T36: Vexa meeting bot integration (disabled by default)
    vexa_base_url: str = ""
    vexa_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
