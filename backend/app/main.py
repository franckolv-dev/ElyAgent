# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/main.py
# @brief      FastAPI application entry point
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
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
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
from app.routers import marketplace as marketplace_router
from app.routers import setup as setup_router
from app.routers import voice as voice_router
from app.routers import arena as arena_router
from app.routers.desktop import ws_router as desktop_ws_router, api_router as desktop_api_router
from app.routers.browser_extension import ws_router as bext_ws_router, api_router as bext_api_router
from app.routers import extension_tokens as extension_tokens_router
from app.routers import api_keys as api_keys_router
from app.routers import learning_report as learning_report_router
from app.routers import user_state as user_state_router
# Sprint 2.5 §2.5.6 — page « Mes mémoires » (parcourir / oublier)
from app.routers import memory as memory_router
# Sprint 4b Phase 3 — autonomous skill_creator admin endpoints
from app.routers import learning_skills as learning_skills_router
# Sprint 4b Phase 5.b — user-facing learned-skills endpoints
from app.routers import me_learning_skills as me_learning_skills_router
from app.middleware.rate_limit import setup_rate_limiter
from app.services.memory_manager import get_memory_manager
from app.services.fts_store import get_fts_store
from app.services.messages_fts_store import get_messages_fts_store


# ─────────────────────────────────────────────────────────────────────────────
# Planificateurs de maintenance — fabriques testables
#
# ⚠️ CE QUE ÇA CORRIGE (audit 02/09) : ces deux planificateurs étaient
# construits `AsyncIOScheduler()` nu, au milieu du `lifespan`. Deux défauts.
#
#  1. Les garde-fous manquaient. `services/scheduler._job_defaults()` prétend
#     les poser « pour couvrir AUSSI les jobs enregistrés ailleurs » : c'est
#     faux, un `job_defaults` appartient à SON instance de planificateur. Les
#     crons de maintenance héritaient donc du `misfire_grace_time = 1 s`
#     d'APScheduler.
#
#     Le mécanisme réel (vérifié en inspectant les deux planificateurs) : ils
#     tournent sur le `MemoryJobStore` par défaut. Un redémarrage du conteneur
#     ne peut donc PAS produire d'occurrence manquée — les jobs sont ré-ajoutés
#     à neuf et leur `next_run_time` est recalculé à partir de maintenant. Ce
#     qui rate une occurrence, c'est une boucle événementielle réveillée en
#     retard : processus gelé, machine suspendue, boucle saturée. Passé une
#     seconde de retard, APScheduler abandonnait l'occurrence — le sauvetage
#     SQLite de 02:30 ne repassait qu'au lendemain. Il en restait une trace
#     (`apscheduler.executors.default` journalise « Run time of job … was
#     missed by … » en WARNING) : ce qui manquait n'est pas le log, c'est le
#     RATTRAPAGE. Les deux autres garde-fous (`coalesce`, `max_instances = 1`)
#     valaient déjà ça chez APScheduler 3.11 — seul
#     `scheduler_misfire_grace_seconds` (1 h) change quelque chose.
#  2. Rien n'était vérifiable sans démarrer toute l'application. Les fabriques
#     ci-dessous rendent un planificateur GARNI mais PAS DÉMARRÉ : un test lit
#     les jobs et leurs garde-fous sans toucher au réseau ni à la base.
# ─────────────────────────────────────────────────────────────────────────────
def _build_vault_scheduler():
    """Crons vault / sécurité / indexation — construit, PAS démarré."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.services.scheduler import _job_defaults

    # Schedule vault auto-lock (every 5 minutes — locks idle vaults after AUTO_LOCK_MINUTES)
    from app.services.vault_service import get_vault_service
    _vault_scheduler = AsyncIOScheduler(job_defaults=_job_defaults())
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
        # Le « ne pas superposer deux scans » (max_instances=1, coalesce) vient
        # maintenant de _job_defaults() — inutile de le reposer ici.
    )

    return _vault_scheduler


def _build_memory_scheduler():
    """Crons mémoire, sauvegardes et boucles d'apprentissage — PAS démarré."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.services.scheduler import _job_defaults

    _startup_logger = _logging.getLogger("app.startup")

    # Schedule user memory consolidation — twice a day to keep the backlog
    # manageable (one run at 03:00 + a booster at 15:00). At ~80 new raw
    # facts per active day, a single 2000-cap run is more than enough but
    # the afternoon pass prevents long gaps if the nightly run fails.
    from app.services.memory_service import consolidate_all_users
    _memory_scheduler = AsyncIOScheduler(job_defaults=_job_defaults())
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
    # Backup SQLite nocturne 02:30 (revue 2026-06-10 §4) — Qdrant était
    # sauvegardé, la VRAIE source de vérité (users/convs/missions) jamais.
    from app.services.sqlite_backup import run_backup as _sqlite_backup
    _memory_scheduler.add_job(
        _sqlite_backup,
        trigger="cron",
        hour=2,
        minute=30,
        id="sqlite_backup",
    )
    # Purge quotidienne des uploads (B-9) — rétention 90 j par défaut,
    # env ELY_UPLOADS_RETENTION_DAYS (0 = désactivée).
    from app.routers.upload import purge_old_uploads as _purge_uploads
    _memory_scheduler.add_job(
        _purge_uploads,
        trigger="cron",
        hour=3,
        minute=30,
        id="uploads_purge",
    )
    # Rétention des tables de signaux (revue 2026-06-10 §4) — 04:30,
    # ELY_SIGNALS_RETENTION_DAYS (90) / ELY_USAGE_RETENTION_DAYS (365).
    from app.services.retention import run_retention as _run_retention
    _memory_scheduler.add_job(
        _run_retention,
        trigger="cron",
        hour=4,
        minute=30,
        id="signals_retention",
    )
    # Purge quotidienne du Reversible Journal (J4) — 04:45 : supprime les entrées
    # hors fenêtre d'annulation pour borner la table reversible_actions.
    from app.services.journal_service import purge_expired as _purge_journal
    _memory_scheduler.add_job(
        _purge_journal,
        trigger="cron",
        hour=4,
        minute=45,
        id="reversible_journal_purge",
    )
    # Éviction des sessions navigateur inactives (B-17) — toutes les 10 min,
    # contextes Chromium fermés après 15 min sans usage.
    from app.services.browser_manager import get_browser_manager as _get_bm

    async def _browser_idle_cleanup() -> None:
        await _get_bm().cleanup_idle_sessions()

    _memory_scheduler.add_job(
        _browser_idle_cleanup,
        trigger="interval",
        minutes=10,
        id="browser_idle_cleanup",
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
    # Boucle d'auto-diagnostic J3 — diagnostiqueur (maillon 2). Scanne les
    # execution_outcomes « dubious / failed » sans diagnose et formule une
    # cause + catégorie (LLM-juge, repli à règles). Décalé de 2 min du critic
    # pour ne pas empiler deux passes LLM cloud sur le même tick. Désactivable
    # via DIAGNOSTICIAN_DISABLED=true.
    from app.services.learning import run_pending_diagnoses as _diag_run
    _memory_scheduler.add_job(
        _diag_run,
        trigger="interval",
        minutes=5,
        id="execution_diagnostician_loop",
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

    # Sprint 4b Phase 5.a — weekly curator for auto-generated learned
    # skills. Transitions active→stale (30j default), stale→archived
    # (90j default). Never deletes. Respects `pinned` opt-out. Runs
    # Monday 03:00 UTC, the calmest cron window in our existing
    # schedule. Disabled by env LEARNED_SKILLS_CURATOR_DISABLED=true.
    from app.services.learning.skill_curator import run_curator_cycle as _sc_run
    _memory_scheduler.add_job(
        _sc_run,
        trigger="cron",
        day_of_week="mon",
        hour=3,
        minute=0,
        id="learned_skills_curator",
    )

    # C5 — anticipation V1 (cadrage validé 22/07) : détecte les demandes
    # récurrentes (heuristique pure, 28 j glissants) et PROPOSE une tâche
    # planifiée (ntfy + /api/me/suggestions). Jamais d'exécution — Ely
    # propose, l'humain crée. Mardi 03:00 UTC (le curator a lundi).
    # Kill-switch : ANTICIPATION_DISABLED=true.
    from app.services.anticipation import run_anticipation_cycle as _ant_run
    _memory_scheduler.add_job(
        _ant_run,
        trigger="cron",
        day_of_week="tue",
        hour=3,
        minute=0,
        id="anticipation_cycle",
    )

    # Métadonnées modèles — refresh hebdo best-effort depuis models.dev. Le
    # snapshot bundlé fait foi (offline) ; ceci augmente l'overlay pour les
    # modèles cloud inconnus. TTL-gated (1 semaine), non bloquant, no-op si
    # offline ou si le cache est encore frais.
    from app.services.model_metadata import refresh_from_models_dev as _mm_refresh
    _memory_scheduler.add_job(
        _mm_refresh,
        trigger="cron",
        day_of_week="mon",
        hour=3,
        minute=30,
        id="model_metadata_refresh",
    )

    # Jalon 1 (portage Hermes) — autonomous skill CREATION. Ely's skill
    # funnel had every part except the trigger : run_full_loop was admin-only
    # (skill_orchestrator : « what a future cron job will call »). This is
    # that cron. Scans users with ≥3 unprocessed failure_cases, drafts +
    # evaluates playbooks, and auto-promotes passes to active — no human
    # click, the way Hermes ships a reviewed skill. Off the request
    # hot-path. Disable via SKILL_AUTOCREATE_DISABLED=true.
    from app.services.learning import (
        run_pending_skill_creation as _skill_autocreate,
    )
    _memory_scheduler.add_job(
        _skill_autocreate,
        trigger="interval",
        minutes=30,
        id="learned_skills_autocreate",
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
        # coalesce / max_instances=1 (« un seul battement à la fois ») sont
        # désormais dans _job_defaults() — voir _build_memory_scheduler.
    )
    _startup_logger.info("[missions] heartbeat scheduled every %ds", _hb_interval)

    return _memory_scheduler


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

    # Verrou mono-process (A-7, revue 2026-06-10) — AVANT init_db : deux
    # process sur la même base = create_all/ALTER en race + HITL/registres
    # split-brain. Échec de boot explicite plutôt que corruption silencieuse.
    from app.services.singleton_guard import acquire_singleton_lock
    acquire_singleton_lock()

    # Register all built-in skills BEFORE the agent graph is built
    from app.skills.builtin import register_all
    register_all()

    await init_db()

    # B-4 (revue 2026-06-10) — Alembic : stampe la base sur la baseline au
    # premier boot, applique les révisions postérieures ensuite. Toute
    # évolution de schéma future passe par `alembic revision --autogenerate`
    # au lieu d'allonger _safe_columns. Best-effort : un échec ne tue pas
    # le boot.
    from app.services.alembic_runner import ensure_migrations
    await ensure_migrations()

    # B-11 (revue 2026-06-10) — chiffre en une passe les secrets encore en
    # clair (system_config is_secret + llm_instances.api_key). Idempotent.
    # AVANT load_llm_settings_from_db pour que les lectures déchiffrent.
    from app.services.system_config import migrate_plaintext_secrets
    await migrate_plaintext_secrets()

    # Load LLM provider/model/key overrides from DB into in-memory runtime
    from app.services.llm_provider import load_llm_settings_from_db
    await load_llm_settings_from_db()

    # Load mono-agent toggle (admin: Paramètres → Routage)
    from app.services.mono_agent import load_mono_agent_flag
    await load_mono_agent_flag()

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

    # Contrôle de réalité de la configuration (26/07/2026). Confronte ce qui
    # est RÉELLEMENT configuré — instances LLM, outils bindés — aux tables du
    # code. Ajouté après avoir découvert que get_context_window() renvoyait
    # 8 192 tokens pour tous les modèles pendant des mois, sans une erreur.
    try:
        from app.services.config_reality import log_config_reality
        await log_config_reality()
    except Exception:
        _startup_logger.debug("Contrôle de réalité ignoré", exc_info=True)

    # Sonde des têtes de chaîne — elle EXERCE les services au lieu de vérifier
    # qu'ils sont constructibles. Le contrôle ci-dessus était vert le 30 et le
    # 31/07 pendant que `kimi-k3` rendait 400 à chaque appel et que SearchCans
    # répondait « 200 OK » sans un résultat.
    #
    # Lancée en TÂCHE DE FOND : elle fait de vrais appels réseau (jusqu'à 40 s
    # par tête). Le démarrage n'a pas à les attendre — un diagnostic qui
    # retarde le service qu'il diagnostique se paie deux fois.
    #
    # ⚠️ (audit 02/09) `ensure_future` nu : la boucle ne garde qu'une référence
    # FAIBLE sur la tâche, qui peut donc être ramassée EN VOL — la sonde qui a
    # rattrapé deux pannes de fournisseur mourrait en silence, exception
    # comprise. `spawn` la retient jusqu'à la fin et journalise son échec.
    try:
        from app.services.background_tasks import spawn
        from app.services.service_probe import log_service_probe
        spawn(log_service_probe(), label="startup.service_probe")
    except Exception:
        _startup_logger.debug("Sonde des têtes ignorée", exc_info=True)

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

    # Chauffe du SLM — charge le modèle en RAM pour épargner un démarrage à
    # froid à la première question. ⚠️ `warmup_slm` REND LA MAIN aussitôt : il
    # ne fait que poser une tâche de fond. Le 08/08, il était attendu ici, son
    # backoff brûlait 62 s sur un serveur local injoignable, et le healthcheck
    # du compose (15 s + 3 × 30 s) déclarait le conteneur mort alors qu'Ely
    # finissait par démarrer. Un confort optionnel ne prend pas le service en
    # otage — ne pas remettre d'`await` ici.
    from app.services.slm_warmup import warmup_slm
    await warmup_slm()  # non bloquant par construction — voir le module

    # Couche 2 PII NER (GLiNER ONNX int8) — chargée au boot UNIQUEMENT si
    # PII_NER_ENABLED est posé (défaut off). Fail-open : tout échec laisse
    # la couche 1 regex seule (comportement historique), avec un log
    # explicite de la marche à suivre (export ONNX / rebuild).
    from app.services.pii_ner import load_ner_engine as _load_ner, pii_ner_enabled as _pii_ner_on
    if _pii_ner_on():
        try:
            import asyncio as _asyncio
            await _asyncio.to_thread(_load_ner)
        except Exception:
            _startup_logger.warning(
                "PII NER layer failed to load — couche 2 désactivée, couche 1 regex intacte",
                exc_info=True,
            )

    # Load approved community skills into the skill registry
    from app.services.marketplace import get_marketplace_service
    try:
        await get_marketplace_service().load_approved_skills()
    except Exception:
        _startup_logger.warning("Community skills failed to load", exc_info=True)


    _vault_scheduler = _build_vault_scheduler()
    _vault_scheduler.start()

    # Jalon 1 (portage Hermes) — seed the playbook library so it's never
    # cold (Hermes ships 89 SKILL.md ; Ely shipped zero). Idempotent +
    # best-effort : a passing playbook is reusable from day one.
    try:
        from app.services.learning.seed_playbooks import load_seed_playbooks
        _seed_summary = await load_seed_playbooks()
        if _seed_summary.get("inserted"):
            _startup_logger.info(
                "[skills] seeded %d bundled playbook(s)",
                _seed_summary["inserted"],
            )
    except Exception as _seed_exc:  # never block boot on seeding
        _startup_logger.warning("[skills] seed playbooks load failed: %s", _seed_exc)

    _memory_scheduler = _build_memory_scheduler()
    _memory_scheduler.start()

    # MCP server (J2): the Streamable-HTTP session manager must run while the
    # mounted /api/mcp app serves. Created at import by build_mcp_app().
    if _MCP_ENABLED:
        from app.mcp_server import mcp as _ely_mcp
        async with _ely_mcp.session_manager.run():
            yield
    else:
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
    version="2.5.0",
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

# Headers de sécurité standard (revue 2026-06-10, B-18/D1)
from app.middleware.security_headers import add_security_headers  # noqa: E402

add_security_headers(app)

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
# Sprint 2.5 §2.5.6 — `/api/me/memories/*` : inspection et oubli
app.include_router(memory_router.router, tags=["memory"])
# Sprint 4b Phase 3 — admin endpoints for the autonomous skill_creator loop.
# Carries its own /admin/learning prefix.
app.include_router(learning_skills_router.router, tags=["learning"])
# Sprint 4b Phase 5.b — user-facing /api/me/learning-skills surface
# (list, pin, forget). Carries its own /api/me/learning-skills prefix.
app.include_router(me_learning_skills_router.router, tags=["learning"])
# Substrat / J2 — Reversible Action Journal : lister + annuler ses actions.
# Carries its own /api/me/reversible-actions prefix.
from app.routers import reversible_actions as _reversible_actions_router
app.include_router(_reversible_actions_router.router, tags=["trust"])
# (J4) métriques du journal — /admin/reversible-actions/stats (admin only)
app.include_router(_reversible_actions_router.admin_router, tags=["trust"])
app.include_router(mcp_router.router, prefix="/admin", tags=["mcp"])
# Client MCP v2 / J2 — OAuth 2.1 par utilisateur : « Se connecter » + callback.
# Sous /api (per-user, callback joignable sans auth admin, borné par state).
# ⚠️ DOIT rester enregistré AVANT `app.mount("/api/mcp", ...)` (serveur FastMCP,
# plus bas) : Starlette résout au premier match dans l'ordre, sinon le mount
# /api/mcp masquerait /api/mcp/oauth/*.
from app.routers import mcp_oauth as _mcp_oauth_router
app.include_router(_mcp_oauth_router.router, prefix="/api", tags=["mcp-oauth"])
app.include_router(telegram_webhook_router.router, tags=["telegram"])
app.include_router(vault_router.router)
app.include_router(conversations_router.router)
app.include_router(knowledge_router.router, prefix="/api", tags=["knowledge"])
app.include_router(marketplace_router.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(settings_llm_router.router)
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
app.include_router(api_keys_router.router)

# ── MCP server (J2) — expose ELY as an MCP server at /api/mcp ───────────────
# Authenticated by personal API keys (J1). Mounted under /api so the existing
# nginx `^/(api|…)/` proxy reaches it with no config change. Its Streamable-HTTP
# session manager is started in the lifespan above. Defensive: a mount failure
# disables only MCP, never the whole app.
_MCP_ENABLED = False
try:
    from app.mcp_server import build_mcp_app
    app.mount("/api/mcp", build_mcp_app())
    _MCP_ENABLED = True
    _logging.getLogger("app.main").info("MCP server mounted at /api/mcp")
except Exception as _mcp_exc:  # noqa: BLE001
    _logging.getLogger("app.main").warning(
        "MCP server mount failed: %s — /api/mcp disabled", _mcp_exc
    )
from app.routers import hitl_prefs as _hitl_prefs_router
app.include_router(_hitl_prefs_router.router, prefix="/api")
from app.routers import onboarding as _onboarding_router
app.include_router(_onboarding_router.router, prefix="/api")
# Voice / TTS preferences. The router already self-prefixes with
# `/api/preferences`, so no extra prefix here.
from app.routers import voice_prefs as _voice_prefs_router
app.include_router(_voice_prefs_router.router)
# PII sovereignty toggle (2026-06-07). Self-prefixes with /api/preferences.
from app.routers import sovereignty_prefs as _sovereignty_prefs_router
app.include_router(_sovereignty_prefs_router.router)
# Tier-aware licence enforcement (Phase 1) — router carries its own /api/licence prefix.
from app.routers import licence as _licence_router
app.include_router(_licence_router.router)
# C5 — suggestions d'anticipation (self-prefixed /api/me/suggestions).
from app.routers import suggestions as _suggestions_router
app.include_router(_suggestions_router.router)

# ── Static files — ELY Desktop binaries ─────────────────────────────────────
import os as _os
_desktop_static = _os.path.join(_os.path.dirname(__file__), "..", "static", "desktop")
if _os.path.isdir(_desktop_static):
    app.mount("/static/desktop", StaticFiles(directory=_desktop_static), name="desktop-static")
