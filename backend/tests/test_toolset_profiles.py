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
from app.skills.base import Skill
from app.skills.registry import get_skill_registry


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
    Bumped to 70 in 2026-05-13 after adding 9 browser_extension tools
    (the Chrome companion that lets the agent act in the user's real
    tabs — list/open/wait/read/screenshot/close). Note: the Playwright
    server-side tools are dynamically REMOVED at bind time when the
    extension is connected, so the runtime toolset stays smaller (~51)
    even though the static profile is now 59.
    Bumped to 75 in 2026-05-20 to make room for orchestrate (Sprint 2.7,
    Programmatic Tool Calling sandbox — see toolset_profiles.py).
    Bumped to 80 in 2026-05-29 for Sprint 4b Phase 4.b (skill_view +
    progressive-disclosure room for one or two more tools landing soon
    without re-bumping the cap on every commit).
    DeepSeek / Mistral Small / Mistral Large handle 50-80 tools
    comfortably; xLAM-style fragile FC-tunes are no longer in the chain."""
    tools = get_profile_tool_names("default")
    assert 25 <= len(tools) <= 80, f"default has {len(tools)} tools (target 25-80)"


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


def test_default_profile_exposes_full_scheduler_lifecycle():
    """ELY must be able to create AND list AND delete her own scheduled tasks.

    Regression guard for the 2026-05-14 audit: ELY had ``scheduler_create_task``
    in the default profile but not ``scheduler_list_tasks`` /
    ``scheduler_delete_task``, so when a user asked her to remove the
    6 individual cron jobs she had just consolidated into 2, she answered:

        "Je n'ai pas d'outil direct pour supprimer des tâches planifiées.
         J'ai créé une tâche qui s'exécutera demain à 9h pour faire le
         ménage, mais ce n'est pas idéal."

    She literally scheduled a cleanup task at 9am to delete the others.
    Fixing the toolset_profiles entry restores the full lifecycle.
    """
    tools = set(get_profile_tool_names("default"))
    lifecycle = {
        "scheduler_create_task",
        "scheduler_list_tasks",
        "scheduler_delete_task",
    }
    missing = lifecycle - tools
    assert not missing, (
        f"Scheduler lifecycle incomplete in default profile: {missing}. "
        "ELY needs all three to manage her own cron jobs without resorting "
        "to 'schedule a task to delete the others tomorrow' workarounds."
    )


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


def test_default_profile_exposes_drive_organisation_tools():
    """« Organise mes fichiers Drive par année » needs to create real
    folders and move files into them. A Drive-reorg session (2026-06-03)
    failed because the default profile only had drive_create_file: the
    agent created "folders" as text/plain files and then truthfully said
    it had no way to make folders or move files. These tools exist in
    drive_tool.py + GOOGLE_TOOLS but were missing from the default profile
    (the "tool invisible" trap). They are non-destructive (no HITL)."""
    tools = set(get_profile_tool_names("default"))
    for name in ("drive_create_folder", "drive_move_file", "drive_copy_file", "drive_rename_file"):
        assert name in tools, (
            f"{name} missing from default profile — Drive organisation "
            "workflows (create folders + move files) will fail"
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


# ── MCP wire-up (Sprint 4a J1.5a, 2026-05-27) ────────────────────────────────


@pytest.fixture
def _mcp_skill_in_registry():
    """Register a fake MCP skill (scopes=["mcp"]) and clean up after the test.

    The MCPClientManager registers skills with scopes=["mcp"] at runtime; the
    static profile cannot enumerate them, so resolve_profile_tools must
    discover them dynamically via the registry.
    """
    registry = get_skill_registry()
    mcp_tool_a = _FakeTool("mcp_time_get_current_time")
    mcp_tool_b = _FakeTool("mcp_time_convert_time")
    skill = Skill(
        name="mcp_time_test",
        display_name="MCP Time (test)",
        description="Fake MCP server for tests",
        icon="🔌",
        scopes=["mcp"],
        tools=[mcp_tool_a, mcp_tool_b],
        author="mcp",
    )
    registry.register_or_replace(skill)
    try:
        yield mcp_tool_a, mcp_tool_b
    finally:
        registry.unregister("mcp_time_test")


def test_resolve_includes_mcp_tools_even_when_absent_from_default(_mcp_skill_in_registry):
    """A tool from an MCP-scoped skill MUST pass the filter even when its
    name is NOT in _DEFAULT_TOOLS — that's the whole point of dynamic MCP
    discovery: the admin adds a server at runtime via the API, the tool
    becomes bindable instantly without editing the static whitelist."""
    mcp_a, mcp_b = _mcp_skill_in_registry
    static = _FakeTool("knowledge_list")  # in default
    out_of_default = _FakeTool("totally_not_in_default")
    all_tools = [static, mcp_a, mcp_b, out_of_default]

    resolved = resolve_profile_tools("default", all_tools)
    names = {t.name for t in resolved}

    assert "mcp_time_get_current_time" in names, "MCP tool A must be included"
    assert "mcp_time_convert_time" in names, "MCP tool B must be included"
    assert "knowledge_list" in names, "static whitelist still applies"
    assert "totally_not_in_default" not in names, "non-MCP unlisted tool stays out"


def test_resolve_only_includes_scope_mcp_not_other_scopes():
    """Only the literal scope 'mcp' opts a skill into dynamic inclusion.
    A skill with scopes=['gmail'] or scopes=[] must follow the static
    whitelist like any other."""
    registry = get_skill_registry()
    not_mcp = Skill(
        name="not_mcp_skill",
        display_name="Not MCP",
        description="Some skill with a different scope",
        icon="🧪",
        scopes=["other_service_api_key"],
        tools=[_FakeTool("not_mcp_tool")],
    )
    registry.register_or_replace(not_mcp)
    try:
        all_tools = [_FakeTool("not_mcp_tool"), _FakeTool("knowledge_list")]
        resolved = resolve_profile_tools("default", all_tools)
        names = {t.name for t in resolved}
        assert "not_mcp_tool" not in names, (
            "scopes=['other_service_api_key'] must NOT trigger dynamic inclusion"
        )
        assert "knowledge_list" in names
    finally:
        registry.unregister("not_mcp_skill")


def test_resolve_drops_mcp_skill_after_unload(_mcp_skill_in_registry):
    """After an MCP server is unregistered (admin deletes it), its tools
    must immediately stop being included — no stale binding."""
    mcp_a, _ = _mcp_skill_in_registry
    # Sanity: tool is currently bound
    assert any(t.name == mcp_a.name for t in resolve_profile_tools("default", [mcp_a]))
    # Simulate admin delete
    get_skill_registry().unregister("mcp_time_test")
    # Tool must no longer pass
    resolved = resolve_profile_tools("default", [mcp_a])
    assert not resolved, "MCP tool must vanish from binding after skill unregistered"


# ── auto_detect_profile ──────────────────────────────────────────────────────


def test_auto_detect_returns_default_for_now():
    """Single-profile shipment: every message goes to default."""
    assert auto_detect_profile("Bonjour") == "default"
    assert auto_detect_profile("capture du site et envoi par mail") == "default"
    assert auto_detect_profile("") == "default"


def test_auto_detect_handles_empty_string():
    assert auto_detect_profile("") == DEFAULT_PROFILE
