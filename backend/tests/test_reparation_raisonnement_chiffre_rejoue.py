# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_reparation_raisonnement_chiffre_rejoue.py
# @brief      Un raisonnement chiffré que le fournisseur ne sait plus lire
#             se retire du fil ; il ne fait pas basculer la conversation
#             sur un modèle de secours.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Réparation post-audit (03/09/2026).

Production, 03/09 à 06:16:52, conversation ``f49faf36`` :

    [fallback] primary LLM failed (BadRequestError/bad_request): Error code: 400
    'The encrypted content for item rs_09cf… could not be verified.'
    [fallback] switched 'gpt-5.6-sol' → 'minimax/minimax-m3:free' (chain_pos=2/4)

Le tier codex rejoue le raisonnement chiffré de chaque tour (``store=false``
+ ``include=["reasoning.encrypted_content"]``, cf. ``_make_openai_codex``).
Quand le serveur refuse UN de ces items, le gestionnaire de repli traite le
400 comme une panne du fournisseur et bascule TOUTE la conversation sur le
maillon suivant de la chaîne — un modèle gratuit. Les vingt tours qui ont
suivi ont tourné dessus : le nettoyage Gmail a bouclé, la conformité a
relancé deux fois, l'utilisateur a fermé la session.

Or l'erreur ne dit rien du fournisseur : elle dit qu'un bloc de raisonnement
du FIL n'est plus lisible. Le geste juste est de retirer ces blocs et de
rappeler le MÊME modèle ; le repli n'a de sens que si ce second appel
échoue aussi.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class _Refus400(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.status_code = 400
        code = "invalid_encrypted_content" if "encrypted" in message else "rate_limit_exceeded"
        self.body = {"error": {"code": code, "message": message}}


_MESSAGE = (
    "Error code: 400 - {'error': {'message': 'The encrypted content for item "
    "rs_09cf could not be verified. Reason: Encrypted content could not be "
    "decrypted or parsed.', 'type': 'invalid_request_error', 'param': None, "
    "'code': 'invalid_encrypted_content'}}"
)


def _fil() -> list:
    return [
        {"role": "system", "content": "Tu es Ely."},
        HumanMessage(content="Trie mes mails"),
        AIMessage(
            content=[
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAAA…",
                 "summary": []},
                {"type": "text", "text": "Je liste d'abord.", "id": "msg_1"},
            ],
            tool_calls=[{"name": "gmail_list_emails", "args": {}, "id": "c1"}],
            additional_kwargs={"reasoning": {"id": "rs_1", "encrypted_content": "gAAAA…"}},
        ),
        ToolMessage(content="3 mails", tool_call_id="c1"),
        AIMessage(content="Voici.", additional_kwargs={"refusal": None}),
    ]


# ── Reconnaître l'erreur ─────────────────────────────────────────────────────

def test_l_erreur_du_serveur_est_reconnue():
    from app.agent.helpers.reasoning_replay import est_un_raisonnement_illisible

    assert est_un_raisonnement_illisible(_Refus400(_MESSAGE)) is True
    assert est_un_raisonnement_illisible(RuntimeError("h1_fallback")) is False
    assert est_un_raisonnement_illisible(_Refus400("Rate limit exceeded")) is False


# ── Retirer le raisonnement, et rien d'autre ─────────────────────────────────

def test_le_fil_sans_raisonnement_garde_le_texte_et_les_appels():
    from app.agent.helpers.reasoning_replay import sans_raisonnement_chiffre

    avant = _fil()
    apres = sans_raisonnement_chiffre(avant)

    assert apres[0] == avant[0]                          # le système est intact
    assert apres[1] is avant[1]                          # l'humain aussi
    ai = apres[2]
    assert isinstance(ai, AIMessage)
    assert ai.content == [{"type": "text", "text": "Je liste d'abord.", "id": "msg_1"}]
    assert ai.tool_calls == avant[2].tool_calls
    assert "reasoning" not in ai.additional_kwargs
    assert apres[3] is avant[3]
    assert apres[4].content == "Voici."
    assert apres[4].additional_kwargs == {"refusal": None}


def test_le_fil_d_origine_n_est_pas_modifie():
    from app.agent.helpers.reasoning_replay import sans_raisonnement_chiffre

    avant = _fil()
    sans_raisonnement_chiffre(avant)

    assert any(b.get("type") == "reasoning" for b in avant[2].content)
    assert "reasoning" in avant[2].additional_kwargs


# ── Rappeler le MÊME modèle avant tout repli ─────────────────────────────────

@pytest.mark.asyncio
async def test_un_raisonnement_illisible_rappelle_le_meme_modele_sans_lui():
    from app.agent.helpers.reasoning_replay import ainvoke_en_tolerant_le_raisonnement

    appels: list[list] = []

    async def _invoke(messages):
        appels.append(messages)
        if len(appels) == 1:
            raise _Refus400(_MESSAGE)
        return AIMessage(content="reprise")

    reponse = await ainvoke_en_tolerant_le_raisonnement(_invoke, _fil())

    assert reponse.content == "reprise"
    assert len(appels) == 2
    assert any(b.get("type") == "reasoning" for b in appels[0][2].content)
    assert not any(b.get("type") == "reasoning" for b in appels[1][2].content)


@pytest.mark.asyncio
async def test_une_autre_erreur_part_telle_quelle_vers_le_repli():
    from app.agent.helpers.reasoning_replay import ainvoke_en_tolerant_le_raisonnement

    appels = 0

    async def _invoke(messages):
        nonlocal appels
        appels += 1
        raise _Refus400("Rate limit exceeded")

    with pytest.raises(_Refus400):
        await ainvoke_en_tolerant_le_raisonnement(_invoke, _fil())
    assert appels == 1


@pytest.mark.asyncio
async def test_si_le_second_appel_echoue_aussi_l_erreur_remonte():
    from app.agent.helpers.reasoning_replay import ainvoke_en_tolerant_le_raisonnement

    async def _invoke(messages):
        raise _Refus400(_MESSAGE)

    with pytest.raises(_Refus400):
        await ainvoke_en_tolerant_le_raisonnement(_invoke, _fil())


@pytest.mark.asyncio
async def test_un_fil_sans_raisonnement_ne_rappelle_pas():
    """Rien à retirer → rappeler serait rejouer la même requête."""
    from app.agent.helpers.reasoning_replay import ainvoke_en_tolerant_le_raisonnement

    appels = 0

    async def _invoke(messages):
        nonlocal appels
        appels += 1
        raise _Refus400(_MESSAGE)

    with pytest.raises(_Refus400):
        await ainvoke_en_tolerant_le_raisonnement(
            _invoke, [HumanMessage(content="salut"), AIMessage(content="bonjour")],
        )
    assert appels == 1


# ── Le branchement dans le nœud agent ────────────────────────────────────────
#
# Le nœud est une fermeture de 1 400 lignes qu'aucun test n'exerce de bout en
# bout ; comme ``test_slm_path_binds_every_local_it_reads``, on épingle sa
# SOURCE : l'appel principal du modèle (``surface="general"``) doit passer par
# la tolérance, et aucun appel nu ne doit subsister sur ce chemin. Relecture
# du 03/09/2026 : ``nodes.py`` remis à HEAD, les tests du helper restaient
# verts — le branchement n'était pas couvert.

def test_le_noeud_agent_appelle_le_modele_a_travers_la_tolerance():
    import inspect

    from app.agent import nodes

    source = inspect.getsource(nodes.create_agent_node)
    appel_principal = 'surface="general")'
    assert source.count(appel_principal) == 1, "l'appel principal doit être unique"
    debut = source.index("ainvoke_en_tolerant_le_raisonnement(")
    assert debut < source.index(appel_principal), (
        "l'appel principal doit être enveloppé par ainvoke_en_tolerant_le_raisonnement"
    )
    assert "await ainvoke_with_deadline(\n                    _llm_with_tools_req, _invoke_msgs" not in source
    # Le repli vers un autre fournisseur ne rejoue pas non plus le raisonnement.
    assert "_fallback_msgs = sans_raisonnement_chiffre(_fallback_msgs)" in source
