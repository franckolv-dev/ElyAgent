# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_playbooks_are_loaded_not_listed.py
# @brief      Le contenu des playbooks est CHARGÉ dans le prompt, au lieu
#             d'être listé en espérant un `skill_view` qui n'arrive jamais.
# @license    MIT
# =============================================================================
"""Les playbooks étaient listés, jamais lus.

La mesure (28/07/2026)
----------------------
    26 playbooks markdown actifs   ->  0 usage
    skill_view                     ->  0 appel DEPUIS TOUJOURS
    skill_list                     ->  0 appel DEPUIS TOUJOURS
    find_tool                      -> 29 appels  (lui est appelé)

Le bloc ``<learned_skills>`` listait nom + description, puis demandait au
modèle d'appeler ``skill_view`` pour lire la procédure et la suivre. Le tool
EST bindé (``tool_sets.py``) — le modèle le voit et ne l'a jamais appelé. Le
catalogue coûtait donc ~354 tokens dans le préfixe de chaque conversation de
Franck pour un mécanisme à 0 % de réussite.

Le correctif
------------
On arrête de parier sur une décision du modèle qui n'arrive jamais : la
procédure est **chargée directement** dans le prompt. C'est ce que fait Hermes
— ``skill_preprocessing.py`` matérialise le contenu du SKILL.md ; il n'existe
pas d'étape « le modèle décide d'ouvrir ».

Ce que ça ne change pas : la sélection par pertinence existante (le re-rank sur
la question d'ouverture) et le gel du snapshot par conversation. Le contenu est
donc payé UNE fois par conversation, dans le préfixe cacheable.

Le budget est borné, et toute troncature est DITE — un catalogue tronqué en
silence se lit comme un catalogue complet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.learning.active_skills import (
    PLAYBOOK_CONTENT_BUDGET_CHARS,
    format_active_skills_block,
)


@dataclass
class _Skill:
    name: str
    description: str = "une procédure"
    content: str = "## Étapes\n1. faire ceci\n2. puis cela"
    content_format: str = "markdown_playbook"
    promoted_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime(2020, 1, 1, tzinfo=timezone.utc)
    )


def _playbook(name: str, content: str = "", desc: str = "une procédure") -> _Skill:
    return _Skill(name=name, description=desc, content=content or f"## {name}\n1. étape")


# ─────────────────────────────────────────────────────────────────────────
# Le contenu arrive au modèle
# ─────────────────────────────────────────────────────────────────────────


def test_the_procedure_itself_is_in_the_prompt():
    block = format_active_skills_block([
        _playbook("gmail-trash", "## Procédure\n1. appeler gmail_trash_message\n2. confirmer")
    ])
    assert "appeler gmail_trash_message" in block, (
        "la procédure doit être chargée, pas seulement annoncée"
    )


def test_the_model_is_no_longer_told_to_call_skill_view():
    """La consigne qui n'a jamais fonctionné une seule fois disparaît : la
    laisser inviterait le modèle à appeler un tool pour relire ce qu'il a
    déjà sous les yeux."""
    block = format_active_skills_block([_playbook("gmail-trash")])
    assert "skill_view" not in block


def test_an_empty_set_still_produces_nothing():
    """Un utilisateur sans playbook ne doit pas voir de bloc vide dans son
    prompt."""
    assert format_active_skills_block([]) == ""


def test_learned_tools_keep_their_own_instruction():
    """Un python_tool est DÉJÀ bindé : il s'appelle directement, et son code
    n'a rien à faire dans le prompt."""
    tool = _Skill(
        name="levenshtein_distance",
        content="def levenshtein(...): ...",
        content_format="python_tool",
    )
    block = format_active_skills_block([tool])
    assert "levenshtein_distance" in block
    assert "def levenshtein" not in block, "le code d'un outil bindé n'a rien à faire là"
    assert "DIRECTEMENT" in block


# ─────────────────────────────────────────────────────────────────────────
# Le budget est borné, et la troncature est DITE
# ─────────────────────────────────────────────────────────────────────────


def test_the_content_budget_is_enforced():
    gros = [_playbook(f"p{i}", "x" * 4000) for i in range(10)]
    block = format_active_skills_block(gros)
    assert len(block) < PLAYBOOK_CONTENT_BUDGET_CHARS * 2, (
        "le budget de contenu n'est pas tenu"
    )


def test_a_truncated_catalog_says_so():
    """Règle du projet : jamais de troncature silencieuse. Un catalogue amputé
    en silence se lit comme un catalogue complet."""
    gros = [_playbook(f"p{i}", "x" * 4000) for i in range(10)]
    block = format_active_skills_block(gros)
    assert "p0" in block, "les plus pertinents (déjà en tête) doivent passer"
    assert any(marqueur in block for marqueur in ("non détaillé", "non détaillés")), (
        "la troncature doit être annoncée au modèle"
    )


def test_playbooks_left_out_of_the_budget_are_still_named():
    """Un playbook trop volumineux pour être détaillé doit rester CONNU du
    modèle : il peut toujours demander à le consulter."""
    gros = [_playbook(f"p{i}", "x" * 4000) for i in range(10)]
    block = format_active_skills_block(gros)
    assert "p9" in block


def test_the_budget_leaves_room_for_a_real_catalog():
    """Mesuré chez Franck : 16 playbooks actifs, 15 462 caractères de contenu,
    le plus gros à 1 595 caractères. Le budget doit laisser passer plusieurs
    procédures entières, sinon il ne sert à rien."""
    assert PLAYBOOK_CONTENT_BUDGET_CHARS >= 4 * 1595
