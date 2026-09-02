# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_skill_from_verified_success.py
# @brief      Une compétence naît d'un SUCCÈS constaté — pas d'un manque supposé.
# @license    Elastic License 2.0
# =============================================================================
"""Le déclencheur qui manquait au funnel des compétences.

Le constat
----------
``skill_creator`` savait déjà rédiger un playbook et le poser en ``CANDIDATE``.
Ce qui lui manquait, c'est **quand** le faire : il était alimenté par des cas
d'échec clusterisés, un déclencheur qui ne partait quasiment jamais. Résultat
mesuré le 28/07/2026 : 66 compétences apprises pour 16 usages cumulés, et
``tier_s.tool_generator`` qui tournait 86 fois en 7 jours — 3× plus que les
demandes de Franck elles-mêmes.

Le déclencheur retenu
---------------------
**Un tour jugé CONFORME alors qu'il a fallu au moins une reprise.** C'est le
seul cas où il s'est passé quelque chose de transférable :

    1re approche  ->  ne répondait pas à la demande
    reprise       ->  a fonctionné
    => il y a une leçon, et on sait laquelle : l'écart qui a été comblé

Un tour conforme du premier coup n'apprend rien (c'était déjà su). Un tour
arrêté sur des écarts n'apprend rien de fiable (on ne sait pas ce qui aurait
marché). C'est le signal que produit désormais ``app.agent.conformity``.

C'est la forme d'Hermes : ``background_review.py`` rejoue le tour APRÈS coup et
demande « faut-il enregistrer une skill ? ». La compétence vient de ce qui a
marché, pas d'un manque anticipé.

Qui rédige
----------
**Le modèle principal — celui qui vient de réussir.** Un SKILL.md est une
consigne écrite POUR un modèle frontière ; le mieux placé pour l'écrire est
celui qui l'exécutera. Faire rédiger par un petit modèle local puis « optimiser »
remettrait le petit modèle en amont de la tâche la plus structurante —
l'inversion supprimée en #287.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.services.learning.skill_from_success import (
    build_success_skill_prompt,
    should_propose_skill_from_success,
)


# ─────────────────────────────────────────────────────────────────────────
# Le déclencheur
# ─────────────────────────────────────────────────────────────────────────


def test_a_success_that_needed_a_retry_is_worth_a_skill():
    assert should_propose_skill_from_success(conforme=True, retries=1) is True


def test_a_first_shot_success_teaches_nothing():
    """Le cas de loin le plus fréquent. En tirer une compétence remplirait le
    catalogue de procédures que le modèle appliquait déjà."""
    assert should_propose_skill_from_success(conforme=True, retries=0) is False


def test_a_turn_stopped_on_gaps_teaches_nothing_reliable():
    """On ne sait pas ce qui aurait marché — écrire une procédure depuis un
    échec, c'est graver une supposition."""
    assert should_propose_skill_from_success(conforme=False, retries=2) is False


def test_several_retries_still_qualify():
    assert should_propose_skill_from_success(conforme=True, retries=3) is True


# ─────────────────────────────────────────────────────────────────────────
# Ce qu'on demande au modèle
# ─────────────────────────────────────────────────────────────────────────


def _messages() -> list:
    return [
        HumanMessage(content="convertis ce pdf en docx en gardant les marges"),
        AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {}, "id": "1"}]),
        ToolMessage(content="Document créé, marges non conservées", tool_call_id="1"),
        AIMessage(content="Voilà."),
        HumanMessage(content="[Vérification — …]\n- les marges ne sont pas conservées"),
        AIMessage(content="", tool_calls=[{"name": "pdf_to_docx", "args": {"keep_geometry": True}, "id": "2"}]),
        ToolMessage(content="Document créé, marges conservées", tool_call_id="2"),
        AIMessage(content="Voilà, marges conservées."),
    ]


def test_the_prompt_carries_the_original_request():
    prompt = build_success_skill_prompt(_messages())
    assert "convertis ce pdf en docx" in prompt


def test_the_prompt_carries_what_had_to_be_corrected():
    """Sans l'écart, la procédure produite serait « fais le travail » — sans
    valeur. C'est la CORRECTION qui est la leçon."""
    prompt = build_success_skill_prompt(_messages())
    assert "marges ne sont pas conservées" in prompt


def test_the_prompt_carries_the_tools_that_finally_worked():
    prompt = build_success_skill_prompt(_messages())
    assert "pdf_to_docx" in prompt


def test_the_prompt_asks_for_the_skill_md_shape():
    """Frontmatter + procédure : le format que le parseur existant attend."""
    prompt = build_success_skill_prompt(_messages())
    assert "---" in prompt
    assert "name:" in prompt
    assert "description:" in prompt


def test_an_empty_conversation_yields_no_prompt():
    assert build_success_skill_prompt([]) == ""


# ─────────────────────────────────────────────────────────────────────────
# La proposition, de bout en bout
# ─────────────────────────────────────────────────────────────────────────


_PLAYBOOK = """---
name: pdf-vers-docx-garder-marges
description: Conserver la géométrie de page lors d'une conversion PDF vers Word.
---

## Quand l'appliquer
Une conversion PDF -> DOCX où l'utilisateur exige la mise en page.

## Ne pas appliquer quand
Le PDF est un scan sans couche texte : passer par l'OCR d'abord.

## Procédure
1. Appeler `pdf_to_docx` avec `keep_geometry=True`.
2. Vérifier le calibrage rapporté avant de répondre.

## Pièges
Sans `keep_geometry`, l'outil rend un document propre aux marges fausses et
ne le signale pas.

## Terminé quand
Le calibrage rapporté est à 0 caractère perdu.
"""


@pytest.fixture
def model(monkeypatch):
    def _install(reply: str):
        from app.services.learning import skill_from_success as sfs

        monkeypatch.setattr(
            "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
        )

        async def _fake(*_a, **_k):
            return AIMessage(content=reply)

        monkeypatch.setattr(sfs, "ainvoke_with_deadline", _fake)

    return _install


@pytest.mark.asyncio
async def test_a_candidate_skill_is_drafted_for_human_validation(model):
    from app.models.learned_skill import SkillStatus
    from app.services.learning.skill_from_success import draft_skill_from_success

    model(_PLAYBOOK)
    skill = await draft_skill_from_success("user-1", _messages())

    assert skill is not None
    assert skill.name == "pdf-vers-docx-garder-marges"
    assert "keep_geometry" in skill.content
    assert skill.status == SkillStatus.CANDIDATE, (
        "jamais activée d'office — elle passe par la validation humaine"
    )
    assert skill.user_id == "user-1"


@pytest.mark.asyncio
async def test_the_rationale_says_where_the_skill_comes_from(model):
    """L'humain qui valide doit savoir sur quoi elle se fonde."""
    from app.services.learning.skill_from_success import draft_skill_from_success

    model(_PLAYBOOK)
    skill = await draft_skill_from_success("user-1", _messages())
    assert "succès" in (skill.rationale or "").lower()


@pytest.mark.asyncio
async def test_an_unparseable_answer_drafts_nothing(model):
    """Échouer OUVERT : pas de compétence bancale enregistrée."""
    from app.services.learning.skill_from_success import draft_skill_from_success

    model("désolé je ne sais pas faire ça")
    assert await draft_skill_from_success("user-1", _messages()) is None


@pytest.mark.asyncio
async def test_a_failing_model_drafts_nothing(model, monkeypatch):
    from app.services.learning import skill_from_success as sfs
    from app.services.learning.skill_from_success import draft_skill_from_success

    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("modèle indisponible")

    monkeypatch.setattr(sfs, "ainvoke_with_deadline", _boom)
    assert await draft_skill_from_success("user-1", _messages()) is None


@pytest.mark.asyncio
async def test_the_draft_never_leaks_into_the_user_stream(monkeypatch):
    """Cette rédaction tourne APRÈS le tour, en tâche de fond. Comme tout appel
    concurrent d'un tour actif, elle doit couper les callbacks — sinon ses
    tokens s'affichent dans la réponse de l'utilisateur (bug du 19/07).
    """
    from app.services.learning import skill_from_success as sfs
    from app.services.learning.skill_from_success import draft_skill_from_success

    vu: dict = {}
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _capture(_llm, _msgs, **kwargs):
        vu.update(kwargs)
        return AIMessage(content=_PLAYBOOK)

    monkeypatch.setattr(sfs, "ainvoke_with_deadline", _capture)
    await draft_skill_from_success("user-1", _messages())

    assert vu.get("config", {}).get("callbacks") == []


# ─────────────────────────────────────────────────────────────────────────
# Le câblage : c'est la conformité qui déclenche
# ─────────────────────────────────────────────────────────────────────────


def _conforming_turn(retries: int) -> dict:
    return {
        "messages": _messages(),
        "user_id": "user-1",
        "conformity_retries": retries,
        "conformity_gap_count": 0,
    }


@pytest.mark.asyncio
async def test_a_conforming_turn_after_a_retry_proposes_a_skill(monkeypatch):
    from app.agent import conformity as conf

    lance: dict = {}
    monkeypatch.setattr(
        "app.services.llm_provider.get_llm_for_tier", lambda *_a, **_k: object()
    )

    async def _verdict(*_a, **_k):
        return AIMessage(content="CONFORME")

    monkeypatch.setattr(conf, "ainvoke_with_deadline", _verdict)
    monkeypatch.setattr(
        conf, "_maybe_learn_from_success",
        lambda uid, msgs, *, retries: lance.update(uid=uid, retries=retries) or True,
    )

    await conf.conformity_node(_conforming_turn(retries=2))
    assert lance == {"uid": "user-1", "retries": 2}


@pytest.mark.asyncio
async def test_the_draft_is_scheduled_in_the_background_not_awaited(monkeypatch):
    """La réponse de l'utilisateur ne doit jamais attendre cette rédaction —
    c'est la leçon de #286, où l'introspection tournait dans la boucle du tour.
    """
    from app.agent import conformity as conf

    planifie: dict = {}
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: (coro.close(), planifie.update(kw))[0],
    )
    assert conf._maybe_learn_from_success("user-1", _messages(), retries=1) is True
    assert planifie.get("label") == "skill_from_success"


@pytest.mark.asyncio
async def test_a_first_shot_success_schedules_nothing(monkeypatch):
    from app.agent import conformity as conf

    appele = {"n": 0}
    monkeypatch.setattr(
        "app.services.background_tasks.spawn",
        lambda coro, **kw: (coro.close(), appele.update(n=appele["n"] + 1))[0],
    )
    assert conf._maybe_learn_from_success("user-1", _messages(), retries=0) is False
    assert appele["n"] == 0
