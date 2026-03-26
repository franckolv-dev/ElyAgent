from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    mistral_api_key: str = ""
    gemini_api_key: str = ""
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
    backend_url: str = "http://localhost:8000"
    # Comma-separated list of allowed CORS origins (overrides frontend_url when set)
    cors_origins: str = ""

    # Rate Limiting
    rate_limit: str = "60/minute"

    # Qdrant vector memory
    qdrant_url: str = "http://localhost:6333"

    # ntfy push notifications (Android HITL)
    ntfy_url: str = ""        # e.g. https://ntfy.sh  or http://ntfy:80
    ntfy_topic: str = "cyberentity"

    # TTS
    tts_voice: str = "fr-FR-DeniseNeural"

    # Cookie security (set True in production behind HTTPS)
    cookie_secure: bool = False

    # Google OAuth2 (optionnel — laisser vide pour désactiver)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/google/callback"

    # YouTube Data API v3 (optionnel — sans clé on utilise Invidious comme fallback)
    youtube_api_key: str = ""

    # Tavily Search API (optionnel — meilleure qualité de recherche pour agents IA)
    # Gratuit : 1000 requêtes/mois sur https://tavily.com
    tavily_api_key: str = ""

    # Telegram bot (optionnel — configurer via Admin ou .env)
    telegram_bot_token: str = ""

    # WhatsApp Cloud API (optional)
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_webhook_verify_token: str = "ely-whatsapp-verify"
    whatsapp_app_secret: str = ""

    # Firebase Cloud Messaging (optional — Android push notifications)
    firebase_credentials_path: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,   # empty shell vars don't override .env values
        "extra": "ignore",          # ignore unknown env vars (e.g. NEXT_PUBLIC_*, SSH_KEYS_PATH)
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
