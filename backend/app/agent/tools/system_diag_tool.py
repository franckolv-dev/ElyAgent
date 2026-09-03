# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tools/system_diag_tool.py
# @brief      Read-only self-introspection tools (logs, status, health)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Read-only self-introspection tools.

These let ELY answer questions like :
  - "Pourquoi ma tâche planifiée n'a pas envoyé l'email hier ?"
  - "Quels canaux sont actifs ?"
  - "Quels modèles LLM sont chargés en ce moment ?"
  - "Combien de RAM consomme le backend ?"

PHASE A : strictly read-only. No DB writes, no shell exec, no file
writes outside the SQLite layer's normal operations. Self-modification
(restart bot, change tier, etc.) is reserved for PHASE B with HITL.

All tools are scoped to the **calling user** when applicable :
- `system_list_scheduled_tasks` returns only this user's tasks
- `system_list_missions` returns only this user's missions
- An admin caller can opt-in to global views via explicit flags

Logs are sanitized via `app.services.log_buffer._sanitize` before any
LLM context injection — secrets like API keys, JWTs, passwords are
masked with `<redacted:type>`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from langchain_core.tools import InjectedToolArg, tool
from sqlalchemy import select, func

from app.database import async_session
from app.services.log_buffer import get_recent, buffer_stats

logger = logging.getLogger(__name__)


# ── Helper : resolve current user via injected user_id ────────────────────────

async def _get_user(user_id: str):
    from app.models.user import User
    if not user_id:
        return None
    async with async_session() as db:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


# ── 1. system_get_logs ───────────────────────────────────────────────────────

# Pre-compiled regex for the user-id leak filter — matches any UUID that
# could be a User.id. We never want user A to see "user B just received
# email from C" in the public demo, so non-admins get rows mentioning a
# foreign UUID redacted to <other-user>.
import re as _re_uid
_UUID_RE = _re_uid.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    _re_uid.IGNORECASE,
)


@tool
async def system_get_logs(
    lines: int = 100,
    grep: Optional[str] = None,
    level: Optional[str] = None,
    logger_prefix: Optional[str] = None,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Read recent backend log lines (in-memory ring buffer, last ~5000 entries).

    NO TIME FILTER — this tool only filters by line count, substring (grep),
    log level, and logger module. Do NOT pass `time`, `date`, `since`, `from`,
    `to`, `today`, `yesterday` — these are NOT valid arguments and the call
    will FAIL. To get "this morning's logs" simply ask for the last N lines
    (the buffer holds ~5000 entries = a few minutes of activity, so recent =
    everything in the buffer).

    Sensitive values (API keys, tokens, JWTs, passwords) are automatically
    masked before being returned. Use this to diagnose why a feature is
    not working as expected.

    Privacy & multi-tenancy :
      • Admins see the full sanitised buffer.
      • Non-admins see only their own log lines + truly global lines
        (lines that mention no user_id at all). Lines mentioning another
        user's UUID are hidden — never anonymised partially, fully removed.
      • In ``demo_mode`` (set in app config), non-admins are denied entirely
        because shared-instance log access is too leaky.

    Args:
        lines: How many recent lines to return (max 200, default 100).
        grep: Substring to filter messages by (case-insensitive).
              Examples: "scheduled task", "email", "telegram", "mission heartbeat".
        level: Minimum log level — DEBUG, INFO, WARNING, ERROR, CRITICAL.
        logger_prefix: Filter by logger name prefix.
              Examples: "app.services.scheduler", "app.channels.telegram_bot",
              "app.services.mission_heartbeat".

    Returns formatted text, one line per entry.
    """
    lines = max(1, min(int(lines or 100), 200))

    # ── Authorization check ───────────────────────────────────────────────
    from app.config import get_settings as _gs
    is_admin = False
    if user_id:
        u = await _get_user(user_id)
        is_admin = bool(u and getattr(u, "role", "") == "admin")

    settings = _gs()
    demo_mode = bool(getattr(settings, "demo_mode", False))
    if demo_mode and not is_admin:
        return (
            "Logs unavailable in demo mode for non-admin users. "
            "This shared instance hides cross-tenant log lines for privacy. "
            "Self-host ELY for full diagnostic access."
        )

    rows = get_recent(lines=lines * 3 if not is_admin else lines,
                      grep=grep, level=level, logger_prefix=logger_prefix)
    if not rows:
        return f"Aucune entrée de log ne correspond aux filtres (grep={grep!r}, level={level}, prefix={logger_prefix})."

    # ── Tenant filter (non-admins) ────────────────────────────────────────
    # Show: rows that mention THIS user_id, or rows that mention NO uuid at all.
    # Hide: rows that mention SOMEONE ELSE's uuid.
    if not is_admin and user_id:
        own_short = user_id[:8].lower()  # short prefix appears in our own logs
        filtered = []
        for ts, lvl, name, msg in rows:
            uuids = _UUID_RE.findall(msg)
            if not uuids:
                # Truly global line (e.g. "Application startup complete")
                filtered.append((ts, lvl, name, msg))
                continue
            # If at least one UUID matches the caller, include — drop otherwise
            if any(uid.lower().startswith(own_short) or uid.lower() == user_id.lower()
                   for uid in uuids):
                filtered.append((ts, lvl, name, msg))
        rows = filtered[-lines:]
        if not rows:
            return (
                "Aucune entrée de log à votre sujet n'a été trouvée. "
                "Les logs concernant d'autres utilisateurs sont masqués."
            )

    out = [f"{len(rows)} entrée(s) — du {rows[0][0]} au {rows[-1][0]} (UTC)"]
    if not is_admin:
        out.append("(filtré pour ne montrer que vos propres logs et les logs globaux)")
    out.append("")
    for ts, lvl, name, msg in rows:
        # Trim very long lines so the LLM context stays manageable
        if len(msg) > 400:
            msg = msg[:400] + "…"
        out.append(f"[{ts}] {lvl:<7} {name}: {msg}")
    out.append("")
    out.append(f"Buffer status: {buffer_stats()}")
    return "\n".join(out)


# ── 2. system_list_scheduled_tasks ───────────────────────────────────────────

@tool
async def system_list_scheduled_tasks(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all scheduled (cron-like) tasks for the current user.

    Returns name, cron expression, channel (email/telegram/web/etc.),
    enabled flag, last_run_at and last_result. Use this to verify that
    a task you set up is actually configured AND to see if it ran
    successfully.
    """
    from app.models.scheduled_task import ScheduledTask
    user = await _get_user(user_id)
    if not user:
        return "Utilisateur introuvable — appel sans contexte d'authentification."

    async with async_session() as db:
        r = await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user.id)
            .order_by(ScheduledTask.created_at.desc())
        )
        tasks = list(r.scalars())

    if not tasks:
        return "Aucune tâche planifiée pour cet utilisateur."

    lines = [f"{len(tasks)} tâche(s) planifiée(s) :"]
    for t in tasks:
        last = (
            f" (dernier run : {t.last_run_at.isoformat()})"
            if getattr(t, "last_run_at", None) else " (jamais exécutée)"
        )
        last_res = getattr(t, "last_result", None) or ""
        if last_res and len(last_res) > 150:
            last_res = last_res[:150] + "…"
        status = "✅ activée" if t.enabled else "⏸ désactivée"
        lines.append(
            f"\n• {t.name}\n"
            f"  cron     : {t.cron_expression}\n"
            f"  channel  : {t.channel}\n"
            f"  status   : {status}{last}\n"
            f"  prompt   : {t.prompt[:120]}{'…' if len(t.prompt) > 120 else ''}\n"
            + (f"  last_res : {last_res}\n" if last_res else "")
        )
    return "".join(lines)


# ── 3. system_list_missions ──────────────────────────────────────────────────

@tool
async def system_list_missions(
    user_id: Annotated[str, InjectedToolArg] = "",
    status_filter: Optional[str] = None,
) -> str:
    """List goal-driven missions for the current user.

    Args:
        status_filter: Only return missions with this status. Possible :
                       draft, planning, running, paused, completed, failed, aborted.
                       Leave empty for all.
    """
    from app.models.mission import Mission
    user = await _get_user(user_id)
    if not user:
        return "Utilisateur introuvable."

    async with async_session() as db:
        q = select(Mission).where(Mission.user_id == user.id).order_by(Mission.created_at.desc()).limit(50)
        if status_filter:
            q = q.where(Mission.status == status_filter)
        missions = list((await db.execute(q)).scalars())

    if not missions:
        return f"Aucune mission ({status_filter or 'tous statuts'})."

    out = [f"{len(missions)} mission(s) :"]
    for m in missions:
        budget = f"{m.iterations_used}/{m.budget_iterations} iter, {m.tokens_used}/{m.budget_tokens} tokens"
        end = ""
        if m.completed_at:
            end = f"  terminée: {m.completed_at.isoformat()}"
        if m.failure_reason:
            end += f"  raison_échec: {m.failure_reason[:100]}"
        out.append(
            f"\n• [{m.status}] {m.title}\n"
            f"  goal    : {m.goal[:120]}{'…' if len(m.goal) > 120 else ''}\n"
            f"  budget  : {budget}\n"
            f"  source  : {m.source}{end}"
        )
    return "".join(out)


# ── 4. system_check_channels ─────────────────────────────────────────────────

@tool
async def system_check_channels(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Check the runtime status of the chat channels (Telegram).

    Reports : configured (yes/no), running (yes/no), whether **you** are
    linked on this channel, bot username when known. Use this to diagnose
    "why didn't I receive a notification on Telegram?".

    In demo_mode, the global linked-user count is hidden (cross-tenant) —
    only your own link status is shown.
    """
    from app.config import get_settings as _gs
    is_admin = False
    if user_id:
        u = await _get_user(user_id)
        is_admin = bool(u and getattr(u, "role", "") == "admin")
    settings = _gs()
    show_global_count = is_admin or not bool(getattr(settings, "demo_mode", False))

    def _linked_str(linked_dict: dict, total: int) -> str:
        # In demo mode, hide cross-tenant counts; always show "you are linked"
        you_linked = bool(user_id and user_id in linked_dict.values()) if linked_dict else False
        if show_global_count:
            return f"users_linked={total} you_linked={you_linked}"
        return f"you_linked={you_linked}"

    out = ["État des canaux conversationnels :\n"]

    # Telegram
    try:
        from app.channels import telegram_bot as tg
        tok = await _config_get("telegram_bot_token", "")
        bot_alive = tg._bot_app is not None
        linked = getattr(tg, "_linked_users", {})
        out.append(f"📨 Telegram : configuré={bool(tok)} bot_alive={bot_alive} {_linked_str(linked, len(linked))}")
    except Exception as exc:
        out.append(f"📨 Telegram : erreur introspection ({exc})")

    return "\n".join(out)


# ── 5. system_check_llm_providers ────────────────────────────────────────────

@tool
async def system_check_llm_providers() -> str:
    """Inspect the LLM routing configuration AND probe each backend for liveness.

    Shows : tier → primary/fallback chain, LM Studio loaded models,
    configured cloud providers, last-used model when available. Use to
    diagnose "ELY is using API X but I want it to use local Y".
    """
    import json
    out = ["Configuration LLM :\n"]

    # 1. Tier routing config from system_config
    try:
        cfg_raw = await _config_get("tier_routing_config", "{}")
        cfg = json.loads(cfg_raw or "{}")

        # Resolve LLMInstance UUIDs to readable labels
        from app.models.llm_instance import LLMInstance
        async with async_session() as db:
            r = await db.execute(select(LLMInstance))
            inst_by_id = {i.id: f"{i.provider}/{i.model}" for i in r.scalars()}

        for tier, conf in cfg.items():
            providers = conf.get("providers", [])
            chain = " → ".join(inst_by_id.get(p, p) for p in providers) or "(none)"
            fb = "fallback ON" if conf.get("fallback_enabled") else "fallback OFF"
            out.append(f"tier {tier:12s}: {chain}  ({fb})")
    except Exception as exc:
        out.append(f"  erreur lecture tier_routing_config: {exc}")

    # 2. LM Studio probe (host)
    try:
        import httpx
        from app.config import get_settings
        s = get_settings()
        url = (getattr(s, "lm_studio_base_url", None) or "http://host.docker.internal:1234").rstrip("/")
        # L'URL configurée finit déjà par `/v1` : on interrogeait `/v1/v1/models`,
        # LM Studio répondait 200 avec une liste vide, et l'outil annonçait
        # « 0 modèle disponible » — le modèle en concluait que les têtes locales
        # étaient mortes et partait fouiller les journaux (03/09/2026).
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{url}/v1/models")
        if r.status_code == 200:
            ids = [m["id"] for m in r.json().get("data", [])]
            out.append(f"\nLM Studio @ {url} — {len(ids)} modèle(s) disponible(s) :")
            for m in ids:
                out.append(f"  • {m}")
        else:
            out.append(f"\nLM Studio @ {url} — HTTP {r.status_code} (probablement éteint)")
    except Exception as exc:
        out.append(f"\nLM Studio injoignable : {exc}")

    # 3. Cloud providers configured
    out.append("\nClés API cloud configurées (présence/absence, valeurs masquées) :")
    for env_key, label in [
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("MISTRAL_API_KEY", "Mistral"),
        ("GEMINI_API_KEY", "Gemini"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
        ("ZHIPU_API_KEY", "Zhipu"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("QWEN_API_KEY", "Qwen DashScope"),
    ]:
        import os
        out.append(f"  • {label:<18s}: {'✅ configurée' if os.environ.get(env_key) else '❌ absente'}")

    return "\n".join(out)


# ── 6. system_get_health ─────────────────────────────────────────────────────

@tool
async def system_get_health() -> str:
    """High-level overview of the backend's health.

    Reports : process uptime, Python version, Qdrant collections + counts,
    SQLite database file size, log buffer fill ratio, mission heartbeat
    interval. Use this as a "general checkup".
    """
    import os
    import sys
    import time

    import httpx
    out = ["État de santé du backend ELY :\n"]

    # Uptime via /proc (Linux container)
    try:
        with open("/proc/self/stat") as f:
            stat = f.read().split()
        starttime_jiffies = int(stat[21])
        with open("/proc/uptime") as f:
            uptime_total = float(f.read().split()[0])
        clk_tck = os.sysconf("SC_CLK_TCK")
        uptime_sec = uptime_total - (starttime_jiffies / clk_tck)
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        out.append(f"⏱  Uptime backend : {days}j {hours}h {mins}m")
    except Exception:
        out.append("⏱  Uptime backend : indisponible")

    out.append(f"🐍 Python : {sys.version.split()[0]}")

    # Qdrant
    try:
        from app.config import get_settings
        s = get_settings()
        url = (getattr(s, "qdrant_url", None) or "http://qdrant:6333").rstrip("/")
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{url}/collections")
        if r.status_code == 200:
            cols = r.json().get("result", {}).get("collections", [])
            out.append(f"\n🧠 Qdrant @ {url} — {len(cols)} collection(s) :")
            for col in cols:
                name = col["name"]
                r2 = await httpx.AsyncClient(timeout=3).get(f"{url}/collections/{name}")
                pts = r2.json().get("result", {}).get("points_count", "?")
                out.append(f"  • {name}: {pts} points")
        else:
            out.append(f"\n🧠 Qdrant : HTTP {r.status_code}")
    except Exception as exc:
        out.append(f"\n🧠 Qdrant : erreur ({exc})")

    # SQLite size
    try:
        db_path = "/app/data/cyberentity.db"
        if os.path.exists(db_path):
            size_mb = os.path.getsize(db_path) / (1024 * 1024)
            out.append(f"\n💾 SQLite DB : {size_mb:.1f} Mo")
    except Exception:
        pass

    # Log buffer
    try:
        stats = buffer_stats()
        out.append(
            f"\n📋 Ring buffer logs : {stats['current_size']}/{stats['max_entries']} entrées "
            f"(plus ancienne : {stats.get('oldest', 'N/A')})"
        )
    except Exception:
        pass

    # Mission heartbeat config
    try:
        interval = int(os.environ.get("MISSION_HEARTBEAT_SECONDS", "30"))
        out.append(f"\n💓 Mission heartbeat : tick toutes les {interval}s")
    except Exception:
        pass

    # Counts of various rows
    try:
        from app.models.user import User
        from app.models.scheduled_task import ScheduledTask
        from app.models.mission import Mission
        async with async_session() as db:
            n_users = (await db.execute(select(func.count(User.id)))).scalar_one()
            n_tasks = (await db.execute(select(func.count(ScheduledTask.id)))).scalar_one()
            n_miss = (await db.execute(select(func.count(Mission.id)))).scalar_one()
        out.append(
            f"\n📊 Stats DB : {n_users} user(s), {n_tasks} tâche(s) planifiée(s), {n_miss} mission(s)"
        )
    except Exception as exc:
        out.append(f"\n📊 Stats DB : erreur ({exc})")

    return "\n".join(out)


# ── Internal helper ──────────────────────────────────────────────────────────

async def _config_get(key: str, default: str = "") -> str:
    """Read a value from the system_config table. Empty string on miss."""
    try:
        from app.services.system_config import get_config
        v = await get_config(key, fallback=default)
        return str(v or default)
    except Exception:
        return default
