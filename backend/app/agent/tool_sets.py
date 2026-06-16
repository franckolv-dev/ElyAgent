# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/agent/tool_sets.py
# @brief      Single source of truth for tool name sets
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RESUME DES CONDITIONS :
#   - AUTORISE : Utilisation personnelle, educative et tests prives.
#   - INTERDIT : Toute utilisation commerciale sans accord prealable.
#   - INTERDIT : Redistribution de versions modifiees de ce code.
# =============================================================================
"""Canonical tool-name sets used for credential injection and tool filtering.

Every module that needs to know which tools require Google credentials,
user_id injection, or belong to the memory skill set MUST import from here
instead of maintaining its own copy.  This eliminates drift between
``nodes.py``, ``factory.py``, and ``supervisor.py``.
"""
from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Tools that need Google credentials injection
#
# Every tool in this set also accepts an optional injected `account: str`
# argument used for multi-account selection. The LLM may set it to a
# user-defined alias ("perso", "pro", …) to drive a specific linked Google
# account; empty / "default" / unknown alias falls back to the user's
# default account (mirrored by credential_store / User.google_credentials).
# Resolution happens in `app/agent/sub_agents/factory.py` BEFORE the tool
# is invoked — the `account` arg is stripped after resolution so Google
# API wrappers never see it.
# ──────────────────────────────────────────────────────────────────────────────

GOOGLE_TOOLS: frozenset[str] = frozenset({
    # Gmail
    "gmail_list_emails", "gmail_read_email", "gmail_send_email",
    "gmail_save_attachments_to_drive",
    "gmail_reply_email", "gmail_send_with_attachment",
    "gmail_send_with_local_attachment",   # FIX 2026-05-07 — oubli initial
    "gmail_mark_read", "gmail_mark_unread",
    "gmail_create_draft", "gmail_list_drafts",
    "gmail_list_labels", "gmail_create_label",
    "gmail_move_emails", "gmail_trash_emails", "gmail_search_for_cleanup",
    "gmail_trash_by_category", "gmail_trash_by_query",
    "gmail_batch_modify", "gmail_update_settings", "gmail_raw_api_call",
    # Calendar
    "calendar_list_events", "calendar_create_event",
    "calendar_get_event", "calendar_update_event", "calendar_delete_event",
    "calendar_check_availability", "calendar_list_calendars",
    "calendar_quick_add", "calendar_create_meet_event", "calendar_raw_api_call",
    # Drive
    "drive_list_files", "drive_read_file",
    "drive_create_folder", "drive_create_file", "drive_update_file",
    "drive_upload_local_file",
    "drive_move_file", "drive_rename_file", "drive_delete_file",
    "drive_share_file", "drive_copy_file", "drive_export_file",
    "drive_find_duplicates", "drive_raw_api_call",
    # Docs
    "docs_create_document", "docs_read_document", "docs_append_text",
    "docs_replace_text", "docs_insert_table",
    "docs_batch_update", "docs_raw_api_call",
    # Sheets
    "sheets_create_spreadsheet", "sheets_read_spreadsheet", "sheets_append_rows",
    "sheets_update_cells", "sheets_delete_rows", "sheets_add_sheet", "sheets_list_sheets",
    "sheets_batch_update", "sheets_raw_api_call",
    # Tasks
    "tasks_list", "tasks_create", "tasks_complete",
    "tasks_update", "tasks_delete", "tasks_list_tasklists", "tasks_create_tasklist",
    "tasks_raw_api_call",
    # Contacts (People API)
    "contacts_search", "contacts_list", "contacts_create",
    "contacts_get", "contacts_update", "contacts_delete",
    "contacts_batch_operations", "contacts_raw_api_call",
})

# ──────────────────────────────────────────────────────────────────────────────
# Tools that need user_id injection
# ──────────────────────────────────────────────────────────────────────────────

USER_ID_TOOLS: frozenset[str] = frozenset({
    "scheduler_list_tasks",
    "scheduler_create_task",
    "scheduler_delete_task",
    "scheduler_update_task",
    "scheduler_run_task",
    "delegate",
    # Browser tools — each user has an isolated browser context
    "browser_navigate",
    "browser_search_web",
    "browser_search_images",
    "browser_get_text",
    "browser_screenshot",
    "browser_click",
    "browser_fill",
    "browser_close",
    # Browser extension tools — need user_id to look up the user's
    # connected Chrome extension in the registry
    "browser_list_tabs",
    "browser_open_tab",
    "browser_tab_wait_loaded",
    "browser_tab_wait_for_selector",
    "browser_tab_get_url",
    "browser_tab_read_text",
    "browser_tab_read_html",
    "browser_tab_screenshot",
    "browser_tab_click",
    "browser_tab_fill",
    "browser_tab_navigate",
    "browser_close_tab",
    # Sprint 0.7 — Chrome v2 read-only inspectors (history/bookmarks/downloads)
    "browser_history_search",
    "browser_bookmarks_search",
    "browser_downloads_search",
    # Watchdog tools
    "watchdog_add",
    "watchdog_list",
    "watchdog_remove",
    # Notes tools
    "notes_create",
    "notes_list",
    "notes_read",
    "notes_update",
    "notes_delete",
    "notes_search",
    # Desktop tools — need user_id to look up the daemon connection
    "desktop_list_dir",
    "desktop_read_file",
    "desktop_write_file",
    "desktop_move_file",
    "desktop_delete_file",
    "desktop_create_dir",
    "desktop_stat_file",
    "desktop_hash_file",
    "desktop_search_files",
    # Trainer tools — need user_id for desktop daemon connection
    "trainer_start",
    "trainer_screenshot",
    "trainer_click",
    "trainer_move",
    "trainer_type",
    "trainer_hotkey",
    "trainer_get_screen_size",
    # Memory / preferences tools
    "save_user_preference",
    "save_constraint",
    "knowledge_search",
    "knowledge_list",
    "smart_knowledge_query",
    # MemGPT-style hierarchical memory (archive + search + recent).
    # FIX 2026-05-17 : ces 3 tools avaient `user_id: InjectedToolArg`
    # dans leur signature mais étaient absents de cette frozenset, donc
    # le runtime n'injectait jamais user_id. DeepSeek v4-flash le voyait
    # alors comme un paramètre à remplir et répondait honnêtement
    # « le tool mémoire attend un user_id que je n'ai pas ». Toute la
    # mémoire archive cassée silencieusement, fallback systématique sur
    # notes_create. Same class of bug que search_past_conversations_tool
    # corrigé la semaine dernière — preuve qu'il faut une CI qui détecte
    # automatiquement les tools avec InjectedToolArg absents de cette set.
    "memory_archive",
    "memory_view_profile",
    "memory_search",
    "memory_recent",
    # Sprint 2.5 (2026-05-21) — unified typed memory recall.
    # New tool replacing memory_search/notes_search/... incrementally;
    # injects user_id so the LLM cannot tamper with the scope.
    "memory_recall",
    # Sprint 4b Phase 4.b (2026-05-29) — progressive disclosure on
    # auto-learned playbooks. user_id injected so the LLM can NEVER
    # read another user's playbooks across the multi-user instance.
    "skill_view",
    # Sprint 1 (2026-05-15) — cross-conversation memory recall.
    # Different from memory_search (structured fact store) and
    # knowledge_search (uploaded documents). Searches the literal
    # messages of every past conversation and summarises the top
    # matches via Ministral 3B local. user_id injected so the LLM
    # never sees a foreign user's history.
    "search_past_conversations_tool",
    # System self-diagnostic tools — scoped per user (logs/missions/tasks/channels)
    # Must receive the calling user's id so they only return that user's data,
    # never another user's. system_get_health and system_check_llm_providers
    # are intentionally global (no user_id) — they describe the backend itself.
    "system_get_logs",
    "system_list_scheduled_tasks",
    "system_list_missions",
    "system_check_channels",
    # Telegram outbound — recipient is ALWAYS the calling user themselves
    # (resolved from User.telegram_id). user_id injected so the LLM can't
    # target arbitrary chats.
    "telegram_send_message",
    # Sprint 2.7 (2026-05-19) — Programmatic Tool Calling sandbox.
    # The orchestrate tool needs user_id to scope every RPC dispatch
    # to the calling user (Gmail / Drive / Calendar / Knowledge / etc.
    # inside the sandbox all run as this user). Adding to USER_ID_TOOLS
    # is mandatory — the CI guard test_user_id_injection_completeness
    # catches it otherwise.
    "orchestrate",
})


# ──────────────────────────────────────────────────────────────────────────────
# Tools restricted to ComplexityTier.COMPLEX (tier C)
# ──────────────────────────────────────────────────────────────────────────────
#
# Some tools need a model capable enough to use them productively. Exposing
# them to SIMPLE (tier A — Ministral 3B local) or MEDIUM (tier B — Mistral
# Small 4) just burns tokens on buggy outputs.
#
# The filter is applied in ``app/agent/nodes.py`` right before
# ``_bind_tools_smart``: if the resolved tier is not COMPLEX, every tool whose
# name appears here is dropped from the binding. The LLM doesn't even see it
# in its tool schema, so there's no risk of accidental invocation.

TIER_C_ONLY_TOOLS: frozenset[str] = frozenset({
    # Sprint 2.7 — orchestrate Python sandbox.
    # Writing a working Python script that drives N tools cleanly was
    # supposed to require frontier-class generation, hence this filter.
    #
    # REMOVED 2026-05-20 during the bench session because the filter
    # interacted badly with the tier downgrade between turns: after the
    # first tool_call, the router classifies the continuation in MEDIUM
    # or IMAGE → orchestrate gets dropped from the binding → the LLM
    # honestly answers « le tool orchestrate n'existe pas » and abandons
    # the workflow. Until we have a "sticky tier" mechanism that keeps
    # tier=complex across the whole turn series of a started workflow,
    # the cure is worse than the disease. Mistral Small / DeepSeek
    # flash actually do produce usable scripts in our small test.
    #
    # To re-enable a per-tier filter once sticky-tier is in place:
    # add tool names back to this frozenset and the existing filter in
    # nodes.py kicks in again automatically.
})

# ──────────────────────────────────────────────────────────────────────────────
# Memory skills — available in every specialist domain
# ──────────────────────────────────────────────────────────────────────────────

MEMORY_SKILLS: frozenset[str] = frozenset({
    "save_user_preference",
    "save_constraint",
    "knowledge_search",
    "knowledge_list",
    "smart_knowledge_query",
    "search_past_conversations_tool",  # Sprint 1 — cross-conversation recall
})
