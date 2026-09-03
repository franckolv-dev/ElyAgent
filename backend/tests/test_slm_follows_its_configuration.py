# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_follows_its_configuration.py
# @brief      Changer le modèle du tier A doit avoir un effet, et se documenter.
# @license    MIT
# =============================================================================
"""Deux dettes de la série SLM, soldées le 22/08.

1. LE CACHE NE SUIVAIT PAS LE ROUTAGE
--------------------------------------
Le cache du SLM ne surveillait que ``registry.tools_version``. Changer le
modèle du tier A dans Réglages → Routage ne le reconstruisait donc **pas** :
Ely continuait de servir l'ancien modèle jusqu'au redémarrage du process.

⚠️ Le défaut jumeau était déjà corrigé, vingt lignes plus haut, pour le cache
des tiers LLM — avec un commentaire qui le décrit mot pour mot :

    « Without the second check, switching a model in the UI had no runtime
      effect — the cached client kept being served on every agent_node call.
      (Audit C-4, fixed 2026-05-06.) »

Le site jumeau, lui, n'a jamais été corrigé. C'est le même motif que
``_ctx_breakdown`` / ``_fb_state`` : quelqu'un voit la classe de défaut,
corrige un site sur deux, et le second attend qu'on l'emprunte.

Franck a déplacé Nemotron et Gemma entre tiers plusieurs fois le 21/08 ; ses
``make down && make up`` ont masqué le défaut en relançant le process.

2. AUCUN RÉGLAGE SLM N'ÉTAIT DOCUMENTÉ
---------------------------------------
``docker-compose.yml`` passe les quatre variables depuis toujours, et
``.env.example`` — décrit dans le CLAUDE.md comme « la référence de
configuration, annotée » — n'en mentionnait aucune. Franck a passé une
journée sur des réglages qui n'étaient écrits nulle part.

⚠️ Et le plus trompeur des quatre est ``SLM_MODEL``, qui NE CHOISIT PAS le
modèle : ``get_slm()`` rend le tier A configuré dans l'interface, et
``SLM_MODEL`` ne sert que de repli quand aucune instance n'est déclarée. Le
documenter sans le dire aurait été pire que ne pas le documenter.

Run with:  cd backend && python -m pytest tests/test_slm_follows_its_configuration.py -v
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────
# 1 — Le cache suit les DEUX versions
# ─────────────────────────────────────────────────────────────────────

def test_the_slm_cache_follows_the_routing_config():
    """LE pin de l'incident. Sans ça, changer le tier A ne change rien
    jusqu'au prochain redémarrage.

    ⚠️ L'ANCRE A ÉTÉ DURCIE (23/08). Elle cherchait `if _slm_with_tools is not
    None` — une phrase qui s'est mise à apparaître dans un COMMENTAIRE décrivant
    ce même garde, plus haut dans la fonction. `find()` tombait alors sur la
    prose et le pin rougissait alors que l'invariant tenait.

    Un pin qui lit du code source doit s'ancrer sur ce qui ne peut être que du
    code : ici la parenthèse ouvrante de la condition composée. Le faux positif
    coûte moins cher qu'un faux négatif, mais il coûte quand même — c'est ce qui
    apprend à ignorer un test rouge.
    """
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    ancre = "if _slm_with_tools is not None and ("
    assert ancre in src, "le garde de reconstruction a changé de forme"
    bloc = src[src.find(ancre):]
    tete = bloc[:400]

    assert "_slm_cfg_version" in tete, (
        "le cache SLM ne surveille pas la version de configuration des tiers — "
        "changer le modèle du tier A dans l'interface n'aura aucun effet"
    )
    assert "current_version != _slm_version" in tete, (
        "il doit continuer de surveiller AUSSI le registre d'outils"
    )


def test_both_caches_watch_the_same_two_things():
    """L'asymétrie ÉTAIT le défaut : deux caches côte à côte, l'un complet,
    l'autre à moitié. Ce pin les tient alignés."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    for compteur in ("_tier_cfg_version", "_slm_cfg_version"):
        assert compteur in src, f"{compteur} a disparu"
    # Les deux doivent lire la MÊME source de vérité.
    assert src.count("get_tier_config_version()") >= 2, (
        "les deux caches doivent lire la version de configuration ; s'il n'y "
        "a qu'un appel, l'un des deux est reparti en arrière"
    )


def test_a_failed_rebuild_is_not_swallowed():
    """⚠️ Le `except: pass` d'origine avalait l'échec en silence : le SLM
    restait sur l'ancien modèle sans que rien ne le dise — précisément le
    défaut qu'on corrige. Un repli doit se voir (invariant 4)."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src[src.find("if _slm_with_tools is not None"):]
    bloc = bloc[:bloc.find("# ── Route first")]

    assert "logger.warning" in bloc, (
        "un échec de reconstruction du SLM doit se journaliser"
    )
    assert not re.search(r"except Exception:\s*\n\s*pass", bloc), (
        "l'échec est encore avalé sans un mot"
    )


# ─────────────────────────────────────────────────────────────────────
# 2 — Les réglages sont documentés, et honnêtement
# ─────────────────────────────────────────────────────────────────────

def _env_example() -> str:
    return (RACINE / ".env.example").read_text(encoding="utf-8")


def test_every_slm_setting_passed_by_compose_is_documented():
    """La liste de référence n'est pas la mienne : c'est celle que le compose
    passe réellement au conteneur. Un réglage ajouté là sans être documenté
    ici redeviendrait introuvable."""
    compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    passes = set(re.findall(r"- (SLM_[A-Z_]+)=", compose))
    assert passes, "le compose ne passe plus aucun réglage SLM — structure inattendue"

    env = _env_example()
    manquants = sorted(v for v in passes if v not in env)
    assert not manquants, (
        f"réglage(s) passé(s) par le compose mais absent(s) de .env.example : "
        f"{', '.join(manquants)}. Un réglage qui n'est écrit nulle part "
        f"n'existe pas pour l'utilisateur — ça a coûté une journée."
    )


def test_the_misleading_setting_says_it_is_misleading():
    """`SLM_MODEL` ne choisit pas le modèle. Le documenter sans le dire aurait
    été pire que de ne pas le documenter du tout."""
    env = _env_example()
    # Fenêtre ancrée sur l'EN-TÊTE de section, pas sur la première occurrence
    # du nom : celle-ci tombe au milieu de l'avertissement, et la fenêtre
    # coupait justement l'explication qu'on vérifie.
    debut = env.find("Voie rapide (SLM)")
    assert debut != -1, "la section SLM a disparu de .env.example"
    bloc = env[debut:debut + 2500]
    assert "Routage" in bloc, (
        "la doc de SLM_MODEL doit renvoyer vers Réglages → Routage, qui est "
        "l'endroit où le modèle se choisit réellement"
    )
    # Deux formulations acceptées : c'est le SENS qui compte — « ce réglage
    # n'est pas la façon de choisir le modèle ». Épingler un seul mot ferait
    # rougir le pin sur une reformulation innocente.
    assert any(m in bloc.lower() for m in ("repli", "dernier recours")), (
        "elle doit dire que ce réglage n'est qu'un dernier recours"
    )
    assert "vide" in bloc.lower(), (
        "elle doit dire de le laisser VIDE — c'est ce qui autorise la "
        "résolution depuis ce que le serveur sert vraiment"
    )


def test_no_layer_imposes_a_model_the_user_may_not_have():
    """Remarque de Franck (22/08) : « il ne faut pas qu'un modèle soit écrit
    dans le code et imposé — si un utilisateur n'a pas qwen2.5:3b-instruct
    installé, que se passe-t-il ? »

    Il se passait un 404 « model not found » À L'INVOCATION, c'est-à-dire au
    moment où il est trop tard pour l'expliquer. Le compose posait
    `qwen2.5:3b-instruct` dans `environment:`, donc `settings.slm_model`
    n'était JAMAIS vide et ce nom était réclamé aux serveurs locaux quel que
    soit ce que l'utilisateur avait installé.

    Les deux couches doivent laisser le champ VIDE : vide veut dire « non
    déclaré », et c'est ce qui autorise la résolution honnête.
    """
    compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    pose = re.search(r"SLM_MODEL=\$\{SLM_MODEL:-([^}]*)\}", compose)
    assert pose, "la ligne SLM_MODEL du compose a disparu"
    assert pose.group(1) == "", (
        f"le compose impose « {pose.group(1)} » — ce modèle sera réclamé aux "
        f"serveurs locaux même si l'utilisateur ne l'a pas installé"
    )

    from app.config import Settings
    assert Settings.model_fields["slm_model"].default == "", (
        "le code impose un modèle par défaut ; vide = « non déclaré », ce qui "
        "laisse `resolve_local_model` demander au serveur ce qu'il a"
    )


def test_an_undeclared_model_is_taken_from_the_server(monkeypatch):
    """LE pin de la remarque. Sans nom déclaré, on demande au serveur — c'est
    le seul nom dont on soit sûr qu'il existe chez l'utilisateur."""
    from app.services import llm_provider

    monkeypatch.setattr(
        llm_provider, "local_models_available",
        lambda _url: ["nvidia/nemotron-3-nano-4b", "google/gemma-4-12b"],
    )
    reglages = type("S", (), {"slm_model": ""})()
    choisi = llm_provider.resolve_local_model(reglages, "http://x:1234", "constante")

    assert choisi == "nvidia/nemotron-3-nano-4b", (
        "on doit prendre un modèle RÉELLEMENT servi, pas la constante"
    )


def test_a_declared_model_still_wins(monkeypatch):
    """Un réglage explicite reste une déclaration de l'utilisateur : on ne la
    remplace pas par ce qu'on devine, même si le serveur dit autre chose."""
    from app.services import llm_provider

    monkeypatch.setattr(
        llm_provider, "local_models_available", lambda _url: ["autre-chose"],
    )
    reglages = type("S", (), {"slm_model": "mon-modele"})()
    assert llm_provider.resolve_local_model(
        reglages, "http://x:1234", "constante",
    ) == "mon-modele"


def test_falling_back_to_the_constant_is_announced(monkeypatch, caplog):
    """⚠️ La constante subsiste en tout dernier recours — la retirer ferait
    lever là où le dépôt a choisi de rendre un client injoignable (« un Ollama
    éteint peut être démarré dans la minute »).

    Mais elle doit S'ANNONCER : c'est l'invariant 4. Sans ce WARNING, on
    revient exactement au défaut d'origine, un nom inventé en silence.
    """
    import logging

    from app.services import llm_provider

    monkeypatch.setattr(llm_provider, "local_models_available", lambda _url: [])
    reglages = type("S", (), {"slm_model": ""})()

    with caplog.at_level(logging.WARNING):
        choisi = llm_provider.resolve_local_model(reglages, "http://x:1234", "constante")

    assert choisi == "constante"
    assert any("404" in r.message or "SLM_MODEL" in r.message
               for r in caplog.records), (
        "le repli sur une constante doit dire ce qu'il risque et quoi faire"
    )


def test_no_local_provider_hardcodes_its_model_any_more():
    """Les TROIS sites qui imposaient un nom passent par le résolveur.

    C'est la classe de défaut que le gros commentaire de `llm_provider`
    condamne depuis le 26/07 — « chaque fournisseur impose un modèle CODÉ EN
    DUR », incident openai_codex/gpt-5.5. `slm_model` y participait.
    """
    src = (RACINE / "backend" / "app" / "services" / "llm_provider.py").read_text(
        encoding="utf-8"
    )
    assert 'slm_model or "' not in src, (
        "un site impose encore un modèle en dur au lieu de passer par "
        "`resolve_local_model`"
    )
    assert src.count("resolve_local_model(") >= 4, (
        "les trois sites locaux + get_slm doivent tous passer par le résolveur"
    )


def test_the_timeout_documents_what_it_really_costs():
    """Un délai de repli n'est pas un réglage de confort : on l'attend AVANT
    de savoir qu'un repli a eu lieu. Franck l'avait monté à 60 s pour un
    diagnostic ; sans cette note, une valeur de test devient permanente."""
    env = _env_example()
    debut = env.find("SLM_TIMEOUT")
    bloc = env[max(0, debut - 700):debut + 100]
    assert "diagnostic" in bloc.lower(), (
        "la doc du délai doit distinguer une valeur d'usage d'une valeur de test"
    )
