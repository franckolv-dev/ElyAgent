# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/main.py
# @brief      FastAPI application entry point
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================

# ── Logging configuration (FIRST, before any app import) ────────────────────
# Reason : without this, our `logger = logging.getLogger(__name__)` calls
# in app modules don't propagate to stdout/stderr of the container — only
# uvicorn's own logger writes there. Result : every `logger.warning(...)` /
# `logger.error(...)` from our code is invisible in `docker logs`, which
# made every silent crash impossible to diagnose during 2026-05-08.
#
# ``force=True`` overrides any previous logging.basicConfig call (uvicorn
# sets one of its own when it starts). The root logger is then wired with
# a StreamHandler writing to stderr, so child loggers propagate up by
# default. Format includes timestamp, level, logger name, message — enough
# to grep ``ERROR`` / ``Traceback`` later.
import logging as _logging
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
# Bump our own loggers to INFO explicitly (defensive — basicConfig already
# sets the root, but a third-party library may have lowered our package).
_logging.getLogger("app").setLevel(_logging.INFO)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.models import system_config as _   # ensure SystemConfig table is registered
from app.models import scheduled_task as __  # ensure ScheduledTask table is registered
from app.models import skill_preference as ___ # ensure SkillPreference table is registered
from app.models import watch_task as _watch_task  # ensure WatchTask table is registered
from app.models import usage_log as _usage_log    # ensure UsageLog table is registered
from app.models import note as _note              # ensure Note table is registered
from app.models import feedback as _feedback      # ensure Feedback table is registered
from app.models import mcp_server as _mcp_server  # ensure MCPServer table is registered
from app.models import llm_instance as _llm_instance  # ensure LLMInstance table is registered
from app.models import community_skill as _community_skill  # ensure CommunitySkill table
from app.models import vault as _vault_models      # ensure VaultConfig + VaultEntry tables
from app.models import conversation as _conversation  # ensure Conversation + Message tables
from app.models import user_memory as _user_memory    # ensure UserMemoryLog + UserProfile tables
from app.models import arena as _arena                 # ensure ArenaMatch + ArenaElo tables
from app.routers import auth, chat, hosts, admin, health
from app.routers import validation, tts, scheduler as scheduler_router
from app.routers import google as google_router
from app.routers import skills as skills_router
from app.routers import transcribe as transcribe_router
from app.routers import whatsapp_webhook as whatsapp_router
from app.routers import whatsapp_web as whatsapp_web_router
from app.routers import channels as channels_router
from app.routers import missions as missions_router
from app.routers import upload as upload_router
from app.routers import attachments as attachments_router
from app.routers import watchdog as watchdog_router
from app.routers import analytics as analytics_router
from app.routers import audit as audit_router
from app.routers.device_token import router as device_token_router
from app.routers import feedback as feedback_router
from app.routers import mcp as mcp_router
from app.routers import telegram_webhook as telegram_webhook_router
from app.routers import vault as vault_router
from app.routers import conversations as conversations_router
from app.routers import knowledge as knowledge_router
from app.routers import settings_llm as settings_llm_router
from app.routers import settings_routing as settings_routing_router
from app.routers import marketplace as marketplace_router
from app.routers import setup as setup_router
from app.routers import voice as voice_router
from app.routers import arena as arena_router
from app.routers.desktop import ws_router as desktop_ws_router, api_router as desktop_api_router
from app.routers.browser_extension import ws_router as bext_ws_router, api_router as bext_api_router
from app.routers import extension_tokens as extension_tokens_router
from app.routers import learning_report as learning_report_router
from app.routers import user_state as user_state_router
from app.middleware.rate_limit import setup_rate_limiter
from app.services.memory_manager import get_memory_manager
from app.services.fts_store import get_fts_store
from app.services.messages_fts_store import get_messages_fts_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging as _logging
    # Make sure INFO-level logs from app.* modules are visible (default
    # uvicorn config leaves non-uvicorn loggers at WARNING). We need INFO
    # for the ⏱ TIMING[...] diagnostic lines from the agent pipeline.
    _logging.getLogger("app").setLevel(_logging.INFO)
    _startup_logger = _logging.getLogger("app.startup")

    # Install the in-memory log ring buffer so the `system_get_logs`
    # tool can let the agent introspect its own runtime. Must be done
    # BEFORE any other module logs anything we want captured.
    from app.services.log_buffer import install_handler as _install_log_buffer
    _install_log_buffer()

    # Register all built-in skills BEFORE the agent graph is built
    from app.skills.builtin import register_all
    register_all()

    await init_db()

    # Load LLM provider/model/key overrides from DB into in-memory runtime
    from app.services.llm_provider import load_llm_settings_from_db
    await load_llm_settings_from_db()

    # Load mono-agent toggle (admin: Paramètres → Routage)
    from app.services.mono_agent import load_mono_agent_flag
    await load_mono_agent_flag()

    # Load learned routing keywords cache (self-improving router)
    from app.services.routing_learning import reload_cache as _reload_routing_cache
    await _reload_routing_cache()

    await get_memory_manager().init_collections()
    await get_fts_store().init()
    # Sprint 1 — Memory recall: messages_fts indexes the literal messages
    # of every conversation for cross-session retrieval. Separate from
    # memory_fts (which indexes extracted facts).
    await get_messages_fts_store().init()
    # Auto-indexer event hook (SQLAlchemy after_insert on Message)
    from app.services.messages_fts_indexer import install_indexer as _install_msg_indexer
    _install_msg_indexer()

    # Init RAG knowledge collection
    from app.services.rag_service import get_rag_service
    await get_rag_service().init_collection()

    # Start Telegram bot if configured
    from app.channels.telegram_bot import start_telegram_bot, stop_telegram_bot
    try:
        await start_telegram_bot()
    except Exception:
        _startup_logger.warning("Telegram bot failed to start — channel disabled", exc_info=True)

    # Start Slack bot if configured
    from app.channels.slack_bot import start_slack_bot, stop_slack_bot
    try:
        await start_slack_bot()
    except Exception:
        _startup_logger.warning("Slack bot failed to start — channel disabled", exc_info=True)

    # Start Discord bot if configured
    from app.channels.discord_bot import start_discord_bot, stop_discord_bot
    try:
        await start_discord_bot()
    except Exception:
        _startup_logger.warning("Discord bot failed to start — channel disabled", exc_info=True)

    # Load WhatsApp linked users
    from app.channels.whatsapp import load_linked_whatsapp_users
    try:
        await load_linked_whatsapp_users()
    except Exception:
        _startup_logger.warning("WhatsApp linked users failed to load", exc_info=True)

    # Resume WhatsApp Web (neonize) sessions that were active before restart.
    # Non-blocking: if neonize isn't installed or fails to init, the channel
    # is simply disabled — the Meta Cloud channel and other channels keep working.
    try:
        from app.channels.whatsapp_web import load_existing_sessions
        await load_existing_sessions()
    except Exception:
        _startup_logger.warning("WhatsApp Web sessions failed to resume", exc_info=True)

    # Start scheduled tasks
    from app.services.scheduler import load_and_schedule_tasks, stop_scheduler
    try:
        await load_and_schedule_tasks()
    except Exception:
        _startup_logger.warning("Scheduler failed to load tasks", exc_info=True)

    # Start watchdog service
    from app.services.watchdog_service import load_and_schedule_watch_tasks, stop_watchdog
    try:
        await load_and_schedule_watch_tasks()
    except Exception:
        _startup_logger.warning("Watchdog failed to start", exc_info=True)

    # Ensure uploads directory exists
    from app.routers.upload import UPLOADS_DIR
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Start headless browser (graceful no-op if playwright is not installed)
    from app.services.browser_manager import get_browser_manager
    try:
        await get_browser_manager().start()
    except Exception:
        _startup_logger.warning("Browser manager failed to start — web browsing disabled", exc_info=True)

    # Load external MCP servers (graceful: no crash if none configured or SDK absent)
    from app.services.mcp_client import get_mcp_client_manager
    try:
        await get_mcp_client_manager().reload_all()
    except Exception:
        _startup_logger.warning("MCP client manager failed to load", exc_info=True)

    # Warm up SLM — loads model into RAM so the first real request has no cold-start
    from app.services.slm_warmup import warmup_slm
    await warmup_slm()

    # Load approved community skills into the skill registry
    from app.services.marketplace import get_marketplace_service
    try:
        await get_marketplace_service().load_approved_skills()
    except Exception:
        _startup_logger.warning("Community skills failed to load", exc_info=True)

    # Compile and register all sub-agent subgraphs
    from app.agent.sub_agents.registry import get_sub_agent_registry
    from app.agent.sub_agents.config import ALL_AGENTS
    _sub_registry = get_sub_agent_registry()
    for _agent_config in ALL_AGENTS:
        _sub_registry.register(_agent_config)
    import logging as _logging
    _logging.getLogger(__name__).info(
        "Sub-agent registry ready: %d agents compiled (%s)",
        len(_sub_registry),
        ", ".join(_sub_registry.list_names()),
    )

    # Schedule vault auto-lock (every 5 minutes — locks idle vaults after AUTO_LOCK_MINUTES)
    from app.services.vault_service import get_vault_service
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _vault_scheduler = AsyncIOScheduler()
    _vault_scheduler.add_job(
        get_vault_service().auto_lock_expired,
        trigger="interval",
        minutes=5,
        id="vault_auto_lock",
    )
    # Schedule OAuth state cleanup every 5 min to prevent memory leak (SEC-3)
    from app.routers.google import _cleanup_expired_states as _cleanup_oauth_states
    _vault_scheduler.add_job(
        _cleanup_oauth_states,
        trigger="interval",
        minutes=5,
        id="oauth_state_cleanup",
    )
    # Evict stale entries from the credential store every hour (SEC-1)
    from app.services.credential_store import get_credential_store as _get_cred_store
    _vault_scheduler.add_job(
        _get_cred_store().evict_expired,
        trigger="interval",
        hours=1,
        id="credential_store_eviction",
    )
    # Schedule auto-indexing of WatchedFolder entries every hour.
    # The service no-ops if the user's ELY Desktop daemon is offline, so
    # the cron is safe even when no daemon is connected.
    from app.services.auto_indexer import scan_all_enabled as _scan_watched_folders
    _vault_scheduler.add_job(
        _scan_watched_folders,
        trigger="interval",
        hours=1,
        id="watched_folders_autoindex",
        # Skip if a previous tick is still running (large folder = long scan)
        max_instances=1,
        coalesce=True,
    )

    _vault_scheduler.start()

    # Schedule user memory consolidation — twice a day to keep the backlog
    # manageable (one run at 03:00 + a booster at 15:00). At ~80 new raw
    # facts per active day, a single 2000-cap run is more than enough but
    # the afternoon pass prevents long gaps if the nightly run fails.
    from app.services.memory_service import consolidate_all_users
    _memory_scheduler = AsyncIOScheduler()
    _memory_scheduler.add_job(
        consolidate_all_users,
        trigger="cron",
        hour=3,
        minute=0,
        id="memory_consolidation_night",
    )
    _memory_scheduler.add_job(
        consolidate_all_users,
        trigger="cron",
        hour=15,
        minute=0,
        id="memory_consolidation_afternoon",
    )
    # Schedule nightly Qdrant snapshot backup at 2:00 AM (ARCH-2)
    from app.services.qdrant_backup import run_backup as _qdrant_backup
    _memory_scheduler.add_job(
        _qdrant_backup,
        trigger="cron",
        hour=2,
        minute=0,
        id="qdrant_backup",
    )
    # Sprint 3.7 Jalon 4 — LLM-as-judge post-mission critic.
    # Scans terminal missions (failed/aborted/completed) without a
    # critic_run_at every 5 minutes. Policy (design note §4.1) :
    #   - failed / aborted → 100% sampled
    #   - completed        → 1/5 sampled (deterministic on mission_id hash)
    # Disable via env CRITIC_DISABLED=true on weak setups.
    from app.services.learning import run_pending_critiques as _mc_run
    _memory_scheduler.add_job(
        _mc_run,
        trigger="interval",
        minutes=5,
        id="mission_critic_loop",
    )
    # Purge expired revoked tokens nightly at 4:00 AM (ARCH-3)
    async def _purge_revoked_tokens():
        from datetime import datetime
        from sqlalchemy import delete
        from app.models.revoked_token import RevokedToken as _RT
        from app.database import async_session as _session
        async with _session() as _db:
            result = await _db.execute(
                delete(_RT).where(_RT.expires_at < datetime.utcnow())
            )
            await _db.commit()
            _startup_logger.info(
                "[auth] purged %d expired revoked tokens", result.rowcount
            )
    _memory_scheduler.add_job(
        _purge_revoked_tokens,
        trigger="cron",
        hour=4,
        minute=0,
        id="purge_revoked_tokens",
    )

    # Mission heartbeat — ticks active missions periodically.
    # See app/services/mission_heartbeat.py for the loop logic.
    from app.services.mission_heartbeat import (
        heartbeat_tick as _mission_heartbeat,
        HEARTBEAT_INTERVAL_SECONDS as _hb_interval,
    )
    _memory_scheduler.add_job(
        _mission_heartbeat,
        trigger="interval",
        seconds=_hb_interval,
        id="mission_heartbeat",
        coalesce=True,        # if missed beats, only run once
        max_instances=1,      # never run two beats concurrently
    )
    _startup_logger.info("[missions] heartbeat scheduled every %ds", _hb_interval)

    # Routing learning — auto-detection des reformulations user (Phase 2).
    # Toutes les 6h. Premier run décalé de 5min (boot calme), coalesce pour
    # éviter les exécutions en parallèle si le précédent tick traîne.
    from app.services.routing_learning import analyze_reformulations_tick
    _memory_scheduler.add_job(
        analyze_reformulations_tick,
        trigger="interval",
        hours=6,
        id="routing_learning_tick",
        coalesce=True,
        max_instances=1,
        next_run_time=None,  # pas d'exécution immédiate au boot
    )
    _startup_logger.info("[routing] learning tick scheduled every 6h")

    _memory_scheduler.start()

    yield

    _memory_scheduler.shutdown(wait=False)
    _vault_scheduler.shutdown(wait=False)
    await stop_scheduler()
    await stop_watchdog()
    await stop_telegram_bot()
    await stop_slack_bot()
    await stop_discord_bot()
    await get_browser_manager().stop()
    # Close mission checkpointer (AsyncSqliteSaver) cleanly so the
    # SQLite WAL is flushed before the container exits.
    try:
        from app.agent.missions.checkpointer import close_mission_checkpointer
        await close_mission_checkpointer()
    except Exception:
        pass


app = FastAPI(
    title="Cyber-Entity Agent API",
    version="0.2.0",
    lifespan=lifespan,
)

def _get_cors_origins() -> list[str]:
    s = get_settings()
    if s.cors_origins:
        return [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    return [s.frontend_url]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_rate_limiter(app)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/ws", tags=["chat"])
app.include_router(hosts.router, prefix="/hosts", tags=["hosts"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
# Validation endpoints — exposed twice:
#   - /validation/*       (legacy path, used by the Android app which talks
#                          directly to the backend without going through nginx)
#   - /api/validation/*   (used by the web UI through Cloudflare Tunnel + nginx,
#                          which only proxies /api/* to the backend)
app.include_router(validation.router)
app.include_router(validation.router, prefix="/api")
app.include_router(tts.router)
app.include_router(google_router.router, prefix="/api")
app.include_router(scheduler_router.router, prefix="/scheduler", tags=["scheduler"])
app.include_router(skills_router.router, prefix="/skills", tags=["skills"])
app.include_router(transcribe_router.router, prefix="/api", tags=["transcribe"])
app.include_router(upload_router.router, prefix="/api", tags=["upload"])
# Attachments (MEDIA: sentinel files served back to the chat UI)
app.include_router(attachments_router.router)
app.include_router(whatsapp_router.router, prefix="/api", tags=["whatsapp"])
# WhatsApp Web bridge (unofficial, QR-paired) — prefix already baked into the router
app.include_router(whatsapp_web_router.router)
# Unified admin API for Telegram / Discord / Slack config from Settings UI
app.include_router(channels_router.router)
# Goal-driven Persistence Loop (Plan→Act→Eval→Replan, Phase 1 skeleton)
app.include_router(missions_router.router)
app.include_router(watchdog_router.router, prefix="/watchdog", tags=["watchdog"])
app.include_router(analytics_router.router, prefix="/analytics", tags=["analytics"])
app.include_router(audit_router.router, prefix="/api", tags=["audit"])
app.include_router(device_token_router)
app.include_router(feedback_router.router)
# Sprint 3.7 V1.5 Jalon 6 — `/api/me/learning-report` (markdown + JSON)
app.include_router(learning_report_router.router, tags=["learning"])
# Sprint 3 Jalon 3 — `/api/me/state` + `/api/me/state/recompute`
app.include_router(user_state_router.router, tags=["learning"])
app.include_router(mcp_router.router, prefix="/admin", tags=["mcp"])
app.include_router(telegram_webhook_router.router, tags=["telegram"])
app.include_router(vault_router.router)
app.include_router(conversations_router.router)
app.include_router(knowledge_router.router, prefix="/api", tags=["knowledge"])
app.include_router(marketplace_router.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(settings_llm_router.router)
app.include_router(settings_routing_router.router)
app.include_router(setup_router.router, prefix="/api", tags=["setup"])
app.include_router(voice_router.router, prefix="/ws", tags=["voice"])
app.include_router(arena_router.router)
app.include_router(desktop_ws_router, prefix="/ws", tags=["desktop"])
app.include_router(desktop_api_router, prefix="/api", tags=["desktop"])
app.include_router(bext_ws_router, prefix="/ws", tags=["browser-extension"])
app.include_router(bext_api_router, prefix="/api", tags=["browser-extension"])
# Long-lived extension tokens (Sprint 0.5) — router self-prefixes with
# /api/extension/tokens, no extra prefix here.
app.include_router(extension_tokens_router.router)
from app.routers import hitl_prefs as _hitl_prefs_router
app.include_router(_hitl_prefs_router.router, prefix="/api")
from app.routers import onboarding as _onboarding_router
app.include_router(_onboarding_router.router, prefix="/api")
# Voice / TTS preferences. The router already self-prefixes with
# `/api/preferences`, so no extra prefix here.
from app.routers import voice_prefs as _voice_prefs_router
app.include_router(_voice_prefs_router.router)
# Tier-aware licence enforcement (Phase 1) — router carries its own /api/licence prefix.
from app.routers import licence as _licence_router
app.include_router(_licence_router.router)

# ── Static files — ELY Desktop binaries ─────────────────────────────────────
import os as _os
_desktop_static = _os.path.join(_os.path.dirname(__file__), "..", "static", "desktop")
if _os.path.isdir(_desktop_static):
    app.mount("/static/desktop", StaticFiles(directory=_desktop_static), name="desktop-static")
