"""Tests for the static per-conversation toolset profiles (Hermes Chantier 1)."""
import pytest

from app.agent.toolset_profiles import (
    DEFAULT_PROFILE,
    auto_detect_profile,
    get_profile_tool_names,
    is_valid_profile,
    list_profiles,
    resolve_profile_tools,
)


# ── Profile registry ─────────────────────────────────────────────────────────


def test_default_profile_exists():
    assert is_valid_profile("default")
    assert DEFAULT_PROFILE == "default"


def test_default_profile_in_list():
    assert "default" in list_profiles()


def test_unknown_profile_falls_back_to_default(caplog):
    """Asking for an unregistered profile returns the default tuple, not crash."""
    fallback_tools = get_profile_tool_names("does_not_exist")
    default_tools = get_profile_tool_names("default")
    assert fallback_tools == default_tools


def test_default_profile_has_reasonable_size():
    """Profile size must stay in a reasonable window — bigger overwhelms
    small models (xLAM-2 8B drowned at 50+), smaller misses common workflows.
    Bumped to 55 in 2026-05-09 after adding 9 ELY Desktop filesystem tools.
    DeepSeek / Mistral Small / Mistral Large handle 50+ tools comfortably;
    xLAM-style fragile FC-tunes are no longer in the chain anyway."""
    tools = get_profile_tool_names("default")
    assert 25 <= len(tools) <= 55, f"default has {len(tools)} tools (target 25-55)"


def test_default_profile_no_duplicates():
    tools = get_profile_tool_names("default")
    assert len(tools) == len(set(tools))


def test_default_profile_includes_universals():
    """Memory + knowledge tools must be in every profile so cross-session
    context survives."""
    tools = set(get_profile_tool_names("default"))
    universals = {
        "knowledge_list",
        "knowledge_search",
        "smart_knowledge_query",
        "save_user_preference",
        "save_constraint",
    }
    missing = universals - tools
    assert not missing, f"Universals missing from default: {missing}"


def test_default_profile_covers_capture_mail_drive_workflow():
    """The recurring workflow that exposed all the bugs: capture site +
    mail to address + save to drive. The profile MUST include the three
    needed tools."""
    tools = set(get_profile_tool_names("default"))
    must_have = {
        "browser_screenshot",            # capture
        "gmail_send_with_local_attachment",  # mail with file
        "drive_create_file",             # drive write
    }
    missing = must_have - tools
    assert not missing, f"Capture+mail+drive workflow tools missing: {missing}"


def test_default_profile_covers_mail_cleanup_workflow():
    """« Supprime tous les mails de X » is a daily-driver chat workflow.
    Without these tools exposed in the sticky profile, the LLM hallucinates
    `gmail_delete_email` (which doesn't exist) and the loop dies on
    « tool not available ». Mission nodes work because they bind by
    keyword booster — chat does NOT, so the profile must carry them."""
    tools = set(get_profile_tool_names("default"))
    must_have = {
        "gmail_search_for_cleanup",
        "gmail_trash_by_category",
        "gmail_trash_emails",
    }
    missing = must_have - tools
    assert not missing, f"Mail cleanup tools missing from default profile: {missing}"


def test_default_profile_exposes_drive_find_duplicates():
    """Asking « find duplicate files in /perso » without this tool means
    asking an 8-24B local model to do a recursive walk + pairwise comparison
    in working memory. We saw Ministral 14B OOM Metal on this scenario
    after 21 messages (mai 2026). The dedicated tool collapses 30+ tool
    calls into one — must stay in the default profile."""
    tools = set(get_profile_tool_names("default"))
    assert "drive_find_duplicates" in tools, (
        "drive_find_duplicates missing — duplicate-finding scenarios will "
        "fall back to manual recursive listing and OOM small local models"
    )


def test_default_profile_exposes_drive_delete_file():
    """drive_find_duplicates is useless without a way to act on the result.
    Natural follow-up « OK, supprime ces doublons » needs drive_delete_file
    in the toolset. The tool itself is a soft trash (30-day Drive recycle
    bin) and is locked into LOCKED_HITL_TOOLS, so it cannot fire without
    user confirmation."""
    tools = set(get_profile_tool_names("default"))
    assert "drive_delete_file" in tools, (
        "drive_delete_file missing — user can find duplicates but not "
        "remove them, which is the obvious follow-up action"
    )


def test_default_profile_exposes_desktop_filesystem_tools():
    """ELY Desktop = local filesystem access via the Go daemon. Without
    these in the profile, asking « lis ce fichier sur mon Mac » makes the
    LLM honestly answer « je ne peux pas » (good — no confabulation) but
    leaves a useful capability locked behind a profile gap.

    Read-only tools have no HITL gate (just sandbox check). Write tools
    (write/move/delete/create_dir) are all in LOCKED_HITL_TOOLS, so even
    when exposed they cannot fire without user confirmation."""
    tools = set(get_profile_tool_names("default"))
    read_tools = {
        "desktop_list_dir",
        "desktop_read_file",
        "desktop_search_files",
        "desktop_stat_file",
        "desktop_hash_file",
    }
    write_tools = {
        "desktop_write_file",
        "desktop_move_file",
        "desktop_delete_file",
        "desktop_create_dir",
    }
    missing_read = read_tools - tools
    missing_write = write_tools - tools
    assert not missing_read, f"Desktop read tools missing: {missing_read}"
    assert not missing_write, f"Desktop write tools missing: {missing_write}"


def test_desktop_write_tools_are_hitl_locked():
    """Belt-and-braces check: even if a future maintainer accidentally
    removes a desktop write tool from LOCKED_HITL_TOOLS, this test catches
    it. The four desktop write tools must remain user-confirmable, full
    stop — they touch the user's disk."""
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS

    write_tools = {
        "desktop_write_file",
        "desktop_move_file",
        "desktop_delete_file",
        "desktop_create_dir",
    }
    missing = write_tools - LOCKED_HITL_TOOLS
    assert not missing, (
        f"Desktop write tools must be locked into LOCKED_HITL_TOOLS, "
        f"missing: {missing}"
    )


def test_default_profile_exposes_gmail_settings():
    """Mail-audit workflows often end with the LLM proposing « je vais
    créer des filtres pour bloquer ce bruit ». If `gmail_update_settings`
    isn't in the profile, the LLM confabulates a success without ever
    calling the tool (observed 2026-05-08 with Qwen 3.6 Flash). Lock the
    tool into the default profile so the proposal can actually execute."""
    tools = set(get_profile_tool_names("default"))
    assert "gmail_update_settings" in tools, (
        "gmail_update_settings missing — the LLM will confabulate filter "
        "creation success messages with no tool call ever happening"
    )


# ── resolve_profile_tools ────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_resolve_filters_to_profile_subset():
    all_tools = [
        _FakeTool("gmail_send_email"),
        _FakeTool("browser_screenshot"),
        _FakeTool("ssh_execute"),       # not in default
        _FakeTool("watchdog_add"),      # not in default
        _FakeTool("knowledge_list"),
    ]
    resolved = resolve_profile_tools("default", all_tools)
    names = {t.name for t in resolved}
    assert "gmail_send_email" in names
    assert "browser_screenshot" in names
    assert "knowledge_list" in names
    assert "ssh_execute" not in names
    assert "watchdog_add" not in names


def test_resolve_drops_missing_tools_silently():
    """Profile lists tools that aren't registered → just skip them."""
    # default profile lists ~33 tools; if we only register 1 of them, the
    # resolved list has just 1.
    one_tool = [_FakeTool("knowledge_list")]
    resolved = resolve_profile_tools("default", one_tool)
    assert len(resolved) == 1
    assert resolved[0].name == "knowledge_list"


def test_resolve_unknown_profile_uses_default():
    all_tools = [
        _FakeTool("browser_screenshot"),
        _FakeTool("ssh_execute"),
    ]
    resolved = resolve_profile_tools("nonexistent_profile", all_tools)
    names = {t.name for t in resolved}
    # browser_screenshot is in default, ssh_execute is not
    assert "browser_screenshot" in names
    assert "ssh_execute" not in names


def test_resolve_empty_input():
    assert resolve_profile_tools("default", []) == []


# ── auto_detect_profile ──────────────────────────────────────────────────────


def test_auto_detect_returns_default_for_now():
    """Single-profile shipment: every message goes to default."""
    assert auto_detect_profile("Bonjour") == "default"
    assert auto_detect_profile("capture du site et envoi par mail") == "default"
    assert auto_detect_profile("") == "default"


def test_auto_detect_handles_empty_string():
    assert auto_detect_profile("") == DEFAULT_PROFILE
