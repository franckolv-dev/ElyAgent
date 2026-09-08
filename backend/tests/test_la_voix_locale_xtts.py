# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_la_voix_locale_xtts.py
# @brief      La voix d'Ely peut venir du service local XTTS (voix clonée) :
#             bascule par réglage, repli sur edge-tts si le service manque.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""08/09/2026 — la voix edge-tts (Microsoft) était jugée trop synthétique, et
chaque réponse lue à voix haute partait chez Microsoft. XTTS-v2 tourne sur
la machine (voir voice/xtts) avec la voix clonée de l'épouse de Franck, avec
son accord : le texte lu ne quitte plus la machine.

Le backend ne porte pas le modèle : il appelle le service local, et retombe
sur edge-tts si celui-ci ne répond pas — une voix qui se tait n'est jamais
un progrès.

Run with:  cd backend && python -m pytest tests/test_la_voix_locale_xtts.py -v
"""
from __future__ import annotations

import httpx
import pytest


def _reglages(monkeypatch, **valeurs):
    import app.config as cfg

    s = cfg.get_settings()
    for k, v in valeurs.items():
        monkeypatch.setattr(s, k, v, raising=True)
    return s


def _transport(reponses: dict):
    """Un faux service XTTS : {chemin: (statut, corps, content-type)}."""
    def handler(request: httpx.Request) -> httpx.Response:
        statut, corps, ctype = reponses.get(request.url.path, (404, b"", "text/plain"))
        return httpx.Response(statut, content=corps, headers={"content-type": ctype})
    return httpx.MockTransport(handler)


def test_les_reglages_existent_avec_edge_par_defaut():
    from app.config import Settings

    champs = Settings.model_fields
    assert champs["tts_provider"].default == "edge"
    assert champs["xtts_url"].default == "http://host.docker.internal:8020"
    assert "xtts_voice" in champs and "xtts_timeout_s" in champs


@pytest.mark.asyncio
async def test_le_fournisseur_xtts_rend_le_wav_du_service(monkeypatch):
    from app.services import tts_engine

    _reglages(monkeypatch, tts_provider="xtts", xtts_url="http://xtts.test", xtts_voice="gert")
    vu: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vu["path"] = request.url.path
        vu["json"] = request.read()
        return httpx.Response(200, content=b"RIFF....WAVEfake", headers={"content-type": "audio/wav"})

    audio, mime = await tts_engine.synthetiser(
        "Bonjour Franck.", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert (audio, mime) == (b"RIFF....WAVEfake", "audio/wav")
    assert vu["path"] == "/speak"
    assert b'"voice": "gert"' in vu["json"] or b'"voice":"gert"' in vu["json"]


@pytest.mark.asyncio
async def test_sans_service_xtts_la_voix_retombe_sur_edge(monkeypatch, caplog):
    from app.services import tts_engine

    _reglages(monkeypatch, tts_provider="xtts", xtts_url="http://xtts.test")

    async def _edge(texte, voix, debit):
        return b"ID3mp3-de-secours", "audio/mpeg"

    monkeypatch.setattr(tts_engine, "_synthetiser_edge", _edge)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    audio, mime = await tts_engine.synthetiser(
        "Bonjour.", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert (audio, mime) == (b"ID3mp3-de-secours", "audio/mpeg")
    assert "repli" in caplog.text.lower()


@pytest.mark.asyncio
async def test_une_erreur_du_service_xtts_retombe_aussi_sur_edge(monkeypatch):
    from app.services import tts_engine

    _reglages(monkeypatch, tts_provider="xtts", xtts_url="http://xtts.test")

    async def _edge(texte, voix, debit):
        return b"mp3", "audio/mpeg"

    monkeypatch.setattr(tts_engine, "_synthetiser_edge", _edge)
    client = httpx.AsyncClient(transport=_transport({"/speak": (500, b"boom", "text/plain")}))
    assert await tts_engine.synthetiser("Bonjour.", client=client) == (b"mp3", "audio/mpeg")


@pytest.mark.asyncio
async def test_le_fournisseur_edge_n_appelle_jamais_le_service(monkeypatch):
    from app.services import tts_engine

    _reglages(monkeypatch, tts_provider="edge")
    appels: list = []

    async def _edge(texte, voix, debit):
        appels.append((texte, voix, debit))
        return b"mp3", "audio/mpeg"

    monkeypatch.setattr(tts_engine, "_synthetiser_edge", _edge)

    def handler(request):
        raise AssertionError("le service XTTS ne doit pas être appelé")

    await tts_engine.synthetiser("Salut.", voix="fr-FR-DeniseNeural", debit="+5%",
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert appels == [("Salut.", "fr-FR-DeniseNeural", "+5%")]


@pytest.mark.asyncio
async def test_l_etat_dit_le_fournisseur_et_les_voix_du_service(monkeypatch):
    from app.services import tts_engine

    _reglages(monkeypatch, tts_provider="xtts", xtts_url="http://xtts.test", xtts_voice="gert")
    client = httpx.AsyncClient(transport=_transport({
        "/health": (200, b'{"ok": true, "voices": ["gert"], "default_voice": "gert", "device": "mps"}', "application/json"),
    }))
    etat = await tts_engine.etat(client=client)
    assert etat["provider"] == "xtts"
    assert etat["xtts"] == {"reachable": True, "voices": ["gert"], "default_voice": "gert", "device": "mps"}
    assert etat["voice"] == "gert"


@pytest.mark.asyncio
async def test_l_endpoint_speak_passe_par_le_moteur(monkeypatch):
    from types import SimpleNamespace

    from app.routers import tts as routeur
    from app.services import tts_engine

    async def _synth(texte, voix=None, debit=None, client=None):
        return b"OggS-audio", "audio/ogg"

    monkeypatch.setattr(tts_engine, "synthetiser", _synth)
    reponse = await routeur.speak(routeur.TTSRequest(text="**Bonjour** Franck."), _user=SimpleNamespace(id="u"))
    assert reponse.media_type == "audio/ogg"
