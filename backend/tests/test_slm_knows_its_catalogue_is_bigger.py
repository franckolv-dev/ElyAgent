# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_knows_its_catalogue_is_bigger.py
# @brief      Un modèle qui ne voit pas l'outillage ne doit pas témoigner de
#             son absence.
# @license    Elastic License 2.0
# =============================================================================
"""Le 23/08, Ely a nié savoir chercher sur le web.

    Franck : « Trouve moi des sites, dans le style babelio, où les lecteurs
               peuvent mettre des critiques aux livres qu'ils ont lus… »

    Ely    : « Je ne peux pas trouver de sites comme Babelio car je n'ai pas
               accès à une base de données ou un outil permettant de rechercher
               des sites web en temps réel. Je ne sais pas si un tel site
               existe ou non. »

`web_search` existe, avec six fournisseurs en cascade derrière lui
(SearXNG → Serper → SearchCans → Google CSE → Tavily → DuckDuckGo). Et la
seconde phrase est pire que la première : c'est une conclusion sur LE MONDE,
tirée par un modèle qui n'a rien cherché.

CE N'EST PAS UNE HALLUCINATION, C'EST UNE CONSÉQUENCE
------------------------------------------------------
Le 21/08, la voie locale a cessé de recevoir le catalogue entier — 145 schémas
d'outils à un 4B faisaient dépasser les 60 s sur « bonjour ». Le SLM ne reçoit
plus que `find_tool` et `report_missing_capability`, `find_tool` étant désigné
comme LE filet vers tout le reste.

Le filet a été tendu **et personne n'a dit au modèle qu'il existait.**
`_SYSTEM_PROMPT_SLM` disait « utiliser les outils DISPONIBLES » ; de son point
de vue, aucun outil ne cherchait sur le web. Déclarer l'incapacité était donc,
littéralement, la réponse honnête. Le prompt nommait même quatre outils que la
voie locale n'a plus (`calendar_list_events`, `gmail_list_emails`,
`contacts_search`, `scheduler_list_tasks`).

⚠️ La classe de défaut est connue ici : #319, où le panel d'escalade a témoigné
de l'absence d'outils qu'Ely venait d'utiliser seize minutes plus tôt. La règle
en avait été tirée — « un relais qui ne voit pas l'outillage ne doit pas
témoigner de son absence » — mais elle n'a jamais été portée sur la voie SLM,
qui n'était pas encore empruntable à l'époque.

⚠️ LE ROUTAGE N'EST PAS EN CAUSE. La demande score 55, le seuil de Franck vaut
55, et `score <= seuil` envoie au local. Pile sur la barre. Remonter le seuil
déplacerait la frontière sans rien réparer : « quelle météo ? » a exactement le
même profil, et la voie locale n'a pas non plus d'outil météo.

CONNAÎTRE L'OUTIL NE SUFFIT PAS — le tour suivant le prouve
------------------------------------------------------------
Franck a demandé « liste les outils que tu as à disposition ». Toujours en
local, Ely a répondu qu'elle devait « utiliser l'outil `find_tool` », a nommé
`report_missing_capability`, a décrit correctement les deux — et n'en a appelé
aucun. Elle a fini par « Souhaites-tu que je cherche ce qui est nécessaire ? ».

Le modèle connaissait donc ses outils. Il a quand même choisi de les RACONTER :
il a demandé la permission d'appeler un outil de lecture, puis servi sa
plomberie en guise de réponse. Sur les trois tours observés, il a proposé une
action au lieu de la faire **trois fois**.

⚠️ Et le tour qui a fini par marcher — après le « oui » de Franck — est parti
au CLOUD : `gpt-5.6-sol`, ~89 400 tokens, c'est-à-dire le catalogue complet. Le
contournement n'a pas fait fonctionner la voie locale, il l'a fait quitter.
D'où deux règles de plus dans le prompt : ne pas demander la permission de
chercher, et traiter une question sur les capacités comme une recherche.

LES DEUX MOITIÉS DE LA RÉPARATION
----------------------------------
1. **La consigne** — le prompt dit désormais que la liste d'outils est un
   échantillon, et que « je n'ai pas d'outil pour ça » est faux par défaut.
2. **Le mécanisme** — les outils rendus par `find_tool` sont réellement liés au
   tour SLM suivant. Sans cette moitié, la consigne enverrait le modèle
   chercher un outil qu'il ne pourrait toujours pas appeler.

Un prompt reste une consigne, pas un verrou (invariant 3). C'est pour ça qu'il
en faut deux.

Run with:  cd backend && python -m pytest tests/test_slm_knows_its_catalogue_is_bigger.py -v
"""
from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

import pytest


class _Registry:
    def __init__(self, noms):
        self.all_tools = [SimpleNamespace(name=n) for n in noms]


# ─────────────────────────────────────────────────────────────────────
# 1 — La consigne : le modèle doit savoir que sa liste est un échantillon
# ─────────────────────────────────────────────────────────────────────

def test_the_slm_prompt_names_the_only_road_out():
    """LE pin de l'incident.

    Depuis le 21/08, `find_tool` est la SEULE voie entre le SLM et les ~145
    autres outils. Un prompt qui ne le nomme pas laisse le modèle conclure à
    l'incapacité — ce qu'il a fait.
    """
    from app.agent.prompts import _SYSTEM_PROMPT_SLM

    assert "find_tool" in _SYSTEM_PROMPT_SLM, (
        "le prompt SLM ne nomme pas `find_tool` — le modèle n'a alors aucun "
        "moyen de savoir que le catalogue existe, et « je n'ai pas d'outil "
        "pour ça » devient sa réponse honnête"
    )
    assert "report_missing_capability" in _SYSTEM_PROMPT_SLM, (
        "sans lui, un manque RÉEL se termine en prose au lieu d'être consigné"
    )


def test_the_slm_prompt_says_the_toolbox_is_a_sample():
    """Nommer `find_tool` ne suffit pas : il faut dire POURQUOI s'en servir.

    Un modèle qui voit deux outils et qu'on n'a pas prévenu croit qu'il en a
    deux. La phrase qui compte est celle qui invalide sa propre observation.
    """
    from app.agent.prompts import _SYSTEM_PROMPT_SLM

    bas = _SYSTEM_PROMPT_SLM.lower()
    assert "échantillon" in bas, (
        "le prompt ne dit pas que la liste d'outils est partielle"
    )
    assert "faux par défaut" in bas, (
        "le prompt ne renverse pas la conclusion « je n'ai pas d'outil » — "
        "c'est elle, et pas l'absence de `find_tool`, qui a produit la réponse "
        "du 23/08"
    )


def test_the_slm_prompt_forbids_concluding_about_the_world_without_looking():
    """« Je ne sais pas si un tel site existe ou non. »

    La phrase visée par ce pin. Nier une CAPACITÉ est déjà faux ; conclure sur
    l'existence de quelque chose dans le monde sans avoir cherché est d'un
    autre ordre — l'utilisateur repart en croyant que le sujet n'existe pas.
    C'est l'invariant « un repli doit se voir », vu depuis l'autre bout.
    """
    from app.agent.prompts import _SYSTEM_PROMPT_SLM

    bas = _SYSTEM_PROMPT_SLM.lower()
    assert "ne conclus jamais sur le monde ce que tu n'as pas cherché" in bas, (
        "rien n'interdit au modèle de trancher sur l'existence d'une chose "
        "qu'il n'a pas cherchée"
    )


def test_the_slm_prompt_forbids_asking_permission_to_search():
    """⚠️ MESURÉ AU TOUR SUIVANT, et c'est le plus instructif des trois.

    Franck : « liste les outils que tu as à disposition ». Ely, toujours en
    local, a répondu qu'elle devait « utiliser l'outil `find_tool` », a nommé
    `report_missing_capability`, décrit correctement les deux — et n'en a
    appelé aucun. Elle a terminé par « Souhaites-tu que je cherche ce qui est
    nécessaire ? ».

    Sur les trois tours observés, le modèle a PROPOSÉ une action au lieu de la
    faire trois fois. Connaître l'outil ne suffit donc pas : il faut lui
    retirer l'option de le raconter.

    ⚠️ Et ce n'est pas une garde d'autorisation qu'on contourne : la garde
    humaine s'applique aux outils ENGAGEANTS, par leur nom, dans le code.
    `find_tool` est en lecture — demander la permission de chercher n'a jamais
    protégé personne, ça a juste coûté un aller-retour.
    """
    from app.agent.prompts import _SYSTEM_PROMPT_SLM

    bas = _SYSTEM_PROMPT_SLM.lower()
    assert "ne demande pas la permission" in bas, (
        "rien n'interdit au modèle de demander l'autorisation d'appeler un "
        "outil de lecture — c'est ce qui a bloqué le tour du 23/08"
    )
    assert "souhaites-tu que je cherche" in bas, (
        "la formule exacte observée doit être citée comme contre-exemple : un "
        "4B suit bien mieux une interdiction nommée qu'une règle abstraite"
    )


def test_the_slm_prompt_turns_a_capability_question_into_a_search():
    """« Liste les outils que tu as » a produit un cours sur `find_tool`.

    La plomberie est devenue la réponse. Une question sur les capacités doit
    déclencher une RECHERCHE, dont le résultat est la réponse — l'utilisateur
    n'a pas à connaître le nom des rouages pour obtenir ce qu'il demande.
    """
    from app.agent.prompts import _SYSTEM_PROMPT_SLM

    bas = _SYSTEM_PROMPT_SLM.lower()
    assert "ce que tu sais faire" in bas and "lister tes outils" in bas, (
        "la question méta n'est pas traitée — elle retombe alors sur « je "
        "n'ai pas accès à la liste de mes outils »"
    )
    assert "n'explique jamais `find_tool` à l'utilisateur" in bas, (
        "rien n'empêche le modèle de servir sa plomberie en guise de réponse"
    )


def test_the_slm_prompt_never_names_a_tool_the_slm_cannot_call():
    """⚠️ LA DÉRIVE QUI SE REFERME TOUTE SEULE.

    Le prompt disait au modèle d'appeler `calendar_list_events`,
    `gmail_list_emails`, `contacts_search` et `scheduler_list_tasks`. Aucun
    des quatre n'est lié à la voie locale depuis le 21/08 : la consigne
    envoyait le modèle appeler des outils absents.

    Ce pin confronte le prompt au registre RÉEL. Tout nom d'outil existant
    qu'il cite doit être un outil que le SLM peut effectivement appeler —
    sinon la consigne ment, et un modèle de 4 milliards de paramètres n'a
    aucun moyen de s'en apercevoir.
    """
    from app.agent.nodes import _SLM_TOOL_NAMES
    from app.agent.prompts import _SYSTEM_PROMPT_SLM
    from app.skills import get_skill_registry
    from app.skills.builtin import register_all

    register_all()
    reels = {t.name for t in get_skill_registry().all_tools}
    cites = set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", _SYSTEM_PROMPT_SLM))

    fautifs = sorted((cites & reels) - set(_SLM_TOOL_NAMES))
    assert not fautifs, (
        f"le prompt SLM demande d'appeler {fautifs}, que la voie locale ne lie "
        f"pas. Soit on les ajoute à _SLM_TOOL_NAMES — au prix du prompt "
        f"processing qui a motivé le 21/08 — soit on passe par `find_tool`."
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Le mécanisme : ce que `find_tool` promet doit être vrai
# ─────────────────────────────────────────────────────────────────────

def test_a_discovered_tool_becomes_callable_on_the_local_path():
    """`find_tool` répond « utilise-les directement maintenant ».

    La voie cloud tenait cette promesse, la voie locale non : sa liaison
    restait figée à deux outils dans la fermeture de `create_agent_node`.
    """
    from app.agent import discovered_tools, nodes

    conv = "conv-test-decouverte"
    discovered_tools.discard_discovered(conv)
    discovered_tools.add_discovered(conv, ["web_search"])
    try:
        registry = _Registry(["find_tool", "report_missing_capability",
                              "web_search", "weather_get"])
        extras = nodes._slm_discovered_extras(registry, conv)
        assert [t.name for t in extras] == ["web_search"], (
            "l'outil découvert n'est pas rendu liable au tour local suivant"
        )
    finally:
        discovered_tools.discard_discovered(conv)


def test_a_base_tool_is_never_bound_twice():
    """`find_tool` se découvre lui-même sans le vouloir. Le lier deux fois
    envoie deux schémas identiques au modèle — du prompt processing payé pour
    rien, sur la voie précisément choisie pour être rapide."""
    from app.agent import discovered_tools, nodes

    conv = "conv-test-doublon"
    discovered_tools.discard_discovered(conv)
    discovered_tools.add_discovered(conv, ["find_tool", "web_search"])
    try:
        registry = _Registry(["find_tool", "report_missing_capability", "web_search"])
        noms = [t.name for t in nodes._slm_discovered_extras(registry, conv)]
        assert noms == ["web_search"], f"doublon lié : {noms}"
    finally:
        discovered_tools.discard_discovered(conv)


@pytest.mark.parametrize("conv", ["", "conv-sans-decouverte"])
def test_nothing_discovered_means_the_cached_lean_binding_is_reused(conv):
    """Le cas courant doit rester gratuit.

    Rendre une liste vide est ce qui permet au nœud de garder sa liaison en
    cache au lieu de refaire un `bind_tools` à chaque tour.
    """
    from app.agent import nodes

    registry = _Registry(["find_tool", "report_missing_capability", "web_search"])
    assert nodes._slm_discovered_extras(registry, conv) == []


def test_a_broken_registry_does_not_kill_the_turn():
    """Une commodité de liaison ne fait pas tomber une conversation.

    ⚠️ Ce contrat compte plus qu'il n'en a l'air : l'échec doit rendre `[]`,
    donc retomber sur la liaison maigre — le modèle reste capable d'agir, il
    devra juste repasser par `find_tool`.
    """
    from app.agent import discovered_tools, nodes

    class _Casse:
        @property
        def all_tools(self):
            raise RuntimeError("registre indisponible")

    conv = "conv-test-casse"
    discovered_tools.discard_discovered(conv)
    discovered_tools.add_discovered(conv, ["web_search"])
    try:
        assert nodes._slm_discovered_extras(_Casse(), conv) == []
    finally:
        discovered_tools.discard_discovered(conv)


def test_the_local_inference_uses_the_binding_that_includes_discoveries():
    """⚠️ LE PIN QUI COMPTE VRAIMENT, et il ne peut être que textuel.

    `_slm_discovered_extras` peut être parfaite et le nœud invoquer quand même
    `_slm_with_tools`, la liaison en cache à deux outils. Le défaut serait
    invisible : le modèle répondrait, simplement sans jamais pouvoir appeler ce
    qu'il vient de trouver.

    On lit donc le bloc d'inférence SLM et on vérifie ce qui y est réellement
    invoqué.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("if use_slm:", 1)[1].split("if response is None:", 1)[0]

    assert "_slm_discovered_extras(" in bloc, (
        "le tour local ne consulte pas les découvertes de la conversation"
    )
    assert "_slm_runtime.ainvoke(" in bloc, (
        "le tour local invoque une autre liaison que celle qui unionne les "
        "découvertes — `find_tool` promettrait alors dans le vide"
    )
    assert "_slm_with_tools.ainvoke(" not in bloc, (
        "la liaison maigre en cache est invoquée directement : les outils "
        "découverts sont ignorés"
    )


def test_the_local_path_after_find_tool_is_not_theoretical(monkeypatch):
    """⚠️ PIN DE CONTRAT, pas de défaut : il passe aussi AVANT la correction.

    Il n'attrape rien — il justifie que les précédents existent, et rougira si
    quelqu'un décide plus tard que « de toute façon, après `find_tool` le tour
    repart toujours au cloud ».

    POURQUOI LE TROU NE SE VOYAIT PAS. Au tour suivant, `user_query` vaut
    ``messages[-1]``, donc le RETOUR de l'outil et non la demande de
    l'utilisateur. Le message de succès de `find_tool` dépasse 80 caractères,
    ce qui vaut +10 au score et repasse la barre : le tour repartait au cloud,
    où la liaison est complète. Le filet ne marchait que par cet accident de
    scoring — raccourcir ce message l'aurait cassé sans que rien ne rougisse.

    ET LE CAS INVERSE EST CELUI QUI COMPTE : quand `find_tool` ne trouve rien,
    sa réponse est courte, le score reste bas, le tour reste LOCAL. C'est
    exactement là que `report_missing_capability` doit être appelé.

    ⚠️ Le seuil et l'activation sont IMPOSÉS ici. Première version de ce pin :
    il lisait l'environnement, donc il rougissait sans `SLM_ENABLED=true` —
    un test qui mesure la configuration de la machine au lieu du code.
    """
    import app.config as config
    from app.services.intent_router import ModelTier, get_intent_router

    monkeypatch.setattr(
        config, "get_settings",
        lambda: SimpleNamespace(slm_enabled=True, slm_complexity_threshold=40),
    )
    router = get_intent_router()

    court = "Aucun outil ne correspond."
    assert router.route(court).tier == ModelTier.SLM, (
        "un retour d'outil court garde le tour en local — c'est le chemin du "
        "gap réel, et il a besoin d'une liaison correcte"
    )

    long = (
        "Outils disponibles pour « rechercher sur le web » (utilise-les "
        "directement maintenant) :\n  • web_search — Search the web."
    )
    assert router.route(long).tier == ModelTier.LLM, (
        "si même un retour de `find_tool` fourni restait en local, la liaison "
        "des découvertes deviendrait le SEUL chemin — et non plus un filet"
    )
