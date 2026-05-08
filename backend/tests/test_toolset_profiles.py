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
    """Profile size must stay in the 25-40 tool window — bigger overwhelms small
    models, smaller misses common workflows."""
    tools = get_profile_tool_names("default")
    assert 25 <= len(tools) <= 40, f"default has {len(tools)} tools (target 25-40)"


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
