# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_mission_ne_s_autodiagnostique_pas.py
# @brief      Une mission n'a pas les outils de diagnostic d'Ely sous la
#             main, et les sondes LM Studio ne doublent plus « /v1 ».
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Mission « nettoyage mails » (65b3a146), 03/09/2026, huit passages :

    **Passage 6** — system_check_llm_providers ✓, system_get_logs ✓ ×3.
    Bilan : … LM Studio indique 0 modèle disponible …
    **Passage 7** — (identique)   **Passage 8** — (identique)

Pas un mail touché. L'enchaînement : `system_check_llm_providers` interroge
``{lm_studio_base_url}/v1/models`` alors que l'URL configurée finit déjà
par ``/v1`` — LM Studio répond 200 à ``/v1/v1/models`` avec une liste vide
(« Unexpected endpoint … Returning 200 anyway ») — l'outil annonce « 0
modèle », le modèle en conclut que les têtes locales sont mortes, fouille
les journaux (``fallback``, ``tier``, ``lm_studio``), l'écrit dans son
carnet, et le passage suivant relit ce carnet et recommence.

Deux fermetures : l'URL, et le profil. Les outils qui inspectent Ely
elle-même (journaux, santé, configuration des modèles, listes de tâches et
de missions) n'ont rien à faire dans une mission — elle exécute un objectif
du monde, elle ne s'ausculte pas.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Outil:
    def __init__(self, name: str) -> None:
        self.name = name


_DIAG = (
    "system_get_logs", "system_check_llm_providers", "system_get_health",
    "system_check_channels", "system_list_missions", "system_list_scheduled_tasks",
    "system_info",
)


# ── Le profil « mission » ────────────────────────────────────────────────────

def test_le_profil_mission_ecarte_les_outils_de_diagnostic():
    from app.agent.toolset_profiles import resolve_profile_tools

    catalogue = [_Outil(n) for n in _DIAG] + [
        _Outil("gmail_list_emails"), _Outil("gmail_trash_emails"), _Outil("web_search"),
        _Outil("session_todo"), _Outil("find_tool"),
    ]
    noms = {t.name for t in resolve_profile_tools("mission", catalogue)}

    assert not (noms & set(_DIAG)), noms & set(_DIAG)
    assert {"gmail_list_emails", "gmail_trash_emails", "web_search", "session_todo", "find_tool"} <= noms


def test_le_profil_default_garde_les_outils_de_diagnostic():
    """Au chat, l'utilisateur a le droit de demander « montre-moi les journaux »."""
    from app.agent.toolset_profiles import resolve_profile_tools

    catalogue = [_Outil(n) for n in _DIAG] + [_Outil("web_search")]
    noms = {t.name for t in resolve_profile_tools("default", catalogue)}
    assert set(_DIAG) <= noms


def test_la_boucle_des_missions_utilise_le_profil_mission():
    from app.agent.missions import chat_loop
    from app.agent.toolset_profiles import _PROFILES

    assert chat_loop._PROFIL_OUTILS == "mission"
    assert "mission" in _PROFILES


# ── Les sondes LM Studio n'interrogent plus /v1/v1/models ────────────────────

class _FauxClient:
    urls: list[str] = []

    def __init__(self, *a, **k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url: str):
        _FauxClient.urls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "google/gemma-4-26b-a4b"}]})


@pytest.mark.asyncio
async def test_l_outil_de_diagnostic_n_ajoute_pas_un_second_v1(monkeypatch):
    import httpx

    from app.config import get_settings
    from app.agent.tools import system_diag_tool as diag

    monkeypatch.setattr(get_settings(), "lm_studio_base_url", "http://host.docker.internal:1234/v1", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", _FauxClient)
    _FauxClient.urls.clear()

    rendu = await diag.system_check_llm_providers.ainvoke({})

    assert _FauxClient.urls, "la sonde LM Studio n'a pas été appelée"
    assert all("/v1/v1" not in u for u in _FauxClient.urls), _FauxClient.urls
    assert "gemma-4-26b-a4b" in rendu
    assert "0 modèle" not in rendu


def test_la_sonde_des_modeles_locaux_n_ajoute_pas_un_second_v1(monkeypatch):
    import httpx

    from app.services import llm_provider as lp

    vus: list[str] = []

    def _get(url, timeout=None):
        vus.append(url)
        if url.endswith("/api/tags"):
            return SimpleNamespace(status_code=404, json=lambda: {})
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "mistralai/ministral-3-3b"}]})

    monkeypatch.setattr(httpx, "get", _get)
    lp._local_models_cache.clear()

    noms = lp.local_models_available("http://host.docker.internal:1234/v1")

    assert "mistralai/ministral-3-3b" in noms
    assert all("/v1/v1" not in u for u in vus), vus
