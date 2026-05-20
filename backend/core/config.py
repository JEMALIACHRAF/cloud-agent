"""Central settings — Cloud Agent v2."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    default_model: str = "gpt-4o"
    fast_model: str = "gpt-4o-mini"          # classifier, detector — moins cher

    # Persistence
    audit_log_path: str = "audit.jsonl"
    sqlite_db_path: str = "agent_memory.db"  # LangGraph checkpointer
    redis_url: str = ""                       # optionnel — InfraMemory cache

    # Feature flags
    dry_run_default: bool = False
    proactive_scan_enabled: bool = True
    proactive_scan_interval_minutes: int = 30


settings = Settings()
