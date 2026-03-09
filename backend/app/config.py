from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    active_llm_provider: str = "anthropic"
    active_llm_model: str = "claude-haiku-4-5-20251001"

    # Auth
    jwt_secret_key: str = "CHANGE-ME-TO-A-RANDOM-SECRET-KEY-AT-LEAST-32-CHARS"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # Database
    database_url: str = "sqlite+aiosqlite:///./cyberentity.db"

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:3000"

    # Rate Limiting
    rate_limit: str = "60/minute"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
