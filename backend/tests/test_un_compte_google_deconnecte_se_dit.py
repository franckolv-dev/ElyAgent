# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_un_compte_google_deconnecte_se_dit.py
# @brief      Un jeton Google révoqué arrête la tâche planifiée et le DIT,
#             au lieu de la laisser tâtonner jusqu'au plafond de récursion.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""« Traitement factures » (17/09/2026) : Google répond ``invalid_grant: Token
has been expired or revoked`` dès la première action. ``get_user_credentials``
journalisait « returning stale creds, API call will likely 401 » et laissait
continuer ; le conseil de reprise disait « change de méthode : find_tool,
navigateur » ; Ely a donc ouvert Gmail dans le navigateur et tâtonné cinq
minutes, jusqu'à « Recursion limit of 60 reached ». Franck a supprimé puis
recréé la tâche : le message ne disait rien de la vraie cause.

Run with:  cd backend && python -m pytest tests/test_un_compte_google_deconnecte_se_dit.py -v
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class _Creds:
    """Des identifiants expirés dont le rafraîchissement échoue comme on veut."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.expired = True
        self.refresh_token = "1//jeton"
        self.expiry = datetime.utcnow() - timedelta(hours=1)

    def refresh(self, _request):
        raise self._exc


# ── 1. Le jeton révoqué n'est plus rendu comme s'il pouvait servir ───────────


@pytest.mark.asyncio
async def test_un_jeton_revoque_rend_non_connecte():
    from google.auth.exceptions import RefreshError

    from app.services.google_auth import get_user_credentials

    exc = RefreshError(
        "invalid_grant: Token has been expired or revoked.",
        {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
    )
    with patch("app.services.google_auth.build_credentials", AsyncMock(return_value=_Creds(exc))):
        creds = await get_user_credentials(json.dumps({"token": "t"}))

    assert creds is None, "un jeton révoqué doit se lire « non connecté », pas partir en 401"


@pytest.mark.asyncio
async def test_une_panne_reseau_au_rafraichissement_garde_les_identifiants():
    """Le comportement d'avant reste pour tout ce qui n'est PAS une révocation :
    une coupure réseau ne doit pas faire passer le compte pour déconnecté."""
    from google.auth.exceptions import TransportError

    from app.services.google_auth import get_user_credentials

    fautif = _Creds(TransportError("Connection reset by peer"))
    with patch("app.services.google_auth.build_credentials", AsyncMock(return_value=fautif)):
        creds = await get_user_credentials(json.dumps({"token": "t"}))

    assert creds is fautif


# ── 2. « Google non connecté » est un ÉCHEC, et la reprise ne contourne pas ──


@pytest.mark.parametrize("retour", [
    "Google non connecté.",
    "Google non connecté. Connectez votre compte Google dans les paramètres.",
    "Google non connecté. Connecte ton compte Google dans les paramètres.",
    "Google non connecté. Demandez à l'utilisateur de connecter son compte Google dans les paramètres.",
    "Google non connecté (Drive).",
    "Google Drive non connecté.",
])
def test_google_non_connecte_est_un_echec(retour):
    from app.agent.recovery import dit_compte_google_deconnecte
    from app.agent.tool_failure import dit_un_echec

    assert dit_un_echec(retour), "sinon la passerelle compte ce retour comme un succès"
    assert dit_compte_google_deconnecte(retour)


def test_la_reprise_ne_propose_pas_de_contourner_un_compte_deconnecte():
    from app.agent.recovery import recovery_hint

    conseil = recovery_hint("gmail_list_emails", "Google non connecté.")

    assert "Compte Google déconnecté" in conseil
    for interdit in ("navigateur", "python_execute", "change de méthode"):
        assert interdit not in conseil, f"le conseil pousse encore à contourner ({interdit})"


# ── 3. Une tâche automatisée s'arrête, un tour de chat continue ──────────────


def _tour(retour_outil: str, *, avant: list | None = None) -> list:
    return [
        *(avant or []),
        HumanMessage(content="Trouve les dernières factures reçues par mail"),
        AIMessage(content="", tool_calls=[{"name": "gmail_list_emails", "args": {}, "id": "c1"}]),
        ToolMessage(content=retour_outil, tool_call_id="c1"),
    ]


def test_une_tache_automatisee_s_arrete_sur_un_compte_deconnecte():
    from app.agent.graph import route_after_tools

    etat = {"messages": _tour("Google non connecté."), "automated_task": True}
    assert route_after_tools(etat) == "compte_deconnecte"


def test_un_tour_de_chat_n_est_pas_coupe():
    """En chat, quelqu'un lit la réponse : le modèle dit le problème et peut
    encore traiter le reste de la demande. Seul le conseil de reprise change."""
    from app.agent.graph import route_after_tools

    etat = {"messages": _tour("Google non connecté."), "automated_task": False}
    assert route_after_tools(etat) == "agent"


def test_un_retour_normal_ne_coupe_rien():
    from app.agent.graph import route_after_tools

    etat = {"messages": _tour("3 mails non lus"), "automated_task": True}
    assert route_after_tools(etat) == "agent"


def test_une_deconnexion_d_un_tour_precedent_ne_coupe_pas_celui_ci():
    from app.agent.graph import route_after_tools

    ancien = _tour("Google non connecté.")
    etat = {"messages": _tour("3 mails non lus", avant=ancien), "automated_task": True}
    assert route_after_tools(etat) == "agent"


@pytest.mark.asyncio
async def test_l_arret_leve_un_message_que_franck_comprend():
    """Le planificateur écrit ``Erreur: {exc}`` sur la tâche : c'est ce texte
    que la page affiche. Il doit commencer par les mots attendus."""
    from app.agent.graph import CompteGoogleDeconnecte, compte_deconnecte_node

    with pytest.raises(CompteGoogleDeconnecte) as info:
        await compte_deconnecte_node({"messages": _tour("Google non connecté.")})

    message = str(info.value)
    assert message.startswith("Compte Google déconnecté")
    assert "Réglages" in message


def test_le_noeud_est_cable_derriere_les_outils():
    from app.agent.graph import build_simple_agent_graph

    g = build_simple_agent_graph().get_graph()
    assert "compte_deconnecte" in set(g.nodes)
    aretes = {(e.source, e.target) for e in g.edges}
    assert ("tools", "compte_deconnecte") in aretes
    assert ("tools", "agent") in aretes


# ── 4. De bout en bout, sur le VRAI graphe compilé ───────────────────────────


@pytest.mark.asyncio
async def test_le_vrai_graphe_s_arrete_apres_un_seul_appel_au_modele(monkeypatch):
    """Le routeur et le nœud sont testés à part ; ici on vérifie qu'ils sont
    réellement sur le chemin. Le modèle factice redemanderait un outil à
    l'infini : sans l'arrêt, ce test finirait en « Recursion limit »."""
    import app.agent.graph as graphe

    appels = {"modele": 0, "outils": 0}

    def _faux_agent():
        async def _agent(_state):
            appels["modele"] += 1
            return {"messages": [AIMessage(content="", tool_calls=[
                {"name": "gmail_list_emails", "args": {}, "id": f"c{appels['modele']}"},
            ])]}
        return _agent

    async def _faux_outils(state):
        appels["outils"] += 1
        dernier = state["messages"][-1]
        return {"messages": [
            ToolMessage(content="Google non connecté.", tool_call_id=tc["id"])
            for tc in dernier.tool_calls
        ]}

    monkeypatch.setattr(graphe, "create_agent_node", _faux_agent)
    monkeypatch.setattr(graphe, "tool_node", _faux_outils)
    monkeypatch.setattr(graphe, "should_continue", lambda _s: "tools")

    with pytest.raises(graphe.CompteGoogleDeconnecte) as info:
        await graphe.build_simple_agent_graph().ainvoke(
            {"messages": [HumanMessage(content="Traite mes factures")], "automated_task": True},
            config={"recursion_limit": 60},
        )

    assert str(info.value).startswith("Compte Google déconnecté")
    assert appels == {"modele": 1, "outils": 1}
