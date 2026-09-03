# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_phase0_hardening.py
# @brief      Revue multi-utilisateurs 2026-06-10, Phase 0 — pins :
#             B-13 (PII voice), B-18 (headers + TTL token), chemin DB
#             absolu, voix TTS câblée sur settings.
# @license    MIT
# =============================================================================
"""Phase 0 hardening pins (revue 2026-06-10)."""
from __future__ import annotations

import types

import pytest


# ─────────────────────────────────────────────────────────────────────────
# B-13 — l'historique assistant du canal vocal est ré-anonymisé (port #55)
# ─────────────────────────────────────────────────────────────────────────


def _row(role: str, content: str):
    return types.SimpleNamespace(role=role, content=content)


def test_voice_history_reanonymizes_assistant_messages() -> None:
    from app.routers.voice import _anonymized_history
    from app.services.security_filter import SecurityFilter

    sf = SecurityFilter()
    rows = [
        _row("user", "écris à jean.dupont@example.com"),
        _row("assistant", "J'ai envoyé le mail à jean.dupont@example.com."),
        _row("user", "merci"),  # message courant — exclu par le helper
    ]
    msgs = _anonymized_history(rows, sf)

    assert len(msgs) == 2
    for m in msgs:
        assert "jean.dupont@example.com" not in str(m.content), (
            "PII en clair ré-injectée vers le LLM — régression du fix #55 "
            "sur le canal vocal (B-13)"
        )
    # Le placeholder remplace bien l'email (mapping déterministe par session)
    assert "[EMAIL" in str(msgs[0].content)
    assert "[EMAIL" in str(msgs[1].content)


def test_voice_history_excludes_current_message() -> None:
    from app.routers.voice import _anonymized_history
    from app.services.security_filter import SecurityFilter

    rows = [_row("user", "seul message")]
    assert _anonymized_history(rows, SecurityFilter()) == []


# ─────────────────────────────────────────────────────────────────────────
# B-18/D1 — headers de sécurité sur toutes les réponses
# ─────────────────────────────────────────────────────────────────────────


def _make_app(monkeypatch, cookie_secure: bool):
    from fastapi import FastAPI

    import app.middleware.security_headers as sh

    monkeypatch.setattr(
        sh, "get_settings",
        lambda: types.SimpleNamespace(cookie_secure=cookie_secure),
    )
    app = FastAPI()
    sh.add_security_headers(app)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_security_headers_present(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(monkeypatch, cookie_secure=False))
    resp = client.get("/ping")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # Pas de HSTS en HTTP clair (dev) — un no-op trompeur sinon.
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_only_when_cookie_secure(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(monkeypatch, cookie_secure=True))
    resp = client.get("/ping")
    assert resp.headers["Strict-Transport-Security"].startswith("max-age=")


# ─────────────────────────────────────────────────────────────────────────
# B-18/D2 + chemin DB + voix TTS — défauts de Settings
# ─────────────────────────────────────────────────────────────────────────


def _fresh_settings(monkeypatch, **overrides):
    """Settings hermétiques : ni .env, ni les env vars du runner CI
    (la CI exporte DATABASE_URL=:memory: qui écraserait les défauts
    qu'on veut précisément tester)."""
    from app.config import Settings

    for var in (
        "DATABASE_URL", "TTS_VOICE", "ACCESS_TOKEN_EXPIRE_MINUTES",
        "CORS_ORIGINS", "FRONTEND_URL", "COOKIE_SECURE",
    ):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        jwt_secret_key="x" * 32,
        **overrides,
    )


def test_access_token_default_ttl_is_15_minutes(monkeypatch) -> None:
    assert _fresh_settings(monkeypatch).access_token_expire_minutes == 15


def test_default_sqlite_url_is_anchored_to_backend_dir(monkeypatch) -> None:
    """Le défaut relatif dépendait du cwd → deux bases divergentes
    constatées en réel le 9 juin (racine + backend/). Le défaut est
    désormais absolu, ancré sur backend/."""
    from pathlib import Path

    url = _fresh_settings(monkeypatch).database_url
    assert url.startswith("sqlite+aiosqlite:////"), url
    path = Path(url.split("sqlite+aiosqlite:///")[-1])
    assert path.is_absolute()
    assert path.name == "cyberentity.db"
    assert path.parent.name == "backend"


def test_explicit_database_url_passes_through_unchanged(monkeypatch) -> None:
    custom = "sqlite+aiosqlite:////app/data/cyberentity.db"
    assert _fresh_settings(monkeypatch, database_url=custom).database_url == custom
    pg = "postgresql+asyncpg://ely:pw@db:5432/ely"
    assert _fresh_settings(monkeypatch, database_url=pg).database_url == pg


def test_tts_voice_default_is_vivienne_and_wired(monkeypatch) -> None:
    """Le setting tts_voice existait mais n'était lu nulle part — la voix
    restait épinglée sur DeniseNeural dans 2 constantes séparées."""
    assert _fresh_settings(monkeypatch).tts_voice == "fr-FR-VivienneMultilingualNeural"

    from app.config import get_settings
    from app.routers import tts as tts_mod
    from app.services import voice_service

    assert tts_mod.DEFAULT_VOICE == get_settings().tts_voice
    assert voice_service.DEFAULT_VOICE == get_settings().tts_voice


def test_tts_rate_default_and_wired(monkeypatch) -> None:
    """+20% était perçu trop rapide / pas naturel avec Vivienne (retour
    Franck 2026-06-10) → +10%, câblé aux DEUX chemins (router TTS + voice
    WebSocket) via settings.tts_rate, override env TTS_RATE."""
    assert _fresh_settings(monkeypatch).tts_rate == "+10%"

    from app.config import get_settings
    from app.routers import tts as tts_mod
    from app.services import voice_service

    assert tts_mod.DEFAULT_RATE == get_settings().tts_rate
    assert voice_service.DEFAULT_RATE == get_settings().tts_rate


def test_cors_warning_when_https_without_allowlist(monkeypatch, caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        _fresh_settings(
            monkeypatch, frontend_url="https://ely.example.com", cors_origins="",
        )
    assert any("CORS_ORIGINS" in r.message for r in caplog.records)
