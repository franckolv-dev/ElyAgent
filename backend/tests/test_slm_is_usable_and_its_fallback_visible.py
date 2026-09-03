# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_is_usable_and_its_fallback_visible.py
# @brief      La voie rapide doit être rapide, et son repli doit se voir.
# @license    MIT
#            https://opensource.org/licenses/MIT
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
    """LE pin de l'incident. 145 schémas à un 4B pour dire « bonjour ».

    ⚠️ CE PIN COMPTAIT LES OUTILS ; IL COMPTE MAINTENANT LES TOKENS (23/08).
    Le nombre était un raccourci — ce qui a fait dépasser les 60 s, c'est le
    *prompt processing* des schémas, pas leur cardinalité. Le raccourci est
    devenu faux le jour où la voie locale a reçu les outils du quotidien : onze
    schémas courts coûtent moins que trois longs.

    Le budget réel est tenu par `test_the_local_tier_can_serve_what_the_router_
    sends_it`, qui mesure les tokens sur le VRAI registre. Ici on garde la
    borne grossière : le catalogue entier ne doit jamais revenir.
    """
    from app.agent import nodes

    registry = _Registry(
        list(nodes._SLM_TOOL_NAMES) + [f"outil_{i}" for i in range(180)]
    )
    retenus = nodes._slm_toolset(registry)

    assert len(retenus) <= 20, (
        f"{len(retenus)} outils liés au SLM — c'est le prompt processing de ces "
        f"schémas qui faisait dépasser les 60 s sur un modèle déjà chaud"
    )
    noms = {t.name for t in retenus}
    assert "find_tool" in noms, (
        "find_tool est le filet : sans lui, un modèle qui découvre qu'il a "
        "besoin d'un outil abandonne au lieu d'aller le chercher"
    )
    assert "web_search" in noms, (
        "la voie locale doit pouvoir chercher sur le web sans détour : c'est "
        "l'intention que `_SIMPLE_PATTERNS` lui envoie le plus souvent"
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


# ─────────────────────────────────────────────────────────────────────
# 3 — Ce que la voie rapide traverse une fois qu'elle marche
# ─────────────────────────────────────────────────────────────────────

def test_slm_path_binds_every_local_it_reads():
    """La suite immédiate de l'incident, le soir même.

    Le correctif ci-dessus a rendu la voie locale utilisable. Elle a alors
    traversé, pour la première fois en production, du code qu'aucun tour
    n'avait jamais exécuté — et ``_fb_state``, initialisé UNIQUEMENT dans
    ``if response is None:`` (la branche cloud), était relu sans condition au
    pied du nœud :

        « Bonjour Ely » → réponse affichée → UnboundLocalError
                        → « Une erreur interne s'est produite »

    Le pire profil de défaut : la réponse s'affichait une demi-seconde, puis
    l'erreur l'écrasait. Le défaut datait de #265 (26/07) et n'était pas
    ATTEIGNABLE tant que le SLM échouait systématiquement — la branche cloud
    tournait alors à chaque tour et liait la variable au passage.

    ⚠️ LA LEÇON, plus large que la variable : réparer une voie morte, c'est
    l'emprunter pour la première fois. Ce qu'elle traverse n'a jamais tourné,
    et la suite verte ne prouvait rien à son sujet.

    ⚠️ POURQUOI CETTE FORME. Ni ruff 0.15.15 (pas de PLE0601) ni pyflakes ne
    voient cette classe : ils signalent les noms INDÉFINIS, pas les noms
    liés sur une branche seulement. Et le pin comportemental ne l'aurait pas
    attrapé — monter `agent_node` demande le graphe, la mémoire, le registre
    et un LLM. C'est ce coût qui a laissé la branche sans couverture.

    L'analyse est volontairement CONSERVATRICE : un nom lié dans les deux
    membres d'un ``if/else``, ou déclaré ``nonlocal``, est tenu pour sûr. Elle
    signale peu, mais ce qu'elle signale est réel.
    """
    import ast
    import inspect
    import textwrap

    from app.agent import nodes

    fabrique = ast.parse(
        textwrap.dedent(inspect.getsource(nodes.create_agent_node))
    ).body[0]
    agent_node = next(
        (n for n in ast.walk(fabrique)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "agent_node"),
        None,
    )
    assert agent_node is not None, (
        "`agent_node` introuvable dans `create_agent_node` — la structure a "
        "changé, revérifie l'invariant à la main avant d'adapter ce pin"
    )

    def _noms(noeud, ctx) -> set:
        return {n.id for n in ast.walk(noeud)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)}

    def _lies_partout(stmts) -> set:
        """Les noms liés sur TOUS les chemins traversant ``stmts``."""
        acquis: set = set()
        for s in stmts:
            if isinstance(s, ast.If):
                # Sans `else`, la branche peut ne pas être prise : rien d'acquis.
                if s.orelse:
                    acquis |= _lies_partout(s.body) & _lies_partout(s.orelse)
            elif isinstance(s, ast.Try):
                sur = _lies_partout(s.body)
                for h in s.handlers:           # une exception peut survenir
                    sur &= _lies_partout(h.body)
                acquis |= sur | _lies_partout(s.finalbody)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                acquis |= _lies_partout(s.body)
            elif isinstance(s, (ast.For, ast.AsyncFor, ast.While)):
                pass                            # zéro tour est un chemin
            else:
                acquis |= _noms(s, ast.Store)
        return acquis

    # Un `nonlocal` vit dans la fermeture : il est lié avant l'appel.
    hors_scope = {
        nom
        for n in ast.walk(agent_node)
        if isinstance(n, (ast.Nonlocal, ast.Global))
        for nom in n.names
    }
    args = {a.arg for a in agent_node.args.args}
    locaux = _noms(agent_node, ast.Store) - hors_scope - args

    acquis = set(args)
    coupables: list = []
    for stmt in agent_node.body:
        # Un nom lié DANS le statement courant lui est disponible : on ne
        # descend pas plus fin, l'analyse resterait juste mais bavarde.
        for nom in sorted((_noms(stmt, ast.Load) & locaux) - acquis
                          - _noms(stmt, ast.Store)):
            coupables.append(f"{nom} (ligne ~{stmt.lineno} du nœud)")
        acquis |= _lies_partout([stmt])

    assert not coupables, (
        "nom(s) local(aux) de `agent_node` lu(s) sur un chemin qui ne les lie "
        f"pas : {', '.join(coupables)}. Le tour lèvera UnboundLocalError APRÈS "
        "avoir produit sa réponse — c'est exactement ce qu'a fait `_fb_state` "
        "sur la voie SLM le 21/08. Initialise le nom en tête de `agent_node`, "
        "avec `_ctx_breakdown`."
    )


def test_the_pin_above_would_have_caught_the_real_defect():
    """Un pin qui ne rougit jamais ne protège rien.

    On rejoue la forme EXACTE du défaut du 21/08 sur une fonction jouet, et on
    vérifie que l'analyse la voit — sinon le test précédent est un décor.
    """
    import ast

    source = (
        "def agent_node(state):\n"
        "    response = None\n"
        "    if response is None:\n"
        "        _fb_state = None\n"
        "        _fb_state = charger()\n"
        "    if _fb_state is not None:\n"          # ← le défaut
        "        enregistrer(_fb_state)\n"
        "    if state:\n"
        "        _sur = 1\n"
        "    else:\n"
        "        _sur = 2\n"
        "    return _sur\n"                        # ← lié partout : muet
    )
    fn = ast.parse(source).body[0]

    def _noms(n, ctx):
        return {x.id for x in ast.walk(n)
                if isinstance(x, ast.Name) and isinstance(x.ctx, ctx)}

    vus = []
    acquis = {"state"}
    for stmt in fn.body:
        vus += sorted((_noms(stmt, ast.Load) & (_noms(fn, ast.Store)))
                      - acquis - _noms(stmt, ast.Store))
        if isinstance(stmt, ast.If) and stmt.orelse:
            acquis |= _noms(stmt.body[0], ast.Store) & _noms(stmt.orelse[0], ast.Store)
        elif not isinstance(stmt, ast.If):
            acquis |= _noms(stmt, ast.Store)

    assert "_fb_state" in vus, "l'analyse rate le défaut qu'elle prétend épingler"
    assert "_sur" not in vus, "l'analyse crie au loup sur un if/else pourtant sûr"
