# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_github_tool.py
# @brief      Tests for the GitHub tools (read-only stats / traffic /
#             notifications). Sprint screencast prep, 2026-05-17.
#
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tests for ``app.agent.tools.github_tool``.

These tests do NOT hit the real GitHub API. They mock ``httpx.AsyncClient``
so the suite stays hermetic and fast. The point is to validate the
plumbing :
    - missing token → clear setup hint
    - repo missing + no default → clear error
    - 403 on traffic → maintainer-only hint
    - 404 → not-found message
    - 200 → expected summary lines

Run with:
    cd backend && .venv/bin/python -m pytest tests/test_github_tool.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools.github_tool import (
    github_notifications,
    github_repo_stats,
    github_traffic_stats,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def no_token(monkeypatch):
    """Settings returns no GitHub token."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "github_token", "", raising=False)
    monkeypatch.setattr(s, "github_default_repo", "", raising=False)


@pytest.fixture
def with_token_and_default(monkeypatch):
    """Settings has both token and default repo configured."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "github_token", "ghp_fake_token", raising=False)
    monkeypatch.setattr(s, "github_default_repo", "franckolv-dev/ElyAgent", raising=False)


def _mock_response(status_code: int, json_data):
    """Build a fake httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(json_data, Exception):
        resp.json.side_effect = json_data
        resp.text = "text body"
    else:
        resp.json.return_value = json_data
    return resp


# ──────────────────────────────────────────────────────────────────────
# Missing-token paths — every tool must give a clear setup hint
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_stats_no_token_returns_setup_hint(no_token):
    result = await github_repo_stats.ainvoke({"owner": "x", "repo": "y"})
    assert "GitHub non configuré" in result
    assert "GITHUB_TOKEN" in result


@pytest.mark.asyncio
async def test_traffic_stats_no_token_returns_setup_hint(no_token):
    result = await github_traffic_stats.ainvoke({"owner": "x", "repo": "y"})
    assert "GitHub non configuré" in result


@pytest.mark.asyncio
async def test_notifications_no_token_returns_setup_hint(no_token):
    result = await github_notifications.ainvoke({})
    assert "GitHub non configuré" in result


# ──────────────────────────────────────────────────────────────────────
# Missing repo + no default → explicit error
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_stats_missing_repo_no_default(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "github_token", "ghp_fake", raising=False)
    monkeypatch.setattr(s, "github_default_repo", "", raising=False)
    result = await github_repo_stats.ainvoke({"owner": "", "repo": ""})
    assert "owner/repo" in result


# ──────────────────────────────────────────────────────────────────────
# Happy path — repo_stats
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_stats_happy_path(with_token_and_default):
    fake_data = {
        "stargazers_count": 142,
        "forks_count": 18,
        "subscribers_count": 9,
        "open_issues_count": 7,
        "language": "Python",
        "default_branch": "main",
        "pushed_at": "2026-05-17T14:30:00Z",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = _mock_response(200, fake_data)
    with patch("app.agent.tools.github_tool.httpx.AsyncClient", return_value=mock_client):
        # Uses default repo from settings
        result = await github_repo_stats.ainvoke({})
    assert "franckolv-dev/ElyAgent" in result
    assert "142" in result  # stars (formatted with non-breaking space possibly)
    assert "Python" in result
    assert "main" in result


# ──────────────────────────────────────────────────────────────────────
# 403 on traffic → maintainer-only hint
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_traffic_stats_403_explains_maintainer_only(with_token_and_default):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = _mock_response(403, {"message": "Forbidden"})
    with patch("app.agent.tools.github_tool.httpx.AsyncClient", return_value=mock_client):
        result = await github_traffic_stats.ainvoke({"owner": "octocat", "repo": "Hello-World"})
    assert "403" in result
    assert "mainteneur" in result.lower() or "admin" in result.lower()


# ──────────────────────────────────────────────────────────────────────
# 404 on repo_stats → explicit not-found
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_stats_404_says_not_found(with_token_and_default):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = _mock_response(404, {"message": "Not Found"})
    with patch("app.agent.tools.github_tool.httpx.AsyncClient", return_value=mock_client):
        result = await github_repo_stats.ainvoke({"owner": "ghost", "repo": "void"})
    assert "introuvable" in result
    assert "ghost/void" in result


# ──────────────────────────────────────────────────────────────────────
# Notifications — empty + non-empty
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notifications_empty_unread(with_token_and_default):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = _mock_response(200, [])
    with patch("app.agent.tools.github_tool.httpx.AsyncClient", return_value=mock_client):
        result = await github_notifications.ainvoke({"unread_only": True})
    assert "Aucune notification" in result


@pytest.mark.asyncio
async def test_notifications_lists_entries(with_token_and_default):
    fake_data = [
        {
            "reason": "mention",
            "repository": {"full_name": "franckolv-dev/ElyAgent"},
            "subject": {
                "title": "Bug : empty trash crashed on 1001 ids",
                "url": "https://api.github.com/repos/franckolv-dev/ElyAgent/issues/42",
            },
        },
        {
            "reason": "review_requested",
            "repository": {"full_name": "franckolv-dev/ElyAgent"},
            "subject": {
                "title": "Sprint 2: tool registry auto-discovery",
                "url": "https://api.github.com/repos/franckolv-dev/ElyAgent/pulls/3",
            },
        },
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = _mock_response(200, fake_data)
    with patch("app.agent.tools.github_tool.httpx.AsyncClient", return_value=mock_client):
        result = await github_notifications.ainvoke({"unread_only": True})
    assert "2 notification" in result
    assert "[mention]" in result
    assert "[review_requested]" in result
    assert "issues/42" in result
    assert "pull/3" in result  # API /pulls/ → web /pull/


# ──────────────────────────────────────────────────────────────────────
# Integration with the toolset profile + skill registry
# ──────────────────────────────────────────────────────────────────────


def test_github_tools_in_default_profile():
    from app.agent.toolset_profiles import _DEFAULT_TOOLS
    for name in ("github_repo_stats", "github_traffic_stats", "github_notifications"):
        assert name in _DEFAULT_TOOLS, f"{name} missing from default toolset profile"


def test_github_skill_registered():
    """After register_all, the github skill must be present."""
    from app.skills.builtin import register_all
    from app.skills import get_skill_registry
    register_all()
    sk = get_skill_registry().get_skill("github")
    assert sk is not None
    names = {t.name for t in sk.tools}
    assert names == {"github_repo_stats", "github_traffic_stats", "github_notifications"}
