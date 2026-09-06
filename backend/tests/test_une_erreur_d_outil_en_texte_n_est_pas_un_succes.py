# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_une_erreur_d_outil_en_texte_n_est_pas_un_succes.py
# @brief      Audit GPT-6 F02 (06/09/2026) : un outil qui annonce son échec
#             en TEXTE n'est plus compté comme un succès par la passerelle.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Les outils d'Ely signalent leur échec par une chaîne (« Erreur : … »),
sans lever. La passerelle ne connaissait que l'exception : le texte d'erreur
prenait le chemin nominal — ``success=True`` dans les traces, journal de
mission ✓, résultat MÉMORISÉ pour l'idempotence. En prod, un
``browser_navigate`` en ``ERR_NAME_NOT_RESOLVED`` figurait comme réussi.

La règle est celle que la garde anti-rejeu et le journal réversible lisent
déjà (``replay_guard._ECHEC_PREFIXES``) : une seule définition de l'échec.

Run with:  cd backend && python -m pytest tests/test_une_erreur_d_outil_en_texte_n_est_pas_un_succes.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def _db():
    await init_db()


class _OutilQuiEchoueEnTexte:
    name = "sheets_append_row"

    async def ainvoke(self, args):
        return "Erreur : écriture impossible, document absent"


class _OutilQuiReussit:
    name = "sheets_append_row"

    async def ainvoke(self, args):
        return "Ligne ajoutée (A12)."


def _ctx(journal: list):
    from app.services.conversation_filters import get_filter
    from app.services.security_filter import SecurityFilter
    from app.services.tool_gateway import GatewayContext

    conv = f"conv-f02-{uuid.uuid4()}"

    def _post(tool_name, ok, _elapsed, _res):
        journal.append((tool_name, ok))

    return GatewayContext(
        user_id="u-f02", conversation_id=conv,
        pii_filter=get_filter(conv), criticality_filter=SecurityFilter(),
        hitl=None, memory=None, post_execute=_post,
    )


@pytest.mark.asyncio
async def test_une_erreur_en_texte_est_un_echec_pour_la_passerelle(monkeypatch):
    import app.services.idempotency_store as idem
    from app.services.tool_gateway import execute_tool_call

    memorises: list = []

    async def _remember(*a, **k):
        memorises.append(a)

    monkeypatch.setattr(idem, "remember", _remember)

    journal: list = []
    meta: dict = {}
    outil = _OutilQuiEchoueEnTexte()
    msg = await execute_tool_call(
        _ctx(journal), {"name": outil.name, "args": {"row": ["a"]}, "id": "t-f02"},
        {outil.name: outil}, meta=meta,
    )

    assert meta.get("success") is False, "un texte d'erreur passait pour un succès"
    assert journal == [(outil.name, False)], "le journal de bord doit voir l'échec"
    assert memorises == [], "un échec ne doit pas être mémorisé comme résultat réussi"
    contenu = msg["content"] if isinstance(msg, dict) else msg.content
    assert "écriture impossible" in contenu, "le modèle doit lire l'erreur telle quelle"


@pytest.mark.asyncio
async def test_un_resultat_ordinaire_reste_un_succes():
    from app.services.tool_gateway import execute_tool_call

    journal: list = []
    meta: dict = {}
    outil = _OutilQuiReussit()
    await execute_tool_call(
        _ctx(journal), {"name": outil.name, "args": {"row": ["a"]}, "id": "t-f02b"},
        {outil.name: outil}, meta=meta,
    )

    assert meta.get("success") is True
    assert journal == [(outil.name, True)]


def test_la_regle_de_l_echec_est_celle_de_la_garde_anti_rejeu():
    """Une seule définition : la passerelle, la garde et le journal lisent la
    même liste de préfixes."""
    from app.agent.replay_guard import _ECHEC_PREFIXES
    from app.agent.tool_failure import ECHEC_PREFIXES, dit_un_echec

    assert _ECHEC_PREFIXES is ECHEC_PREFIXES
    assert dit_un_echec("  Erreur lors de la navigation vers https://x : net::ERR")
    assert dit_un_echec("ÉCHEC : rien trouvé")
    assert not dit_un_echec("Résultat : 3 lignes. Aucune erreur.")
    assert not dit_un_echec("")
