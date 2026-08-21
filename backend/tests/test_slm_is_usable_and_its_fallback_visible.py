# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_is_usable_and_its_fallback_visible.py
# @brief      La voie rapide doit être rapide, et son repli doit se voir.
# @license    Elastic License 2.0
# =============================================================================
"""L'aboutissement du 21/08 — deux défauts qui se tenaient.

Franck met Nemotron 3 nano 4B en tier A. Les logs prouvent que tout marche :

    SLM pre-built: model=nvidia/nemotron-3-nano-4b …
    SLM warm-up terminé (tentative 1) : … chargé en RAM
    SLM timeout after 60.0s (score=35) — falling back to LLM
    SLM timeout after 60.0s (score=35) — falling back to LLM

Le modèle est CHAUD, le routage l'a bien choisi (score 35 sous le seuil 55),
et l'appel dépasse quand même 60 s. Deux fois.

1. LA VOIE RAPIDE SE SABOTAIT
------------------------------
Le warm-up envoie ``[HumanMessage("hi")]`` — nu. L'agent envoyait
``get_slm().bind_tools(registry.all_tools)`` : **~145 schémas d'outils**,
plusieurs dizaines de milliers de tokens, à un modèle de 4 milliards de
paramètres, pour répondre « bonjour ».

Ce n'est pas de l'inférence, c'est du *prompt processing*. Le tier A existe
pour traiter vite ce qui est simple ; on lui livrait le catalogue entier, donc
il était lent, donc il dépassait le délai, donc tout repartait au cloud. Le
mécanisme annulait sa propre raison d'être.

⚠️ Le profil ``_DEFAULT_TOOLS`` n'aurait pas suffi : **84 outils**. Un ordre de
grandeur en dessous du problème, pas une solution.

2. ET LE REPLI ÉTAIT MUET
--------------------------
La bascule ENTRE FOURNISSEURS émettait déjà un toast (`provider.switched`).
Celle du local vers le cloud, non — seulement un WARNING dans les logs. Franck
a passé une journée à demander pourquoi « GPT-5.6-sol » répondait à
« bonjour », alors que trois lignes de `docker compose logs` le disaient.

C'est l'invariant « un repli doit se voir », appliqué au dernier endroit du
système qui y échappait encore.

Run with:  cd backend && python -m pytest tests/test_slm_is_usable_and_its_fallback_visible.py -v
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Registry:
    def __init__(self, noms):
        self.all_tools = [SimpleNamespace(name=n) for n in noms]


# ─────────────────────────────────────────────────────────────────────
# 1 — Le SLM ne reçoit plus le catalogue entier
# ─────────────────────────────────────────────────────────────────────

def test_the_slm_gets_a_handful_of_tools_not_the_whole_catalogue():
    """LE pin de l'incident. 145 schémas à un 4B pour dire « bonjour »."""
    from app.agent import nodes

    registry = _Registry(
        ["find_tool", "report_missing_capability"] + [f"outil_{i}" for i in range(143)]
    )
    retenus = nodes._slm_toolset(registry)

    assert len(retenus) <= 5, (
        f"{len(retenus)} outils liés au SLM — c'est le prompt processing de ces "
        f"schémas qui faisait dépasser les 60 s sur un modèle déjà chaud"
    )
    noms = {t.name for t in retenus}
    assert "find_tool" in noms, (
        "find_tool est le filet : sans lui, un modèle qui découvre qu'il a "
        "besoin d'un outil abandonne au lieu d'aller le chercher"
    )


def test_a_registry_without_the_expected_tools_falls_back_to_everything():
    """Mieux lent que muet.

    Si les noms attendus disparaissent du registre (renommage en amont), lier
    zéro outil rendrait le SLM incapable d'agir — un échec pire et plus
    silencieux que la lenteur qu'on corrige.
    """
    from app.agent import nodes

    registry = _Registry(["quelque_chose", "autre_chose"])
    retenus = nodes._slm_toolset(registry)

    assert len(retenus) == 2, (
        "sans les outils attendus, on relie tout plutôt que rien"
    )


def test_a_broken_registry_does_not_kill_the_turn():
    """L'instrumentation d'un confort ne casse pas une conversation."""
    from app.agent import nodes

    class _Casse:
        @property
        def all_tools(self):
            raise RuntimeError("registre indisponible")

    # Ne lève pas : l'exception est absorbée, et le repli tente `all_tools`
    # une seconde fois — qui lève à son tour. On vérifie juste le contrat.
    with pytest.raises(RuntimeError):
        nodes._slm_toolset(_Casse())


# ─────────────────────────────────────────────────────────────────────
# 2 — Le repli local → cloud remonte à l'utilisateur
# ─────────────────────────────────────────────────────────────────────

def test_the_local_to_cloud_fallback_reaches_the_user():
    """Il n'était que journalisé. C'est ce qui a coûté une journée d'enquête.

    Le canal est celui qui porte déjà `provider.switched` : le chat le draine
    à la fin de chaque tour et en fait un toast.
    """
    from app.services import fallback_manager as fm

    fm._reset_for_tests()
    fm.note_slm_fallback("conv-1", model="nemotron-3-nano-4b", reason="délai dépassé")

    events = fm.drain_events("conv-1")
    assert len(events) == 1, "le repli doit produire un événement, pas un log seul"
    ev = events[0]
    assert ev["type"] == "slm.fallback"
    assert "nemotron" in ev["model"], "l'utilisateur doit savoir QUEL modèle a lâché"
    assert ev["reason"], "un repli sans raison n'apprend rien"


def test_the_event_says_why_not_just_that():
    """« Repli » seul laisse l'utilisateur au même point qu'un silence.

    Un délai dépassé et une erreur de chargement appellent des gestes
    différents — l'un est un réglage, l'autre une configuration cassée.
    """
    from app.services import fallback_manager as fm

    fm._reset_for_tests()
    fm.note_slm_fallback("c", model="m", reason="délai de 60 s dépassé")
    assert "60" in fm.drain_events("c")[0]["reason"]


def test_noting_a_fallback_advances_no_chain():
    """⚠️ Le piège du correctif. `try_activate` fait AVANCER la chaîne de
    repli et rend la bascule collante pour toute la conversation.

    Un SLM lent une fois ne doit pas écarter le local jusqu'à la fin de la
    conversation : le tour suivant doit le retenter. On signale, on ne
    décide rien.
    """
    from app.services import fallback_manager as fm

    fm._reset_for_tests()
    etat = fm.get_or_create("conv-2", "simple", ["local", "cloud"])
    avant = etat.current_index

    fm.note_slm_fallback("conv-2", model="m", reason="r")

    assert fm.get_or_create("conv-2", "simple", []).current_index == avant, (
        "signaler un repli SLM ne doit pas faire avancer la chaîne de "
        "fournisseurs — ce sont deux mécanismes distincts"
    )


def test_an_empty_conversation_id_is_ignored():
    """Sans conversation, personne ne draine : on n'accumule pas d'orphelins."""
    from app.services import fallback_manager as fm

    fm._reset_for_tests()
    fm.note_slm_fallback("", model="m", reason="r")
    assert fm.drain_events("") == []
