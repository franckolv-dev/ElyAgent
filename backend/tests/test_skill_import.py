# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_import.py
# @brief      J5-B — import de playbooks SKILL.md depuis une URL
# @license    Elastic License 2.0
# =============================================================================
"""Tests for importing external SKILL.md playbooks (J5-B)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.database import async_session, init_db
from app.models.learned_skill import (
    LearnedSkill,
    SkillContentFormat,
    SkillSource,
    SkillStatus,
)

_VALID_SKILL_MD = """\
---
name: tri-emails-importe
description: Playbook importé pour trier les emails entrants.
tags: [email, import]
---

# Trier les emails entrants

## Quand ce playbook s'applique
- Boîte de réception encombrée.

## Procédure
1. Lister les non-lus.
2. Classer par expéditeur.

## Ce qu'il NE faut PAS faire
- Ne rien supprimer sans confirmation.
"""


def _patch_httpx(monkeypatch, *, text="", status=200, exc=None):
    import app.services.learning.skill_import as mod

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if exc:
                raise exc
            return SimpleNamespace(status_code=status, text=text)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)


@pytest_asyncio.fixture
async def _user():
    await init_db()
    from app.models.user import User
    uid = "imp_" + uuid.uuid4().hex[:8]
    async with async_session() as db:
        db.add(User(id=uid, username=uid, email=f"{uid}@t.local", hashed_password="x"))
        await db.commit()
    yield uid
    async with async_session() as db:
        await db.execute(delete(LearnedSkill).where(LearnedSkill.user_id == uid))
        await db.commit()


async def _count(uid):
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(LearnedSkill)
            .where(LearnedSkill.user_id == uid)
        )).scalar_one()


# ── happy path ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_creates_candidate(_user, monkeypatch):
    from app.services.learning.skill_import import import_skill_from_url
    _patch_httpx(monkeypatch, text=_VALID_SKILL_MD)

    out = await import_skill_from_url("https://example.com/SKILL.md", _user)
    assert out["status"] == "imported"
    assert out["name"] == "tri-emails-importe"

    async with async_session() as db:
        skill = (await db.execute(
            select(LearnedSkill).where(LearnedSkill.id == out["skill_id"])
        )).scalar_one()
    # External content lands as a CANDIDATE (admin reviews before it goes live).
    assert skill.status == SkillStatus.CANDIDATE
    assert skill.source == SkillSource.IMPORTED_MARKETPLACE
    assert skill.content_format == SkillContentFormat.MARKDOWN_PLAYBOOK
    assert "Procédure" in skill.content


@pytest.mark.asyncio
async def test_import_is_idempotent(_user, monkeypatch):
    from app.services.learning.skill_import import import_skill_from_url
    _patch_httpx(monkeypatch, text=_VALID_SKILL_MD)
    first = await import_skill_from_url("https://example.com/SKILL.md", _user)
    second = await import_skill_from_url("https://example.com/SKILL.md", _user)
    assert first["status"] == "imported"
    assert second["status"] == "duplicate"
    assert await _count(_user) == 1


# ── error paths (no HTTP call needed) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_rejects_bad_url(_user):
    from app.services.learning.skill_import import import_skill_from_url
    assert (await import_skill_from_url("", _user))["status"] == "error"
    assert (await import_skill_from_url("ftp://x/y", _user))["status"] == "error"
    assert (await import_skill_from_url("not-a-url", _user))["status"] == "error"
    assert await _count(_user) == 0


@pytest.mark.asyncio
async def test_import_blocks_local_host(_user):
    from app.services.learning.skill_import import import_skill_from_url
    for u in ("http://localhost/SKILL.md", "http://127.0.0.1/x", "http://192.168.1.5/x"):
        out = await import_skill_from_url(u, _user)
        assert out["status"] == "error"
    assert await _count(_user) == 0


@pytest.mark.asyncio
async def test_import_bad_content(_user, monkeypatch):
    from app.services.learning.skill_import import import_skill_from_url
    _patch_httpx(monkeypatch, text="ceci n'est pas un SKILL.md")
    out = await import_skill_from_url("https://example.com/x.md", _user)
    assert out["status"] == "error"
    assert await _count(_user) == 0


@pytest.mark.asyncio
async def test_import_http_404(_user, monkeypatch):
    from app.services.learning.skill_import import import_skill_from_url
    _patch_httpx(monkeypatch, status=404, text="nope")
    out = await import_skill_from_url("https://example.com/missing.md", _user)
    assert out["status"] == "error"
    assert await _count(_user) == 0


@pytest.mark.asyncio
async def test_import_fetch_exception(_user, monkeypatch):
    from app.services.learning.skill_import import import_skill_from_url
    _patch_httpx(monkeypatch, exc=RuntimeError("boom"))
    out = await import_skill_from_url("https://example.com/x.md", _user)
    assert out["status"] == "error"
    assert await _count(_user) == 0
