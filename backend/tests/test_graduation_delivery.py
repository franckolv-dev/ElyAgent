# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_graduation_delivery.py
# @brief      Sprint 4d J5 — livraison d'une graduation : PR via API GitHub
#             (mockée) ou export local, et le pin « jamais de demi-PR ».
# @license    Elastic License 2.0
# =============================================================================
"""Pins J5.

Run with:  cd backend && python -m pytest tests/test_graduation_delivery.py -v
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.learning import graduation_delivery as delivery
from app.services.learning.graduation_delivery import (
    GitHubDeliveryError,
    _branch_name,
    _deliver_via_export,
    _pr_body,
    deliver_graduation,
)

_MANIFEST = {
    "learned_skill_id": "abcd1234-5678",
    "tool_name": "grad_mean_ms",
    "tool_profile": "pure",
    "origin_user": "u_grad_c",
    "created_at": "2026-05-10T00:00:00",
    "graduated_at": "2026-06-10T23:00:00+00:00",
    "stats": {"invocations": 42, "errors_recent": 0, "refusals_recent": 0, "age_days": 31},
    "thresholds": {"min_invocations": 10, "error_free_days": 14, "min_age_days": 7},
    "gates": [{"key": "invocations", "ok": True, "value": 42}],
    "rationale": "test",
}

_FILES = [
    {"path": "backend/app/agent/tools/graduated/__init__.py",
     "content": "# init\n", "create_only": True},
    {"path": "backend/app/agent/tools/graduated/grad_mean_ms_tool.py",
     "content": "# tool source\n", "create_only": False},
    {"path": "backend/tests/test_graduated_grad_mean_ms.py",
     "content": "# test source\n", "create_only": False},
]


class _FakeGitHub:
    """API GitHub minimale en MockTransport — enregistre les appels."""

    def __init__(self, *, init_exists_on_branch: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.put_paths: list[str] = []
        self.init_exists = init_exists_on_branch

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if request.method == "GET" and path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if request.method == "POST" and path.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if request.method == "GET" and "/contents/" in path:
            if self.init_exists and path.endswith("__init__.py"):
                return httpx.Response(200, json={"sha": "oldsha"})
            return httpx.Response(404, json={})
        if request.method == "PUT" and "/contents/" in path:
            self.put_paths.append(path.split("/contents/")[1])
            return httpx.Response(201, json={})
        if request.method == "POST" and path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/x/y/pull/42"})
        return httpx.Response(500, text=f"unexpected {request.method} {path}")


@pytest.fixture
def _with_token(monkeypatch):
    async def _fake_token():
        return "ghp_fake_token"
    monkeypatch.setattr(delivery, "_token", _fake_token)


@pytest.fixture
def _without_token(monkeypatch):
    async def _fake_token():
        return ""
    monkeypatch.setattr(delivery, "_token", _fake_token)


# ── Canal GitHub ──────────────────────────────────────────────────────────────

class TestGitHubChannel:
    @pytest.mark.asyncio
    async def test_happy_path_creates_branch_files_and_pr(self, _with_token):
        fake = _FakeGitHub()
        result = await deliver_graduation(
            manifest=_MANIFEST, files=_FILES,
            transport=httpx.MockTransport(fake.handler),
        )
        assert result["status"] == "pr_created"
        assert result["pr_url"] == "https://github.com/x/y/pull/42"
        assert result["branch"] == "graduate/grad_mean_ms-abcd1234"
        # les 3 fichiers sont poussés (init absent sur la branche → créé)
        assert sorted(fake.put_paths) == sorted(f["path"] for f in _FILES)
        # et la PR est bien le DERNIER appel (jamais de PR avant les fichiers)
        assert fake.calls[-1] == ("POST", "/repos/franckolv-dev/ElyAgent/pulls")

    @pytest.mark.asyncio
    async def test_create_only_init_not_overwritten(self, _with_token):
        fake = _FakeGitHub(init_exists_on_branch=True)
        await deliver_graduation(
            manifest=_MANIFEST, files=_FILES,
            transport=httpx.MockTransport(fake.handler),
        )
        assert not any(p.endswith("__init__.py") for p in fake.put_paths)
        assert len(fake.put_paths) == 2

    @pytest.mark.asyncio
    async def test_github_error_raises_with_context(self, _with_token):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Bad credentials")
        with pytest.raises(GitHubDeliveryError) as err:
            await deliver_graduation(
                manifest=_MANIFEST, files=_FILES,
                transport=httpx.MockTransport(handler),
            )
        assert "401" in str(err.value) and "Bad credentials" in str(err.value)

    def test_branch_name_is_slugged(self):
        assert _branch_name("Grad Mean/MS", "abcdef123456") == "graduate/grad-mean-ms-abcdef12"

    def test_pr_body_carries_the_evidence(self):
        body = _pr_body(_MANIFEST)
        assert "grad_mean_ms" in body
        assert "42" in body                       # invocations
        assert "revue et merge humains" in body   # le garde-fou affiché
        assert "| ✅ | `invocations` | 42 |" in body


# ── Fallback export ───────────────────────────────────────────────────────────

class TestExportFallback:
    @pytest.mark.asyncio
    async def test_no_token_falls_back_to_export(self, _without_token, monkeypatch, tmp_path):
        from pathlib import Path
        monkeypatch.setenv("GRADUATION_EXPORT_DIR", str(tmp_path))
        result = await deliver_graduation(manifest=_MANIFEST, files=_FILES)
        assert result["status"] == "exported"
        root = Path(result["export_path"])
        assert str(root).startswith(str(tmp_path))
        assert (root / _FILES[1]["path"]).read_text() == "# tool source\n"
        manifest = json.loads((root / "grad_manifest.json").read_text())
        assert manifest["tool_name"] == "grad_mean_ms"
        assert "github_graduation_token" in (root / "INSTRUCTIONS.md").read_text()

    def test_export_recreates_repo_relative_paths(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GRADUATION_EXPORT_DIR", str(tmp_path))
        result = _deliver_via_export(_MANIFEST, _FILES)
        import os
        for f in _FILES:
            assert os.path.exists(os.path.join(result["export_path"], f["path"]))
