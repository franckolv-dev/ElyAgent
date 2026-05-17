# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/toolset_profiles.py
# @brief      Static per-conversation toolset profiles (Hermes Chantier 1)
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
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
    # Universal — memory, preferences, knowledge (always present)
    "knowledge_list",
    "knowledge_search",
    "smart_knowledge_query",
    "save_user_preference",
    "save_constraint",            # HITL-gated, harmless to expose
    # Memory — durable facts via MemGPT-style hierarchical store
    "memory_archive",
    "memory_search",
    # Sprint 1 (2026-05-15) — cross-conversation recall.
    # Lets the agent answer "do you remember…", "what did we say
    # about…" by searching past conversations via FTS5 + summarising
    # via Ministral 3B local.
    "search_past_conversations_tool",
    # Notes — quick scratch storage
    "notes_create",
    "notes_list",
    "notes_search",
    # Gmail — read + send + reply (the 80% of email work)
    "gmail_list_emails",
    "gmail_read_email",
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
    "gmail_empty_trash",
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
    # Drive — create text files + list + read + find duplicates + trash
    "drive_create_file",
    "drive_list_files",
    "drive_read_file",
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
    # Web search (DuckDuckGo / SerpAPI fallback path)
    "web_search",
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


def resolve_profile_tools(name: str, all_tools: Sequence) -> list:
    """Return the subset of ``all_tools`` belonging to profile ``name``.

    Tools listed in the profile but missing from the registry are dropped
    silently with a debug log (typo / disabled skill / etc.).

    Parameters
    ----------
    name
        Profile name (e.g. ``"default"``).
    all_tools
        Sequence of LangChain tool objects, each having a ``.name`` attribute.

    Returns
    -------
    list
        Tools in registration order, filtered to the profile's whitelist.
    """
    wanted = set(get_profile_tool_names(name))
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
