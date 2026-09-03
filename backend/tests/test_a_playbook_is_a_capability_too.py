# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_a_playbook_is_a_capability_too.py
# @brief      Une procédure apprise couvre un besoin sans coûter un schéma.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""La croissance des outils, et la seule réponse qui la borne (24/08).

    Franck : « On a prévu qu'Ely puisse créer ses propres outils […] mais si
      on envoie systématiquement tous les outils, au fur et à mesure, cela va
      devenir de plus en plus lourd. »

La crainte est fondée. Un outil coûte son schéma JSON à CHAQUE tour, pour
toujours — 200 outils pèsent 60 941 tokens. Un playbook coûte des caractères
de prompt, plafonnés, et seulement le jour où on le rend. C'est la différence
entre une croissance bornée et une croissance linéaire.

C'est la réponse d'Hermes, et **le portage était déjà fait ici** :
`app/models/learned_skill.py` dit en toutes lettres « auto-improved skills
(Hermes-style playbooks) » et « Markdown playbook (Hermes ``SKILL.md`` format
with YAML frontmatter) ». Deux formats coexistent — `markdown_playbook`
(document) et `python_tool` (outil lié).

Deux trous empêchaient ce modèle de fonctionner.

TROU 1 — `find_tool` NE VOYAIT PAS LES PROCÉDURES
---------------------------------------------------
Il ne balayait que le catalogue d'OUTILS. Une capacité couverte par un
playbook était donc déclarée « réellement absente », et la fabrique repartait
écrire ce qui existait déjà.

C'est aussi ce qui rendait le modèle inutile : écrire des procédures que rien
ne sait retrouver revient à ne pas les écrire.

TROU 2 — L'AIGUILLAGE AVAIT UNE BRANCHE MORTE
-----------------------------------------------
`auto_tool_generation` pose la bonne question depuis le 29/07 — règle de
Franck : « soit la demande peut être réglée par un modèle et dans ce cas ce
n'est pas un outil qu'il faut mais une skill ; soit elle nécessite une ou
plusieurs ACTIONS et là il faut un outil. » Le juge `needs_a_tool` tranche
correctement.

Mais quand il répondait « compétence », la fonction faisait `return None`.
**Elle ne créait rien.** La moitié « outil » de l'aiguillage était branchée ;
la moitié « compétence » ne menait nulle part. Chaque manque relevant d'une
procédure restait un manque.

⚠️ CE QUI N'EST PAS FAIT, ET POURQUOI
---------------------------------------
Les 200 outils intégrés ne migrent PAS vers des playbooks. La garde humaine
d'Ely est **par nom d'outil** — 46 outils sous `LOCKED_HITL_TOOLS ∪
ALWAYS_CRITICAL_TOOLS`, invariant 2, échec fermé. Un playbook qui dirait
« exécute ce code pour envoyer le mail » n'a aucun nom à garder : la table de
sécurité s'effondrerait. Hermes peut se le permettre, leur modèle de sûreté
n'est pas bâti là-dessus. Ici, c'est l'invariant fondateur.

Run with:  cd backend && python -m pytest tests/test_a_playbook_is_a_capability_too.py -v
"""
from __future__ import annotations

import inspect

import pytest


def _corps(outil):
    """Le code du corps d'un outil LangChain.

    ⚠️ `@tool` sur une fonction ASYNC laisse `.func` à None et met le
    callable dans `.coroutine`. Viser `.func` en dur faisait lever
    `TypeError` sur `inspect.getsource` — un pin qui rougit pour une raison
    qui n'a rien à voir avec ce qu'il garde.
    """
    return inspect.getsource(outil.coroutine or outil.func)


# ─────────────────────────────────────────────────────────────────────
# 1 — `find_tool` regarde aussi dans les procédures
# ─────────────────────────────────────────────────────────────────────

def test_find_tool_searches_playbooks_not_only_tools():
    """LE pin du trou 1. Une capacité couverte par une procédure n'est pas un
    manque."""
    from app.skills.builtin import find_tool_skill

    src = _corps(find_tool_skill.find_tool)
    assert "_playbooks_for_capability(" in src, (
        "`find_tool` ne consulte pas les procédures apprises — une capacité "
        "déjà écrite serait déclarée absente et refabriquée"
    )


def test_a_matching_playbook_prevents_the_gap_path():
    """⚠️ La conséquence la plus coûteuse du trou 1 : sans ce garde, la
    fabrique repartait écrire ce qui existait déjà."""
    from app.skills.builtin import find_tool_skill

    src = _corps(find_tool_skill.find_tool)
    assert "if not top and not playbooks:" in src, (
        "le chemin « capacité absente » se déclenche encore alors qu'une "
        "procédure couvre le besoin"
    )


def test_playbooks_are_searched_even_when_tools_matched():
    """Un playbook dit souvent COMMENT combiner des outils — ce qu'aucune
    description d'outil ne porte. Le chercher seulement en dernier recours
    priverait le modèle de la moitié utile de la réponse."""
    from app.skills.builtin import find_tool_skill

    src = _corps(find_tool_skill.find_tool)
    avant_garde = src.split("if not top and not playbooks:", 1)[0]
    assert "_playbooks_for_capability(" in avant_garde, (
        "les procédures ne sont cherchées qu'en repli"
    )


def test_the_answer_says_a_playbook_is_not_callable():
    """⚠️ Sans le dire, le modèle tente d'APPELER la procédure comme un outil —
    elle n'a ni schéma ni exécuteur, et l'appel échoue sans rien expliquer.

    ⚠️ Le fragment visé tient sur UNE ligne du littéral. Première version de ce
    pin : « PAS des outils appelables », coupé par le retour à la ligne du
    littéral Python en « …PAS des » + « outils appelables… ». Il rougissait
    alors que la phrase était bien là. Un contrôle textuel doit viser ce qui ne
    peut pas être recoupé par un formateur.
    """
    from app.skills.builtin import find_tool_skill

    src = _corps(find_tool_skill.find_tool)
    assert "outils appelables" in src, (
        "rien ne distingue une procédure d'un outil dans la réponse rendue"
    )


def test_a_long_playbook_announces_its_truncation():
    """Une troncature muette ferait suivre une procédure sur sa première
    moitié en croyant l'avoir lue entière."""
    from app.skills.builtin.find_tool_skill import (
        _PLAYBOOK_EXTRAIT_CHARS, _rendre_playbook,
    )

    rendu = _rendre_playbook("ma-proc", "desc", "A" * (_PLAYBOOK_EXTRAIT_CHARS + 500))
    assert "tronquée" in rendu and "skill_view" in rendu, (
        "la coupe est silencieuse, et rien ne dit comment lire la suite"
    )
    court = _rendre_playbook("ma-proc", "desc", "deux lignes\nsuffisent")
    assert "tronquée" not in court, "une procédure courte s'annonce coupée"


@pytest.mark.asyncio
async def test_no_user_means_no_playbook_lookup():
    """Les procédures sont personnelles. Sans utilisateur, on n'en sert
    aucune plutôt que celles d'un tiers."""
    from app.skills.builtin.find_tool_skill import _playbooks_for_capability

    assert await _playbooks_for_capability("n'importe quoi", "") == []


def test_serving_a_playbook_counts_as_using_it():
    """⚠️ LE PIÈGE QUE CE CHANTIER POUVAIT CRÉER.

    `skill_curator` fait passer `active → stale → archived` ce qui ne sert
    pas, sur la foi de `use_count`. Une procédure servie par `find_tool` à
    chaque tour, sans compteur, passerait pour inutilisée et finirait
    archivée : on aurait construit un chemin de découverte qui condamne ce
    qu'il découvre.
    """
    from app.skills.builtin import find_tool_skill

    src = inspect.getsource(find_tool_skill._marquer_playbooks_utilises)
    assert "use_count" in src and "last_used_at" in src, (
        "servir une procédure ne compte pas comme un usage — le curateur "
        "l'archivera alors qu'elle travaille"
    )
    appel = _corps(find_tool_skill.find_tool)
    assert "_marquer_playbooks_utilises(" in appel


# ─────────────────────────────────────────────────────────────────────
# 2 — La branche « compétence » de l'aiguillage crée enfin quelque chose
# ─────────────────────────────────────────────────────────────────────

def test_the_skill_branch_now_writes_a_playbook():
    """LE pin du trou 2. Le juge tranchait bien, et la branche `return None`
    ne créait rien : le manque restait un manque."""
    from app.services.learning import auto_tool_generation

    src = inspect.getsource(auto_tool_generation.maybe_generate_for_gap)
    branche = src.split("needs_a_tool(", 1)[1].split("logger.info(\n            \"auto_tool_gen: génération", 1)[0]
    assert "draft_playbook_for_gap(" in branche, (
        "la branche « compétence » ne crée toujours rien — l'aiguillage a "
        "une moitié morte"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,user_id", [(0, "u"), (12, ""), (0, "")])
async def test_drafting_refuses_incomplete_input_without_raising(case_id, user_id):
    """Un playbook non écrit ne doit jamais casser le tour qui l'a révélé."""
    from app.services.learning.skill_creator import draft_playbook_for_gap

    resultat = await draft_playbook_for_gap(case_id, user_id)
    assert resultat["status"] == "invalid_input"


def test_drafting_reuses_the_batch_writer():
    """⚠️ Pas un SECOND rédacteur qui dériverait du premier.

    `run_skill_creator_batch` regroupe par `pattern_hash` et tourne en lot ;
    ici on tient un cas unique et frais. Même rédacteur, même persistance,
    grappe de un — la seule différence est le moment.
    """
    from app.services.learning import skill_creator

    src = inspect.getsource(skill_creator.draft_playbook_for_gap)
    assert "_draft_skill_for_cluster([fc], user_id)" in src, (
        "un second chemin de rédaction a été écrit — il dérivera du premier"
    )
    assert "processed_at" in src, (
        "le cas n'est pas marqué traité : le lot nocturne réécrirait la même "
        "procédure"
    )


def test_an_already_processed_case_is_not_written_twice():
    """Le lot nocturne et ce chemin-ci visent la même table. Sans ce garde,
    une procédure serait écrite deux fois et le curateur devrait trier."""
    from app.services.learning import skill_creator

    src = inspect.getsource(skill_creator.draft_playbook_for_gap)
    assert "already_processed" in src


def test_the_message_no_longer_promises_a_tool():
    """⚠️ « la génération d'un outil candidat démarre » est devenu FAUX.

    Depuis que la branche « compétence » écrit un playbook, ce qui démarre est
    l'un OU l'autre — et c'est le juge qui tranche, après ce message.
    Promettre un outil ferait attendre au modèle une capacité appelable qui ne
    viendra pas.
    """
    from app.skills.builtin import find_tool_skill

    src = inspect.getsource(find_tool_skill._record_gap_and_trigger)
    assert "Une procédure ou un outil candidat" in src, (
        "le message promet encore un outil alors qu'une procédure peut arriver"
    )


# ─────────────────────────────────────────────────────────────────────
# 3 — Ce qu'on ne fait PAS, et qui doit le rester
# ─────────────────────────────────────────────────────────────────────

def test_the_guarded_core_tools_are_still_real_tools():
    """⚠️ PIN DE CONTRAT — il passe aussi avant ce chantier, et c'est le but :
    il empêche l'étape suivante d'être prise sans mesurer ce qu'elle coûte.

    Migrer les outils intégrés vers des playbooks dissoudrait la garde
    humaine : elle s'applique **par nom d'outil**. Un playbook qui dirait
    « exécute ce code pour envoyer le mail » n'a aucun nom à garder.
    """
    from app.services.hitl_preferences import LOCKED_HITL_TOOLS
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    noms = {t.name for t in get_skill_registry().all_tools}
    gardes_reels = LOCKED_HITL_TOOLS & noms
    assert len(gardes_reels) >= 20, (
        f"seuls {len(gardes_reels)} outils sous garde nominale existent encore "
        f"dans le registre. Si des outils gardés sont devenus des procédures, "
        f"la garde ne s'applique plus à eux — invariant 2 (échec fermé)."
    )
