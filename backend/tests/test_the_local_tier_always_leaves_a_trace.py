# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_the_local_tier_always_leaves_a_trace.py
# @brief      « GPT-5.6 a répondu — est-ce gemma qui a passé la main ? »
# @license    Elastic License 2.0
# =============================================================================
"""Une question sans réponse, le 23/08 à 21 h 07.

Franck demande quelque chose, GPT-5.6 répond, et il veut savoir si la voie
locale a essayé. `usage_logs` ne montre que deux lignes `gpt-5.6-sol` pour sa
conversation — aucune ligne locale.

**J'en ai conclu que gemma n'avait jamais vu la demande. C'était faux.** La
trace `[routing]` disait :

    [routing] conv=26556c11 slm=slm   score=55     ← le tour EST parti en local
    [routing] conv=26556c11 slm=cloud score=100    ← puis six tours cloud
    [routing] conv=26556c11 turn=complex …

La voie locale avait bien reçu la demande. Elle a émis un appel d'outil — donc
pas de réponse finale, donc **aucune ligne dans `usage_logs`**, qui n'enregistre
que le modèle ayant RENDU la réponse. Puis le tour a escaladé au score : au tour
suivant, `messages[-1]` est le retour d'outil, long et truffé d'URL, ce qui vaut
+20 et +15 et fait sauter la barre.

CE QUE CET ÉPISODE MONTRE
--------------------------
Deux scénarios opposés — « le local a travaillé puis escaladé » et « le local
n'a jamais été consulté » — produisaient **exactement les mêmes lignes** dans la
seule source durable. Il a fallu une ligne de log, dans un conteneur qui aurait
pu être recréé entre-temps, pour les séparer.

⚠️ Et cette ligne n'existait que parce que le SLM était présent : `routing_note`
vivait À L'INTÉRIEUR de `if _slm_with_tools is not None`. Le jour où la voie
locale est éteinte ou cassée, il n'y a plus rien du tout — ni trace, ni ligne
d'usage, ni toast. C'est le trou que ce fichier ferme.

LES DEUX TROUS
---------------
1. **Un tour qui ne consulte pas la voie locale est une DÉCISION**, et une
   décision non tracée est indiscernable d'une panne. La note part désormais
   dans tous les cas, avec la raison : `slm_desactive`, `slm_indisponible`,
   `tache_planifiee`.

2. **Un échec de construction du SLM était définitif.** La reconstruction est
   gardée par `if _slm_with_tools is not None` : un `get_slm()` qui lève au
   démarrage tuait la voie locale pour toute la vie du process, avec un seul
   WARNING au boot pour tout signal. Cas banal — `docker compose up` démarre le
   backend avant que LM Studio soit prêt sur l'hôte. Le seul remède était un
   redémarrage manuel, décidé sans rien pour le motiver.

Run with:  cd backend && python -m pytest tests/test_the_local_tier_always_leaves_a_trace.py -v
"""
from __future__ import annotations

import inspect

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1 — Chaque tour laisse une trace, voie locale ou pas
# ─────────────────────────────────────────────────────────────────────

def test_a_turn_without_the_local_tier_is_still_traced():
    """LE pin de l'épisode.

    `routing_note` était dans la branche `if _slm_with_tools is not None`.
    Quand la voie locale n'existe pas, aucune ligne `[routing]` n'était émise —
    et `usage_logs` ne porte que le modèle qui a rendu la réponse. La question
    « est-ce que le local a essayé ? » n'avait alors aucune source.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("use_slm = False", 1)[1].split("Refactor 2026-05-25", 1)[0]

    assert bloc.count("routing_note(") >= 2, (
        "un seul appel à `routing_note` : le cas « voie locale absente » ne "
        "laisse toujours aucune trace"
    )
    assert "else:" in bloc, (
        "il n'y a pas de branche pour le cas où la voie locale n'est pas "
        "consultée — c'est pourtant une décision, pas un non-événement"
    )


@pytest.mark.parametrize("raison", [
    "slm_desactive",     # SLM_ENABLED=false
    "slm_indisponible",  # construction échouée
    "tache_planifiee",   # les tours automatisés vont au cloud par conception
])
def test_the_reason_says_which_of_the_three_cases_it_was(raison):
    """« cloud » sans raison ne renseigne pas : les trois cas se soignent
    différemment. Un `SLM_ENABLED=false` se règle dans le `.env`, une
    construction échouée demande un serveur local, une tâche planifiée est le
    comportement voulu."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert f'"{raison}"' in src, f"la raison « {raison} » n'est jamais émise"


def test_an_abandoned_local_attempt_is_traced_not_just_toasted():
    """⚠️ LE TOAST EST ÉPHÉMÈRE, et c'est ce qui a manqué.

    `note_slm_fallback` pousse un événement dans l'interface — il vit le temps
    d'un tour et personne ne le retrouve le lendemain. Or c'est précisément le
    lendemain qu'on demande « qui a répondu, et pourquoi ? ».

    La note `[routing]` est la moitié durable. Elle est émise par la MÊME
    fonction, donc les trois points d'abandon (délai, erreur, appel écrit en
    texte) la produisent sans qu'on ait à y penser à chaque fois.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes._annoncer_repli_slm)
    assert "note_slm_fallback(" in src, "le toast a disparu"
    assert "routing_note(" in src, (
        "le repli n'est plus tracé — il ne reste que le toast, qui ne survit "
        "pas au tour"
    )
    assert "cloud_apres_local" in src, (
        "la trace doit DISTINGUER « le local a essayé puis abandonné » de "
        "« le local n'a pas été consulté » — c'est toute la question du 23/08"
    )


def test_the_trace_survives_a_broken_toast():
    """Les deux moitiés sont indépendantes : un canal d'interface cassé ne doit
    pas emporter la trace durable avec lui."""
    from app.agent import nodes

    src = inspect.getsource(nodes._annoncer_repli_slm)
    # Deux `try` distincts, pas un seul qui engloberait les deux appels.
    assert src.count("try:") == 2, (
        "toast et trace partagent un `try` : si le premier lève, le second "
        "n'est jamais atteint"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Un échec de construction n'est plus définitif
# ─────────────────────────────────────────────────────────────────────

def test_a_failed_slm_build_is_retried():
    """⚠️ La reconstruction existante est gardée par `is not None`.

    Elle répare un SLM qui existe ; elle ne ressuscite pas celui qui n'a jamais
    été construit. Un `get_slm()` qui lève au démarrage — LM Studio pas encore
    levé, instance mal configurée — condamnait la voie locale jusqu'au prochain
    `make down && make up`, avec un unique WARNING au boot pour tout signal.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert "_slm_with_tools is None" in src, (
        "rien ne retente une construction ratée : la voie locale reste morte "
        "pour toute la vie du process"
    )
    assert "_slm_echec_a" in src and "_SLM_REPRISE_S" in src, (
        "la reprise n'est pas temporisée — elle retenterait à chaque tour, "
        "y compris quand le serveur local est éteint pour de bon"
    )


def test_the_retry_also_fires_on_a_configuration_change():
    """Deux déclencheurs, et le second compte autant que le premier.

    La temporisation couvre « le serveur s'est levé entre-temps ». Le changement
    de configuration couvre « l'administrateur vient de désigner un autre
    modèle » — attendre deux minutes après un réglage explicite serait le même
    genre de silence que la #342 corrigeait.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("_slm_with_tools is None", 1)[1].split("Mêmes DEUX conditions", 1)[0]

    assert "current_cfg_version != _slm_cfg_version" in bloc, (
        "un changement de modèle dans Réglages → Routage ne relance pas la "
        "construction : l'administrateur attendrait la temporisation sans le "
        "savoir"
    )


def test_a_successful_retry_announces_itself():
    """Une voie locale qui revient change ce qu'Ely fait et ce qu'elle coûte.
    Le silence ferait attribuer le changement de comportement à autre chose."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert "SLM reconstruit après un échec de démarrage" in src, (
        "la reprise est muette — invariant « un repli doit se voir », dans "
        "l'autre sens"
    )


def test_the_retry_does_not_flood_the_log_while_the_server_is_down():
    """⚠️ Une tentative toutes les deux minutes, chacune en WARNING, noierait
    tout le reste sur une machine où le serveur local est éteint pour de bon.

    L'absence de voie locale est déjà tracée à CHAQUE tour par la note
    `[routing] slm=cloud raison=slm_indisponible` — l'information n'est pas
    perdue, elle est juste au bon endroit.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src.split("_slm_with_tools is None", 1)[1].split("Mêmes DEUX conditions", 1)[0]

    assert "logger.info(" in bloc and "SLM toujours indisponible" in bloc, (
        "l'échec de reprise doit rester en `info` : c'est un état attendu, "
        "pas un incident, et il se répète"
    )
