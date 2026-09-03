# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tts_requires_auth.py
# @brief      La synthèse vocale demande un utilisateur connecté.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""`/tts/speak` et `/tts/voices` étaient sans authentification (audit du 02/09/2026).

Quiconque atteignait l'API pouvait faire synthétiser du texte aux frais du
déploiement, seule la limite globale de 60 requêtes par minute s'appliquait.
Toutes les autres routes passent par `get_current_user` ; celles-ci aussi.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI


def _app() -> FastAPI:
    from app.routers.tts import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_speak_sans_jeton_est_refuse() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t",
    ) as client:
        r = await client.post("/tts/speak", json={"text": "Bonjour"})
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_voices_sans_jeton_est_refuse() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t",
    ) as client:
        r = await client.get("/tts/voices")
    assert r.status_code in (401, 403), r.text
