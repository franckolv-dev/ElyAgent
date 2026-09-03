# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_llm_calls_are_accounted.py
# @brief      Un appel LLM facturé doit laisser une ligne. Ce pin cherche les
#             chemins qui dépensent sans compter, AVANT qu'ils n'arrivent.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Tout appel LLM d'une boucle de fond doit consigner sa consommation.

L'incident, 28/07 → 05/08/2026
-------------------------------
994 requêtes et 42 M tokens sur ``deepseek-v4-pro``, visibles sur la facture
du fournisseur et **introuvables côté Ely**. La question « à quoi c'est dû ? »
a demandé une demi-journée d'enquête, et trois audits successifs se sont
trompés — parce que le dépôt consigne l'usage sous **trois noms différents** :

    ``log_usage``  ``log_response_usage``  ``record_tier_s_usage``

Chercher l'un des trois donne une réponse fausse et rassurante. C'est
précisément ce que ce fichier empêche : il cherche les TROIS, et il part des
appels plutôt que des consignations.

Pourquoi un test STRUCTUREL et pas un test par module
------------------------------------------------------
Un test par module vérifie les chemins qu'on connaît. Celui-ci vérifie les
chemins qu'on ne connaît pas encore : un nouveau fichier qui appelle un LLM
sans consigner échoue ici le jour où il est écrit, pas neuf jours après sur
un relevé bancaire.

⚠️ Il lit du TEXTE, pas un graphe d'appels : il ne prouve pas que la
consignation couvre l'appel, seulement qu'elle existe dans le fichier. C'est
un filet, pas une preuve — et il attrape le seul mode de panne observé
jusqu'ici : l'oubli pur et simple.

Run with:  cd backend && python -m pytest tests/test_llm_calls_are_accounted.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parent.parent / "app"

# Les trois noms sous lesquels le dépôt écrit une ligne d'usage. En ajouter un
# quatrième sans l'inscrire ici rendrait ce pin faussement vert.
_CONSIGNATIONS = ("log_usage", "log_response_usage", "record_tier_s_usage")

# LE critère, et il est mécanique. La consommation d'un tour est comptée au
# niveau du TOUR par `usage_instrumentation.record_turn_usage`, qui lit l'arbre
# de callbacks LangChain. Un appel qui pose `config={"callbacks": []}` coupe
# cet arbre — nécessaire quand il tourne pendant un tour actif, sinon ses
# tokens s'affichent dans la réponse de l'utilisateur (bug du 19/07) — mais il
# sort DU MÊME COUP du comptage. Couper les callbacks et ne pas consigner soi-
# même, c'est dépenser hors bilan. C'est exactement ce qu'`escalation._ask`
# faisait.
_DETACHE = re.compile(r'callbacks"\s*:\s*\[\]')

# Chemins dispensés, avec leur RAISON. Une dispense sans raison écrite est une
# dette qu'on ne retrouve plus.
_DISPENSES: dict[str, str] = {
    # Couche transport : pose le `config` qu'on lui passe, n'invoque pas pour
    # son compte. Lui demander de consigner ferait compter chaque appel deux
    # fois, une fois ici et une fois chez l'appelant.
    "services/llm_deadline.py": "transport — l'appelant consigne",
    # Wrapper qui rend (texte, réponse brute) JUSTEMENT pour que l'appelant
    # consigne. Même raison.
    "services/background_llm.py": "wrapper — l'appelant consigne",
    # ⚠️ DETTE ASSUMÉE, pas un appel gratuit. `select_tools(user_query, tools,
    # *, include_core)` ne reçoit aucun `user_id` et le fil est appelé sur le
    # chemin chaud : le plomber touche toutes les surfaces. L'appel vise le
    # sélecteur local, mais « conçu pour être local » ne veut pas dire gratuit
    # — la chaîne descend sur un fournisseur facturé dès qu'il est absent.
    # À reprendre avec la signature, pas en douce.
    "agent/tool_selector.py": "DETTE — aucun user_id dans la signature",
}


def _fichiers_qui_appellent_un_llm() -> list[Path]:
    """Les modules dont un appel est détaché du comptage du tour."""
    out: list[Path] = []
    for zone in (_RACINE / "services", _RACINE / "agent"):
        for f in sorted(zone.rglob("*.py")):
            try:
                if _DETACHE.search(f.read_text(encoding="utf-8")):
                    out.append(f)
            except OSError:
                continue
    return out


def test_the_audit_actually_finds_something():
    """Un balayage qui ne trouve rien passerait toujours.

    Sans ce garde-fou, renommer `.ainvoke` en amont viderait la liste et ce
    fichier deviendrait un test qui ne teste rien — vert, et muet.
    """
    trouves = _fichiers_qui_appellent_un_llm()
    assert len(trouves) >= 5, (
        f"seulement {len(trouves)} module(s) appelant un LLM détecté(s) — le "
        f"motif de détection ne reconnaît plus les appels"
    )


@pytest.mark.parametrize("rel", [
    "services/learning/tool_or_skill.py",
    "services/learning/skill_from_success.py",
    "services/learning/user_state.py",
    "services/learning/diagnostician.py",
    "services/learning/mission_critic.py",
    "services/learning/patch_service.py",
    "agent/escalation.py",
])
def test_a_background_llm_call_records_its_usage(rel: str):
    """Chacun de ces modules dépense de l'argent réel sur une boucle de fond.

    `tool_or_skill` et `skill_from_success` étaient les deux derniers non
    consignés — branchés le 05/08. `escalation` l'a été le même jour : son
    `_ask` jetait `usage_metadata`, et sa coupure `config={"callbacks": []}`
    le détachait aussi de l'instrumentation du tour.
    """
    chemin = _RACINE / rel
    assert chemin.exists(), f"{rel} a bougé — mettre à jour ce pin"
    source = chemin.read_text(encoding="utf-8")
    assert _DETACHE.search(source), (
        f"{rel} ne coupe plus les callbacks — s'il est repassé sous le "
        f"comptage du tour, retirer cette entrée"
    )
    assert any(nom in source for nom in _CONSIGNATIONS), (
        f"{rel} appelle un modèle sans consigner sa consommation. C'est le "
        f"défaut du 28/07 : la facture le voit, Ely non. Utiliser l'un de "
        f"{_CONSIGNATIONS}."
    )


def test_no_new_unaccounted_llm_path_appears():
    """Le pin qui vaut pour les fichiers PAS ENCORE ÉCRITS.

    Les entrées ci-dessus couvrent ce qu'on connaît. Celui-ci balaie tout et
    échoue sur le prochain chemin qui dépensera sans compter — le jour où il
    est écrit, pas neuf jours plus tard sur un relevé.
    """
    muets: list[str] = []
    for f in _fichiers_qui_appellent_un_llm():
        rel = f.relative_to(_RACINE).as_posix()
        if rel in _DISPENSES:
            continue
        source = f.read_text(encoding="utf-8")
        if not any(nom in source for nom in _CONSIGNATIONS):
            muets.append(rel)

    assert muets == [], (
        "ces modules appellent un modèle sans consigner sa consommation :\n  "
        + "\n  ".join(muets)
        + f"\n\nUtiliser l'un de {_CONSIGNATIONS}, ou — si l'appel est "
        f"réellement gratuit et le restera — l'inscrire dans _DISPENSES AVEC "
        f"sa raison. Un modèle « conçu pour être local » ne suffit pas : la "
        f"chaîne descend sur un fournisseur facturé dès qu'il est indisponible."
    )
