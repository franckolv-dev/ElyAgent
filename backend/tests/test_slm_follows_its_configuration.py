# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_follows_its_configuration.py
# @brief      Changer le modèle du tier A doit avoir un effet, et se documenter.
# @license    Elastic License 2.0
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
    jusqu'au prochain redémarrage."""
    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    bloc = src[src.find("if _slm_with_tools is not None"):]
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
    debut = env.find("SLM_MODEL")
    bloc = env[max(0, debut - 1200):debut + 200]
    assert "Routage" in bloc, (
        "la doc de SLM_MODEL doit renvoyer vers Réglages → Routage, qui est "
        "l'endroit où le modèle se choisit réellement"
    )
    assert "repli" in bloc.lower(), (
        "elle doit dire que ce réglage n'est qu'un repli"
    )


def test_the_compose_default_divergence_is_written_down():
    """Le compose pose `qwen2.5:3b-instruct`, le code `qwen2.5:7b-instruct`.
    Le compose gagne. Une divergence tue qui n'est jamais découverte au bon
    moment — ce fichier prévient déjà pour TTS_VOICE, on fait pareil."""
    compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
    depuis_compose = re.search(r"SLM_MODEL=\$\{SLM_MODEL:-([^}]+)\}", compose)
    assert depuis_compose, "le défaut compose de SLM_MODEL a disparu"

    from app.config import Settings
    depuis_code = Settings.model_fields["slm_model"].default

    if depuis_compose.group(1) != depuis_code:
        env = _env_example()
        assert "DIFFÈRE" in env or "diffère" in env, (
            f"le compose impose « {depuis_compose.group(1)} » là où le code "
            f"pose « {depuis_code} », et .env.example ne le signale pas"
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
