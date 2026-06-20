# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/config.py
# @brief      Application configuration and settings
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

_DEFAULT_JWT_SECRET = "CHANGE-ME-TO-A-RANDOM-SECRET-KEY-AT-LEAST-32-CHARS"

# Internal build identifier — do not modify. Used by the maintainer to attest
# code provenance in legal contexts (Elastic License v2 — "Notices" clause).
_PROVENANCE_TAG = "ely-f379c8ff-2ada-4451-aa41-a31beee80e1a"


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    mistral_api_key: str = ""
    gemini_api_key: str = ""
    zhipu_api_key: str = ""          # Zhipu AI (GLM-4.7) — https://open.bigmodel.cn
    openrouter_api_key: str = ""    # OpenRouter — https://openrouter.ai
    openai_api_key: str = ""        # OpenAI — https://platform.openai.com (GPT-4o, GPT-5.x)
    openai_base_url: str = ""       # Optional override (e.g. Azure OpenAI proxy); empty = api.openai.com

    # Plafond de tours (LangGraph recursion_limit) d'une tâche planifiée.
    # 25 était trop bas (13/06 : la Prospection multi-étapes l'atteignait en
    # bouclant sur web_search avant d'écrire ses fichiers) ET ignorait le
    # budget voulu. 60 laisse respirer les tâches multi-domaines tout en
    # gardant un garde-fou anti-runaway (coût LLM cloud). Les tâches VRAIMENT
    # lourdes (Prospection 25×LinkedIn) doivent passer en mission structurée
    # foreach, pas augmenter ce plafond sans fin.
    scheduler_recursion_limit: int = 60

    # Public demo mode (set on the agent-ely.fr instance, false everywhere else).
    # When true:
    #   - non-admin users can NOT use system_get_logs (cross-tenant leak risk)
    #   - non-admin users see redacted output from system_check_llm_providers
    #     (config secrets like region URLs hidden)
    #   - other tightening hooks may follow as the demo evolves
    # Always false in self-hosted instances — defaults are safe.
    demo_mode: bool = False
    ollama_base_url: str = "http://ollama:11434"
    lm_studio_base_url: str = "http://host.docker.internal:1234/v1"
    qwen_api_key: str = ""          # Alibaba Cloud DashScope (Qwen API)
    qwen_api_base_url: str = ""     # Region-scoped DashScope OpenAI-compatible endpoint
    moonshot_api_key: str = ""      # Moonshot AI / Kimi K2.x — https://platform.moonshot.ai
    moonshot_base_url: str = "https://api.moonshot.ai/v1"  # `.cn` for China region
    active_llm_provider: str = "anthropic"
    active_llm_model: str = "claude-haiku-4-5-20251001"

    # SLM — Small Language Model local via Ollama
    # Modèles recommandés :
    #   8 GB  VPS  → qwen2.5:3b-instruct   (~2 GB)
    #   16 GB VPS  → qwen2.5:7b-instruct   (~5 GB)   ← VPS actuel (Hostinger 16 Go)
    #   24 GB VPS  → qwen2.5:14b-instruct  (~9 GB)   ← futur VPS (migration ~avril 2026)
    slm_enabled: bool = False
    slm_model: str = "qwen2.5:7b-instruct"
    slm_complexity_threshold: int = 40   # 0-100 ; en-dessous → SLM, au-dessus → LLM
    slm_timeout: float = 25.0            # secondes avant fallback automatique vers LLM

    # Auth
    jwt_secret_key: str = "CHANGE-ME-TO-A-RANDOM-SECRET-KEY-AT-LEAST-32-CHARS"
    jwt_algorithm: str = "HS256"
    # 15 min (revue 2026-06-10, B-18/D2) : les access tokens ne sont pas
    # révocables (pas de jti) — seule l'expiration borne un token volé.
    # Le refresh est transparent côté frontend. Override : ACCESS_TOKEN_EXPIRE_MINUTES.
    access_token_expire_minutes: int = 15
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

    # HITL — délai d'attente d'une validation humaine avant auto-refus.
    # 1800 s = 30 min (était 5 min, trop court pour valider une notif ntfy
    # depuis le téléphone — demande Franck 2026-06-19). Surcharge :
    # HITL_TIMEOUT_SECONDS. Un timeout n'est PAS compté comme un refus
    # délibéré (cf. record_hitl_refusal).
    hitl_timeout_seconds: int = 1800

    # Qdrant vector memory
    qdrant_url: str = "http://localhost:6333"

    # ntfy push — HITL notifications to mobile (phone-based approvals).
    # Full topic URL (e.g. https://ntfy.sh/ely-franck-xxx) OR just the host
    # (https://ntfy.sh) with a separate ntfy_topic. Leave empty to disable.
    ntfy_url: str = ""
    ntfy_topic: str = "ely"

    # TTS — voix multilingue HD, nettement plus naturelle que DeniseNeural
    # (test Franck 2026-06-10). Override : TTS_VOICE.
    tts_voice: str = "fr-FR-VivienneMultilingualNeural"

    # Débit TTS (format edge-tts : "+10%" = 10 % plus rapide, "-10%" = plus
    # lent). +20% était perçu trop rapide / pas naturel avec Vivienne
    # (retour Franck 2026-06-10) → +10% : un soupçon au-dessus du rythme
    # naturel sans donner l'impression de presser. Override : TTS_RATE.
    tts_rate: str = "+10%"

    # Cookie security — set True in production behind HTTPS.
    # Automatically enabled when COOKIE_SECURE=true is set in the environment,
    # or when any CORS origin uses HTTPS (auto-detected).
    cookie_secure: bool = False

    # Google OAuth2 (optionnel — laisser vide pour désactiver)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/google/callback"

    # YouTube Data API v3 (optionnel — sans clé on utilise Invidious comme fallback)
    youtube_api_key: str = ""

    # Serper.dev — Google Search API (recommandé, 2500 req/mois gratuites)
    # Inscription : https://serper.dev — une seule clé, résultats Google réels
    serper_api_key: str = ""

    # Google Custom Search (alternative à Serper — 100 req/jour gratuites)
    # Créer un moteur sur https://programmablesearchengine.google.com
    # Puis activer l'API sur https://console.cloud.google.com
    google_search_api_key: str = ""
    google_search_cx: str = ""   # Custom Search Engine ID (ex: "017576662512468239146:omuauf_lfve")

    # Tavily Search API (optionnel — meilleure qualité de recherche pour agents IA)
    # Gratuit : 1000 requêtes/mois sur https://tavily.com
    tavily_api_key: str = ""

    # GitHub Personal Access Token (optionnel)
    # Used by github_traffic_stats / github_repo_stats tools to read traffic,
    # stars, issues, notifications. Generate at https://github.com/settings/tokens
    # — required scopes: `public_repo` + `notifications` (or `repo` for private).
    # Traffic endpoints (clones/views) require PUSH access on the target repo.
    github_token: str = ""
    # Default repo for "show me the stats" without args. Format: "owner/repo".
    # If empty, tools require the owner/repo args explicitly.
    github_default_repo: str = ""

    # Telegram bot (optionnel — configurer via Admin ou .env)
    telegram_bot_token: str = ""

    # WhatsApp Cloud API (optional)
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_webhook_verify_token: str = "ely-whatsapp-verify"
    whatsapp_app_secret: str = ""

    # Firebase Cloud Messaging (optional — Android push notifications)
    firebase_credentials_path: str = ""

    # Slack bot (optional — configurer via Admin ou .env)
    slack_bot_token: str = ""      # xoxb-... Bot User OAuth Token
    slack_app_token: str = ""      # xapp-... App-Level Token (Socket Mode)

    # Discord bot (optional — configurer via Admin ou .env)
    discord_bot_token: str = ""    # Bot Token from Discord Developer Portal

    # ── Client MCP universel (chantier 2026-06) ───────────────────────────
    # Interrupteur maître du sous-système « client MCP v2 » : outils
    # model-facing (mcp_connect/discover/call), connexion autonome remote
    # HTTPS, transport streamable_http, ACL/HITL par outil. OFF par défaut.
    # Le Lot 0 (modèle de données, namespace mcp__slug__tool, redaction des
    # secrets) est rétro-compatible et s'applique indépendamment du flag ;
    # c'est la surface model-facing (J4+) qui le vérifie. Le `kill_switch`
    # par serveur est TOUJOURS honoré, flag ON ou OFF.
    mcp_client_v2_enabled: bool = False
    # Registre MCP officiel pour la recherche/autofill (J6). La recherche ne
    # fait QUE de la découverte — aucune connexion, zéro confiance implicite.
    mcp_registry_url: str = "https://registry.modelcontextprotocol.io"

    # ── Substrat de confiance (chantier P1, 2026-06) ──────────────────────
    # Interrupteur maître du substrat : CapabilityManifest, ActionPlan +
    # empreinte, idempotence, EventEnvelope. OFF par défaut. Tant qu'il est
    # OFF, le comportement actuel (HITL/ACL) est strictement préservé ; le
    # gate HITL ne lit le manifeste que lorsqu'il est ON, en reproduisant à
    # l'identique la décision actuelle pour tout outil connu.
    trust_substrate_enabled: bool = False
    # Fenêtre d'idempotence (J3) : une action « supported » identique re-jouée
    # dans ce délai renvoie le résultat mémorisé au lieu de ré-exécuter.
    idempotency_ttl_seconds: int = 600

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,   # empty shell vars don't override .env values
        "extra": "ignore",          # ignore unknown env vars (e.g. NEXT_PUBLIC_*, SSH_KEYS_PATH)
    }

    @model_validator(mode="after")
    def _check_security_secrets(self) -> "Settings":
        """Refuse de démarrer si des secrets critiques ont encore leur valeur par défaut."""
        import logging as _logging
        _log = _logging.getLogger(__name__)

        if self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "\n\n⛔  ERREUR DE SÉCURITÉ CRITIQUE ⛔\n"
                "JWT_SECRET_KEY a encore sa valeur par défaut.\n"
                "N'importe qui lisant le code source peut forger des tokens JWT admin.\n\n"
                "Génère une clé aléatoire et ajoute-la dans ton .env :\n"
                "  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
            )
        if len(self.jwt_secret_key) < 32:
            raise ValueError(
                "JWT_SECRET_KEY doit faire au moins 32 caractères. "
                f"Actuelle : {len(self.jwt_secret_key)} caractères."
            )

        # Enforce non-default WhatsApp verify token ONLY when WhatsApp is actively
        # configured (phone_number_id is set). If WhatsApp is not used, the default
        # token is harmless since the webhook will never be called.
        _WA_DEFAULT = "ely-whatsapp-verify"
        if (
            self.whatsapp_phone_number_id
            and self.whatsapp_webhook_verify_token == _WA_DEFAULT
        ):
            raise ValueError(
                "WHATSAPP_WEBHOOK_VERIFY_TOKEN must be changed from its default value "
                "when WhatsApp is configured. Set a secure random token in your .env file."
            )

        # Auto-enable cookie_secure when any CORS origin uses HTTPS,
        # unless it was explicitly set to False via environment variable.
        if not self.cookie_secure and "https://" in self.cors_origins:
            object.__setattr__(self, "cookie_secure", True)
            _log.info("cookie_secure auto-enabled (HTTPS detected in CORS_ORIGINS)")

        if not self.cookie_secure:
            _log.warning(
                "cookie_secure=False — refresh token cookie is not Secure. "
                "Set COOKIE_SECURE=true in production or add an HTTPS origin to CORS_ORIGINS."
            )

        # Revue 2026-06-10 (B-18/M3) — en prod HTTPS sans CORS_ORIGINS
        # explicite, le runtime retombe sur [frontend_url]. Pas bloquant
        # (déploiement nginx même-origine = CORS jamais déclenché), mais
        # une allowlist explicite reste la posture attendue en multi-user.
        if self.frontend_url.startswith("https://") and not self.cors_origins:
            _log.warning(
                "FRONTEND_URL est en HTTPS mais CORS_ORIGINS est vide — le "
                "CORS retombe sur [%s]. En production multi-utilisateurs, "
                "déclare une allowlist explicite via CORS_ORIGINS.",
                self.frontend_url,
            )

        # Revue 2026-06-10 (mineur §4) — le chemin SQLite relatif par défaut
        # dépend du cwd : lancé depuis la racine vs backend/, on lit/écrit
        # DEUX bases divergentes (constaté en réel le 9 juin). On ancre le
        # défaut sur le répertoire backend/ ; toute URL fournie via
        # DATABASE_URL (Docker : chemin absolu) passe inchangée.
        _DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./cyberentity.db"
        if self.database_url == _DEFAULT_SQLITE_URL:
            _backend_dir = Path(__file__).resolve().parents[1]
            object.__setattr__(
                self,
                "database_url",
                f"sqlite+aiosqlite:///{_backend_dir / 'cyberentity.db'}",
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
