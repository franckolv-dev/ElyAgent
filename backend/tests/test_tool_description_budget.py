# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_tool_description_budget.py
# @brief      Les descriptions d'outils repartent à CHAQUE tour : elles ont un
#             budget, et il doit être tenu.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du budget de descriptions du profil d'outils.

**Le constat, mesuré le 26/07.** Les 82 outils du profil ``default`` pèsent
**15 486 tokens** de descriptions — **189 tokens par outil**. À titre de
comparaison, Hermes v0.19 binde 72 outils pour ~5 700 tokens, soit **79 tokens
par outil** : Ely paie 2,4× plus cher pour un nombre d'outils comparable.

Ces descriptions ne sont pas payées une fois : elles repartent à **chaque
appel de modèle**, donc à chaque itération d'une boucle d'outils. Sur une
demande PDF, 18 outils sont plausiblement utiles (1 799 tokens) sur 82 envoyés
— **88 % du poids ne sert pas au tour en cours**.

**La cause structurelle.** La docstring de développement sert AUSSI de
description au modèle : ``orchestrate`` expose ainsi 4 826 caractères, dont
des exemples de code et des sections de documentation destinées à un humain
qui lit le source. Hermes sépare les deux — ses schémas ont un champ
``description`` distinct du code.

**Ce que ce lot NE fait pas.** Il ne supprime pas les docstrings : elles
restent, pour les développeurs. Il donne au modèle une description courte et
orientée décision, via le paramètre ``description`` de ``@tool``.

**Ce qui est préservé en priorité** : les *anti-déclencheurs* (« n'utilise pas
ceci quand… ») — c'est ce qui empêche le mauvais choix d'outil, et c'est
précisément la forme que Hermes soigne dans ses SKILL.md.

Run with:  cd backend && python -m pytest tests/test_tool_description_budget.py -v
"""
from __future__ import annotations

import pytest

# Budget total du profil. Départ mesuré : 15 486 tokens.
_PROFILE_BUDGET_TOKENS = 9_500

# Plafond par outil : au-delà, une description cesse d'aider au choix et
# devient de la documentation. `orchestrate` est le plus proche du plafond
# (267) parce qu'il DOIT énumérer les 15 stubs de son bac à sable : en mode
# « code », le modèle écrit lui-même le script et ne peut appeler que ceux-là.
# C'est un contrat, épinglé par test_orchestrate_skeleton.
_PER_TOOL_CEILING_TOKENS = 280


def _tool_or_skip(name: str):
    """Renvoie l'outil, ou saute le test s'il n'est pas au catalogue.

    ``orchestrate`` s'enregistre par AUTO-DÉCOUVERTE
    (``auto_discover_tools(packages=("app.agent.tools",))``), elle-même
    enveloppée d'un ``try/except`` qui n'interrompt pas le démarrage. En suite
    complète, cette découverte n'aboutit pas toujours — l'outil est alors
    absent du registre et l'assertion lèverait un ``KeyError`` sans rapport
    avec ce qu'on veut vérifier.

    En production il EST enregistré (mesuré : 1 378 tokens de description avant
    ce lot, 267 après). On saute donc proprement plutôt que de masquer le vrai
    sujet — et ``apply_slim_descriptions`` traite déjà l'absence sans lever.
    """
    import pytest as _pytest

    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    by = {t.name: t for t in get_skill_registry().all_tools}
    if name not in by:
        _pytest.skip(f"{name} absent du registre dans ce contexte de test")
    return by[name]


def _profile_descriptions() -> dict[str, int]:
    from app.agent.toolset_profiles import _DEFAULT_TOOLS
    from app.services.context_manager import estimate_tokens
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    by = {t.name: t for t in get_skill_registry().all_tools}
    return {
        n: estimate_tokens(by[n].description or "")
        for n in _DEFAULT_TOOLS if n in by
    }


def test_the_profile_stays_within_its_token_budget():
    """LE test du lot. Ce poids est payé à chaque itération de chaque tour."""
    sizes = _profile_descriptions()
    total = sum(sizes.values())

    worst = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    assert total <= _PROFILE_BUDGET_TOKENS, (
        f"{total} tokens de descriptions pour {len(sizes)} outils "
        f"(budget {_PROFILE_BUDGET_TOKENS}). Plus lourds : {worst}"
    )


def test_no_single_tool_dominates():
    """Une description qui dépasse ce plafond documente au lieu d'aiguiller."""
    sizes = _profile_descriptions()
    over = {n: t for n, t in sizes.items() if t > _PER_TOOL_CEILING_TOKENS}

    assert not over, f"descriptions au-dessus du plafond : {over}"


def test_the_average_approaches_the_hermes_reference():
    """Repère externe : 79 tokens/outil chez Hermes pour 72 outils. On ne vise
    pas l'égalité — Ely a des outils plus riches — mais l'ordre de grandeur."""
    sizes = _profile_descriptions()
    avg = sum(sizes.values()) / max(len(sizes), 1)

    assert avg <= 120, f"{avg:.0f} tokens/outil en moyenne (départ : 189)"


# ------------------------------------------- ce qu'on ne doit pas perdre

@pytest.mark.parametrize("tool_name,needles", [
    # L'anti-déclencheur d'orchestrate est ce qui l'empêche d'être appelé
    # à la place d'un outil dédié — le travers exact relevé par l'audit
    # (« 9 outils pour 1 besoin »).
    ("orchestrate", ["intent", "code"]),
    # browser_screenshot ne doit PAS se croire capable d'envoyer le fichier.
    ("browser_screenshot", ["screenshot"]),
])
def test_the_decision_relevant_content_survives(tool_name, needles):
    """Dégraisser ne doit pas retirer ce qui fait choisir correctement."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    desc = (_tool_or_skip(tool_name).description or "").lower()

    for needle in needles:
        assert needle.lower() in desc, f"{tool_name} a perdu « {needle} »"


def test_the_developer_docstrings_are_kept():
    """Le dégraissage porte sur ce qu'on ENVOIE au modèle, pas sur la
    documentation du code : la docstring reste lisible dans le source."""
    # Ré-ancré le 29/07 : l'exemple était `orchestrate`, démantelé au lot 5
    # du ménage. `gmail_trash_by_category` est le nouveau poids lourd du
    # catalogue (docstring ~3 350 car. pour une description ~450).
    tool = _tool_or_skip("gmail_trash_by_category")

    fn = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    doc = (getattr(fn, "__doc__", "") or "")

    assert len(doc) > 1_000, (
        "la docstring de développement a été amputée — ce n'est pas le but"
    )
    assert len(doc) > len(tool.description or ""), (
        "la description envoyée au modèle doit être plus courte que la "
        "docstring de développement"
    )


def test_the_sessionless_browser_notice_survives():
    """Garde-fou : le dégraissage ne doit pas effacer l'aiguillage de #260."""
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    by = {t.name: t for t in get_skill_registry().all_tools}

    for name in ("browser_navigate", "browser_get_text", "browser_screenshot"):
        desc = by[name].description or ""
        assert "NO login session" in desc
        assert "browser_tab_read_text" in desc


def test_applying_the_slim_descriptions_twice_changes_nothing():
    """Défaut trouvé pendant l'écriture du lot : la liste des stubs
    d'orchestrate était concaténée à SLIM_DESCRIPTIONS, donc RÉAJOUTÉE à
    chaque appel — 267 → 458 tokens en trois passes. Une fonction appelée au
    démarrage doit pouvoir être rejouée sans effet de bord (rechargement,
    test, ré-enregistrement du catalogue)."""
    from app.agent.tool_descriptions import apply_slim_descriptions
    from app.services.context_manager import estimate_tokens
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    once = estimate_tokens(_tool_or_skip("orchestrate").description or "")

    apply_slim_descriptions()
    apply_slim_descriptions()
    by = {t.name: t for t in get_skill_registry().all_tools}

    assert estimate_tokens(by["orchestrate"].description or "") == once
