# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_a_tool_call_written_as_text_is_not_an_answer.py
# @brief      « find_tool("…") » affiché à l'utilisateur en guise de réponse.
# @license    MIT
# =============================================================================
"""Le 23/08, Ely a répondu par un appel de fonction.

    Franck : « Trouve moi des sites, dans le style babelio […] »
    Ely    : find_tool("sites de critiques de livres en ligne")

Le texte partait tel quel à l'écran. Aucune erreur, aucun délai dépassé, une
réponse rendue : le tour était un **succès** pour tout le système.

⚠️ C'EST UNE RÉGRESSION QUE LE CORRECTIF PRÉCÉDENT A INTRODUITE
----------------------------------------------------------------
La #341 disait au modèle local, avec insistance, d'appeler `find_tool` avant
de conclure à l'incapacité. Elle ne lui a pas dit **par quel canal**. Le modèle
a obéi — en écrivant l'appel. Ajouter une consigne sans vérifier que la voie
sait encaisser ce qu'elle déclenche déplace le défaut au lieu de le régler.

TROIS CAUSES, ET LA PREMIÈRE EST STRUCTURELLE
-----------------------------------------------
1. **La récupération d'appels textuels n'était câblée que sur la voie cloud.**
   `recover_tool_calls_into_response` existe depuis le 06/05 et vit dans
   `if response is None:`. La voie SLM ne l'a jamais eue. C'est le TROISIÈME
   filet dans ce cas — après la liaison des découvertes de `find_tool` (#341)
   et l'invalidation du cache d'instances (#342). Un mécanisme de sûreté câblé
   sur une seule des deux voies est le motif récurrent de ce mois.

2. **Aucun motif ne couvrait la forme produite.** Les quatre motifs existants
   viennent de modèles cloud qui émettent du JSON balisé — `<tool_call>{…}`,
   ```` ```json ````, objet JSON nu. Un petit modèle local écrit ce qu'il a lu
   dans son prompt : `find_tool("…")`. Pas de balise, pas de clé `name`.

3. **`_SYSTEM_PROMPT_SLM` ne disait pas d'appeler nativement.** La règle existe
   mot pour mot dans `_SYSTEM_PROMPT_BASE` depuis longtemps.

CE QUE FRANCK A PERDU EN CHANGEANT DE MODÈLE
----------------------------------------------
    « Au moins nemotron avait transféré la tâche à GPT-5.6 rapidement… »

Il a raison, et ça oriente la réparation. L'ancien modèle **dépassait son
délai** : le repli partait, annoncé, et l'utilisateur avait sa réponse. Le
nouveau **réussit** — vite, 3,6 s — et boucle en local sans jamais rendre la
main. Un échec rapide et visible vaut mieux qu'un succès apparent.

D'où le troisième volet : un appel écrit en texte et non exécuté est traité
comme un ÉCHEC de la voie locale, annoncé par `note_slm_fallback`, et le tour
repart au cloud. On ne compte pas sur la seule récupération.

Run with:  cd backend && python -m pytest tests/test_a_tool_call_written_as_text_is_not_an_answer.py -v
"""
from __future__ import annotations

import inspect

import pytest

_NOMS = {"find_tool", "report_missing_capability", "web_search", "gmail_send_email"}
_PREMIER = {"find_tool": "capability", "web_search": "query"}.get


# ─────────────────────────────────────────────────────────────────────
# 1 — La forme exacte du 23/08 est récupérée
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte,attendu", [
    # LA ligne que Franck a lue à l'écran.
    ('find_tool("sites de critiques de livres en ligne")',
     {"capability": "sites de critiques de livres en ligne"}),
    ("  find_tool('x')  ", {"capability": "x"}),
    ('find_tool(capability="sites de critiques")', {"capability": "sites de critiques"}),
    ('find_tool({"capability": "livres"})', {"capability": "livres"}),
    ("find_tool()", {}),
])
def test_a_bare_call_is_recovered(texte, attendu):
    """LE pin de l'incident. Un appel écrit à la main doit s'exécuter."""
    from app.agent.tool_call_recovery import parse_bare_tool_calls

    trouves = parse_bare_tool_calls(texte, _NOMS, _PREMIER)
    assert trouves == [{"name": "find_tool", "arguments": attendu}], (
        f"« {texte} » n'est pas récupéré — il repart à l'écran tel quel"
    )


def test_the_positional_argument_is_bound_from_the_real_schema():
    """`find_tool("…")` ne porte AUCUN nom de paramètre.

    Le deviner produirait un appel plausible et faux, ce qui est pire que pas
    d'appel du tout : un appel raté se voit, un appel mal lié rend un résultat
    crédible. Le nom vient donc du schéma réel de l'outil, ou l'appel est
    abandonné.
    """
    from app.agent.tool_call_recovery import parse_bare_tool_calls

    assert parse_bare_tool_calls('web_search("babelio")', _NOMS, _PREMIER) == [
        {"name": "web_search", "arguments": {"query": "babelio"}}
    ]
    # Sans résolveur de paramètre, on n'invente pas.
    assert parse_bare_tool_calls('web_search("babelio")', _NOMS, None) == []


# ─────────────────────────────────────────────────────────────────────
# 2 — Ce qu'il ne faut SURTOUT pas attraper
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prose", [
    "Je vais utiliser find_tool pour chercher.",
    "Appelle `find_tool` si besoin, il sert à ça.",
    "L'outil find_tool (l'annuaire) choisit parmi les 200 outils.",
    "Voici les sites : Booknode, Livraddict et SensCritique.",
])
def test_prose_that_merely_mentions_a_tool_is_never_executed(prose):
    """⚠️ LE RISQUE DE CE CORRECTIF, et pourquoi le motif exige la ligne
    ENTIÈRE.

    Une ligne de texte ordinaire ressemble bien plus à un appel qu'un bloc
    JSON balisé. Attraper une mention en prose enverrait Ely appeler un outil
    parce qu'elle vient d'en parler — un effet de bord déclenché par une
    explication.
    """
    from app.agent.tool_call_recovery import parse_bare_tool_calls

    assert parse_bare_tool_calls(prose, _NOMS, _PREMIER) == []


def test_an_unknown_name_is_never_fuzzy_matched_on_a_bare_call():
    """Les motifs JSON tolèrent le rapprochement flou (`send_email` →
    `gmail_send_email`) parce qu'une balise est une intention explicite. Sur
    une ligne de texte nue, la même souplesse ferait exécuter n'importe quelle
    ligne finissant par des parenthèses."""
    from app.agent.tool_call_recovery import parse_bare_tool_calls

    assert parse_bare_tool_calls('outil_inconnu("x")', _NOMS, _PREMIER) == []
    assert parse_bare_tool_calls('send_email("a@b.c")', _NOMS, _PREMIER) == []


def test_unbindable_arguments_are_dropped_not_guessed():
    """Mieux vaut ne pas appeler qu'appeler avec le mauvais paramètre."""
    from app.agent.tool_call_recovery import parse_bare_tool_calls

    assert parse_bare_tool_calls("find_tool(42, foo, bar)", _NOMS, _PREMIER) == []


# ─────────────────────────────────────────────────────────────────────
# 3 — Constater l'échec quand la récupération ne peut rien
# ─────────────────────────────────────────────────────────────────────

def test_an_unexecuted_call_is_detected_even_mid_sentence():
    """Plus large que le motif de récupération, et c'est voulu.

    ⚠️ N'est consulté qu'APRÈS avoir constaté `tool_calls == []`. Sous cette
    condition, une mention d'appel ne peut plus être le récit de ce que le
    modèle VIENT de faire — c'est une tentative qui n'a pas abouti. Rien ne
    part vers un outil sur la foi de cette fonction : elle ne sert qu'à
    décider d'un repli.
    """
    from app.agent.tool_call_recovery import looks_like_an_unexecuted_tool_call

    assert looks_like_an_unexecuted_tool_call(
        "je vais appeler find_tool(...) ensuite", _NOMS) == "find_tool"
    assert looks_like_an_unexecuted_tool_call(
        "Voici trois sites de critiques littéraires.", _NOMS) is None
    assert looks_like_an_unexecuted_tool_call("", _NOMS) is None


# ─────────────────────────────────────────────────────────────────────
# 4 — Le câblage : la voie locale a enfin le filet de la voie cloud
# ─────────────────────────────────────────────────────────────────────

def test_the_local_path_recovers_text_tool_calls_like_the_cloud_one():
    """⚠️ TROISIÈME FILET CÂBLÉ SUR UNE SEULE VOIE ce mois-ci.

    La récupération vit dans `if response is None:` depuis le 06/05 — la
    branche cloud. La voie SLM ne l'a jamais eue, alors que c'est elle qui
    sert les plus petits modèles, donc ceux qui violent le plus le contrat de
    tool-calling.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]

    assert "recover_tool_calls_into_response(" in bloc, (
        "la voie locale ne récupère pas les appels écrits en texte — ils "
        "repartent à l'écran comme réponse"
    )
    assert "premier_parametre=" in bloc, (
        "sans résolveur de paramètre, `find_tool(\"…\")` est ignoré : c'est "
        "exactement la forme observée"
    )


def test_an_unexecuted_call_hands_back_to_the_cloud_visibly():
    """« Au moins nemotron avait transféré la tâche à GPT-5.6 rapidement. »

    Le modèle précédent dépassait son délai : le repli partait, annoncé. Le
    nouveau RÉUSSIT en 3,6 s et boucle en local. Sans ce volet, la
    récupération serait le seul recours — et le jour où elle ne reconnaît pas
    une forme, l'utilisateur reboucle sans que rien ne le signale.

    `response = None` rend la main à la branche cloud existante ; le repli
    passe par `note_slm_fallback`, donc il s'affiche (invariant « un repli
    doit se voir »).
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]

    assert "looks_like_an_unexecuted_tool_call(" in bloc, (
        "rien ne constate qu'une réponse locale est un appel manqué"
    )
    assert "_annoncer_repli_slm(" in bloc and "response = None" in bloc, (
        "le repli doit être ANNONCÉ et rendre la main au cloud — sinon "
        "l'utilisateur reboucle en local sans savoir pourquoi"
    )


# ─────────────────────────────────────────────────────────────────────
# 5 — La consigne qui manquait à la #341
# ─────────────────────────────────────────────────────────────────────

def test_the_slm_prompt_demands_native_tool_calling():
    """La règle existe mot pour mot dans `_SYSTEM_PROMPT_BASE`. Elle n'avait
    jamais été portée sur le prompt local — celui du modèle le plus susceptible
    d'écrire son appel au lieu de l'émettre."""
    from app.agent.prompts import _SYSTEM_PROMPT_BASE, _SYSTEM_PROMPT_SLM

    assert "tool-calling natif" in _SYSTEM_PROMPT_BASE.lower(), (
        "le prompt complet a perdu sa règle — ce pin part de son existence"
    )
    bas = _SYSTEM_PROMPT_SLM.lower()
    assert "tool-calling natif" in bas, (
        "le prompt local ne dit pas PAR QUEL CANAL appeler : lui demander "
        "d'appeler `find_tool` sans ça le fait écrire l'appel"
    )
    assert "s'affichent" in bas, (
        "la conséquence doit être nommée — un 4B suit mieux une règle dont "
        "l'effet est écrit"
    )
