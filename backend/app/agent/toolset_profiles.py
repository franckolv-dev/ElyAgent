# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/toolset_profiles.py
# @brief      Static per-conversation toolset profiles (Hermes Chantier 1)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Static toolset profiles — Hermes-style stable tool catalog per session.

Why
---
ELY historically bound the full registry (145 tools) and filtered by keyword
on the user's input each turn. That broke the Anthropic prompt cache prefix,
sent contradictory signals to the model ("the tool was here last turn, where
is it now?"), and overwhelmed small models (Ministral 3 8B, Qwen3-VL-8B)
with a constantly shifting catalog.

Hermes uses a **fixed catalog of ~30 tools per session**, chosen ONCE at
session start. The model learns the catalog (muscle memory), the system
prompt is byte-stable (cache hit), and multi-turn workflows stop confusing
the model with vanishing tools.

Design
------
A **profile** is a hand-curated list of ~25-35 tool names that covers a
coherent persona. We start with a single profile, ``default``, that covers
~80% of everyday workflows (capture + email + drive + calendar + tasks +
notes + simple web search). Future profiles (``workspace_focus``,
``research_focus``, etc.) plug into the same registry.

A profile is **sticky to a conversation**: stored in
``conversations.toolset_profile``. The first message of a conversation
triggers ``auto_detect_profile()`` which today returns ``"default"``;
later we may add keyword classifiers. The user can override anytime via
the ``/profile <name>`` slash command (handled in chat.py).

Failure mode
------------
A tool name in a profile that's not registered (typo, removed) is silently
dropped at resolution time. The bound list is always a subset of
``registry.all_tools`` regardless of stale config.
"""
from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)


# ── Profile names ────────────────────────────────────────────────────────────
DEFAULT_PROFILE = "default"


# ── Profile contents ─────────────────────────────────────────────────────────
# Each list is curated by hand. Order doesn't matter for binding but kept
# semantic for readability. Universal tools (memory, knowledge) appear in
# every profile so cross-session context still works.

_DEFAULT_TOOLS: tuple[str, ...] = (
    # Universal — tool discovery (the safety net: lets the model pull in any
    # catalog tool it doesn't currently see, instead of giving up).
    "find_tool",
    "report_missing_capability",
    # Universal — memory, preferences, knowledge (always present)
    "knowledge_list",
    "knowledge_search",
    "smart_knowledge_query",
    "save_user_preference",
    "save_constraint",            # HITL-gated, harmless to expose
    # Memory — durable facts via MemGPT-style hierarchical store
    "memory_archive",
    "memory_search",
    "memory_view_profile",
    # Sprint 1 (2026-05-15) — cross-conversation recall.
    # Lets the agent answer "do you remember…", "what did we say
    # about…" by searching past conversations via FTS5 + summarising
    # via Ministral 3B local.
    "search_past_conversations_tool",
    # Notes — quick scratch storage
    "notes_create",
    "notes_list",
    "notes_search",
    # NB : les outils d'annulation (list_revertible_actions / revert_action /
    # undo_last_action) ne sont PAS dans le profil statique : ils sont unis
    # dynamiquement par resolve_profile_tools UNIQUEMENT quand le flag
    # reversible_journal_enabled est ON (zéro coût de prompt quand OFF).
    # Gmail — read + send + reply (the 80% of email work)
    "gmail_list_emails",
    "gmail_read_email",
    # Download a message's attachments → Drive folder (binary, server-side).
    # The only path to "save invoice PDFs to Drive" — drive_create_file is
    # text-only and gmail_read_email can't fetch files (gap found 2026-06-04).
    "gmail_save_attachments_to_drive",
    "gmail_send_email",
    "gmail_send_with_local_attachment",
    "gmail_reply_email",
    "gmail_create_draft",
    # Gmail — cleanup / triage (HITL forced inside each tool)
    # Without these, the LLM hallucinates `gmail_delete_email` when the
    # user asks « supprime les mails AliExpress » and the loop dies on
    # « tool not available ». The matching mission node already binds
    # them via the keyword booster (missions/nodes.py:_KEYWORD_BOOST),
    # which is why scheduled missions worked but interactive chat did not.
    "gmail_search_for_cleanup",
    "gmail_trash_by_category",
    "gmail_trash_emails",
    # 2026-05-17 — Added after the agent told Franck «je n'ai pas accès à
    # l'outil gmail_trash_by_query» while doing a SHEIN cleanup. The tool
    # existed in gmail_tool.py but was missing from the default profile,
    # forcing every sender-based bulk delete through the 2-step
    # list+trash_by_id flow (slower + more turns = more LLM pressure).
    # Now exposed. Already in ALWAYS_CRITICAL_TOOLS and just added to
    # LOCKED_HITL_TOOLS — a single bad query can match thousands of
    # mails, so the user can NEVER opt out of confirming this one.
    "gmail_trash_by_query",
    # 2026-05-17 — gmail_empty_trash : DEFINITIVELY empties the trash
    # (vs gmail_trash_* which only MOVE to trash and rely on Gmail's
    # 30-day auto-purge). Created after the agent kept hallucinating
    # « la corbeille a été vidée » without an actual tool to do it.
    # HITL-locked (irreversible — no API recovers a deleted Gmail msg).
    # GitHub — read-only stats + traffic + notifications (2026-05-17,
    # added to unblock screencast scenario step « clones du repo ElyAgent »).
    # Token configured via GITHUB_TOKEN env var.
    "github_repo_stats",
    "github_traffic_stats",
    "github_notifications",
    # Gmail — settings (filters, signature, vacation, forwarding).
    # Added 2026-05-08 after observing Qwen 3.6 Flash spontaneously
    # propose « je vais créer des filtres » during a mail audit, then
    # confabulate a success message because the tool wasn't exposed.
    # LOCKED_HITL so user always confirms — these settings persist.
    "gmail_update_settings",
    # Calendar — create + list (single events; recurring goes via scheduler)
    "calendar_create_event",
    "calendar_list_events",
    "calendar_quick_add",
    # Drive — create text files + list + read + organise + find duplicates + trash
    "drive_create_file",
    # Upload a LOCAL binary file (e.g. a screenshot PNG) to Drive (added
    # 2026-06-16): drive_create_file is text-only, so without this there was
    # no way to save a captured PNG to Drive — the agent would bail
    # ("can't save the file") even though the screenshot existed on disk.
    "drive_upload_local_file",
    "drive_list_files",
    "drive_read_file",
    # Organisation tools (added 2026-06-03 after a Drive-reorg session failed:
    # the agent only had drive_create_file, so it created "folders" as
    # text/plain files and concluded — truthfully, from its bound toolset —
    # that it had no way to make folders or move files. These existed in
    # drive_tool.py + GOOGLE_TOOLS but were never in the default profile
    # (the "tool invisible" trap, docs/ADDING_A_TOOL.md). All non-destructive
    # (move relocates via addParents/removeParents, no data loss) → NOT
    # HITL-locked, so bulk reorg flows without a prompt per file.
    "drive_create_folder",
    "drive_move_file",
    "drive_copy_file",
    "drive_rename_file",
    # Server-side duplicate detection (added 2026-05-09 after observing
    # Ministral 14B OOM Metal trying to do it manually with 30+ tool calls).
    # Compresses recursive walk + md5 grouping into 1 tool call → tractable
    # for any LLM, even Ministral 8B.
    "drive_find_duplicates",
    # Trash a file by ID (NOT permanent — Drive keeps trashed files 30 days).
    # Natural follow-up to drive_find_duplicates: « OK, supprime ces 3 doublons ».
    # Already in LOCKED_HITL_TOOLS so user always confirms before action.
    "drive_delete_file",
    # ELY Desktop — local filesystem access via the Go daemon. Sandboxed
    # to the directories the user explicitly authorised in
    # Paramètres → Intégrations → ELY Desktop. Daemon connection state
    # is checked at tool-call time — when offline the tools return a
    # clear « ELY Desktop n'est pas connecté » message.
    # 5 read-only tools (no HITL):
    "desktop_list_dir",
    "desktop_read_file",
    "desktop_search_files",
    "desktop_stat_file",
    "desktop_hash_file",
    # 4 write tools (HITL forced — all in LOCKED_HITL_TOOLS):
    "desktop_write_file",
    "desktop_move_file",
    "desktop_delete_file",
    "desktop_create_dir",
    # Browser — capture + navigate + extract text (server-side Playwright,
    # no user session)
    "browser_navigate",
    "browser_screenshot",
    "browser_get_text",
    "browser_search_web",
    # Browser extension — acts on the user's REAL Chrome tabs (their cookies,
    # their authenticated sessions on LinkedIn / Gmail / Amazon / X / etc.).
    # Two patterns:
    #   1. Read an existing tab the user already has open:
    #      list_tabs → tab_read_text(tab_id)
    #   2. Autonomously fetch a URL using the user's Chrome session:
    #      open_tab → wait_loaded → tab_read_text → close_tab
    "browser_list_tabs",
    "browser_open_tab",
    "browser_tab_wait_loaded",
    "browser_tab_wait_for_selector",
    "browser_tab_get_url",
    "browser_tab_read_text",
    "browser_tab_read_html",
    "browser_tab_screenshot",
    # Sprint 1 (2026-05-14) — interactivity. Required to drive multi-step
    # SPA workflows (Doctolib, SNCF, Booking, .gouv.fr) that hide their
    # data behind buttons React refuses to expose via URL.
    "browser_tab_click",
    "browser_tab_fill",
    "browser_tab_navigate",
    "browser_close_tab",
    # Sprint 0.7 (2026-05-26) — Chrome v2 read-only inspectors.
    # Answer "what did I visit/bookmark/download?" without opening a tab.
    # Server-side privacy filter drops banking/health/adult/gov domains
    # before the agent sees the rows; inputs clamped to ≤30 days / ≤20 rows.
    "browser_history_search",
    "browser_bookmarks_search",
    "browser_downloads_search",
    # Web search (DuckDuckGo / SerpAPI fallback path)
    "web_search",
    # Incident du 26/07 : ces deux outils existaient dans le catalogue mais
    # n'étaient pas bindés. Ely répondait donc — honnêtement — « je n'ai aucun
    # outil dédié à l'actualité récente », et se rabattait sur une recherche
    # web générique dégradée.
    "web_search_news",
    "news_get_headlines",
    # Tasks (Google Tasks)
    "tasks_create",
    "tasks_list",
    # Contacts — needed when user says "envoie à Alice" without an address
    "contacts_search",
    # Vision — analyse an image attached or already on disk
    "vision_analyze_image",
    # Image generation
    "generate_image",
    # Weather + translation (frequent quick utilities)
    "weather_get",
    "translate_text",
    # Scheduler — recurring reminders (cron-like). All three operations
    # exposed together so ELY can manage the lifecycle of her own tasks
    # without resorting to "schedule a task to delete the other tasks
    # tomorrow morning" workarounds (audit Franck 2026-05-14).
    "scheduler_create_task",
    "scheduler_list_tasks",
    "scheduler_delete_task",
    # Sprint 4b Phase 4.b (2026-05-29) — progressive disclosure on the
    # autonomous learned playbooks. The system prompt already lists each
    # active LearnedSkill's name + description (~50 tokens per skill,
    # see memory_snapshot.build_memory_snapshot). When the agent
    # decides a playbook is relevant, it calls `skill_view(name)` to
    # pull the full body. user_id is auto-injected (USER_ID_TOOLS)
    # so the lookup is always user-scoped.
    "skill_view",
)


# Registry of profiles. Add new ones by appending tuples and registering them
# in this dict. Auto-detect logic lives below.
_PROFILES: dict[str, tuple[str, ...]] = {
    "default": _DEFAULT_TOOLS,
}


def list_profiles() -> list[str]:
    """Return the names of all registered profiles."""
    return list(_PROFILES.keys())


def is_valid_profile(name: str) -> bool:
    """True if ``name`` is a registered profile."""
    return name in _PROFILES


def get_profile_tool_names(name: str) -> tuple[str, ...]:
    """Return the tool-name tuple for ``name``. Falls back to ``default``
    if the name is unknown (defensive — better to bind something than to
    crash on a stale config value)."""
    if name not in _PROFILES:
        logger.warning(
            "toolset_profiles: unknown profile %r — falling back to %r",
            name, DEFAULT_PROFILE,
        )
        return _PROFILES[DEFAULT_PROFILE]
    return _PROFILES[name]


def _mcp_tool_names() -> set[str]:
    """Tool names exposed by every currently-registered MCP skill.

    Sprint 4a (2026-05-27) — MCP servers register themselves via
    ``mcp_client.MCPClientManager.load_server`` which builds a ``Skill``
    with ``scopes=["mcp"]``. Those skills are dynamic (added/removed at
    runtime by the admin UI), so they cannot live in a static profile
    whitelist. Instead, ``resolve_profile_tools`` unions the static
    whitelist with the set returned here.

    Wrapped in a broad except so a registry import failure or a partial
    test harness never breaks tool binding — worst case we return an
    empty set and only the static whitelist applies (i.e. legacy
    behaviour).
    """
    try:
        from app.skills.registry import get_skill_registry

        names: set[str] = set()
        for skill in get_skill_registry().list_skills():
            if "mcp" in (skill.scopes or ()):
                names.update(t.name for t in skill.tools)
        return names
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("toolset_profiles: MCP tool discovery failed (%s)", exc)
        return set()


# Outils d'annulation (Reversible Journal). Unis au bind UNIQUEMENT si le flag
# reversible_journal_enabled est ON — même logique dynamique que les skills MCP.
# Flag OFF (défaut prod) ⇒ ensemble vide ⇒ zéro coût de prompt.
_REVERSIBLE_TOOL_NAMES = ("list_revertible_actions", "revert_action", "undo_last_action")


def _reversible_tool_names() -> set[str]:
    try:
        from app.config import get_settings
        if getattr(get_settings(), "reversible_journal_enabled", False):
            return set(_REVERSIBLE_TOOL_NAMES)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("toolset_profiles: reversible flag check failed (%s)", exc)
    return set()


def resolve_profile_tools(name: str, all_tools: Sequence) -> list:
    """Return the subset of ``all_tools`` belonging to profile ``name``.

    Tools listed in the profile but missing from the registry are dropped
    silently with a debug log (typo / disabled skill / etc.).

    MCP tools (those belonging to a skill with ``scopes=["mcp"]``) are
    **always included** on top of the static whitelist — MCP servers are
    added at runtime via the admin UI, so it would be impossible to
    enumerate them by name in a static tuple. The wire-up makes any tool
    exposed by an MCP server immediately bindable by the LLM, without
    having to edit ``_DEFAULT_TOOLS``.

    Parameters
    ----------
    name
        Profile name (e.g. ``"default"``).
    all_tools
        Sequence of LangChain tool objects, each having a ``.name`` attribute.

    Returns
    -------
    list
        Tools in registration order, filtered to ``profile ∪ mcp-skills``.
    """
    wanted = set(get_profile_tool_names(name))
    wanted |= _mcp_tool_names()
    wanted |= _reversible_tool_names()
    have = {t.name for t in all_tools}
    missing = wanted - have
    if missing:
        logger.debug(
            "toolset_profiles[%s]: %d tool(s) listed but not registered: %s",
            name, len(missing), sorted(missing),
        )
    return [t for t in all_tools if t.name in wanted]


def auto_detect_profile(first_user_message: str) -> str:
    """Choose a profile from the user's first message.

    Currently always returns ``"default"`` because we ship with a single
    profile. Future expansion will add keyword classifiers (``ssh|cron``
    → automation, ``génère image|illustre|youtube`` → creative, etc.).
    Keeping this hook in place now means callers don't have to change
    when more profiles arrive.
    """
    return DEFAULT_PROFILE


async def resolve_conversation_profile(
    conversation_id: str, user_message: str = ""
) -> str:
    """Profil d'outils de cette conversation — auto-détecté et persisté au
    premier tour, réutilisé ensuite.

    V1 temps 1 : extrait de `routers/chat.py`, où il vivait en ligne. Les
    canaux et la voix en ont besoin **à l'identique** — c'est ce champ qui
    court-circuite le routeur (`supervisor.py`) et donne le runtime unique,
    celui que le banc A/B a mesuré comme plus rapide ET plus juste.

    Le profil est figé au premier tour pour que le catalogue d'outils reste
    stable aux yeux du modèle d'une question à l'autre.

    Best-effort : sur erreur ou conversation inconnue, rend la chaîne vide —
    le tour repart alors sur le chemin historique plutôt que d'échouer.
    """
    if not conversation_id:
        return ""
    try:
        from app.database import async_session
        from app.models.conversation import Conversation

        async with async_session() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv is None:
                return ""
            if not conv.toolset_profile:
                conv.toolset_profile = auto_detect_profile(user_message or "")
                await db.commit()
                logger.info(
                    "[toolset_profile] auto-detected '%s' for conv=%s",
                    conv.toolset_profile, conversation_id,
                )
            return conv.toolset_profile or DEFAULT_PROFILE
    except Exception as exc:  # noqa: BLE001
        logger.warning("toolset_profile resolve failed: %s", exc)
        return ""
