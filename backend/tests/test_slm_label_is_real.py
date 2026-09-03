# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_slm_label_is_real.py
# @brief      La voie SLM doit nommer le modèle qui a répondu, pas un réglage.
# @license    MIT
# =============================================================================
"""Le 06/08, Franck installe Nemotron 3 nano 4B dans LM Studio et demande :

    « quand je lui demande quelque chose dans Ely, cela m'affiche que c'est
      GPT 5.6 sol qui a été utilisé alors que j'ai l'impression, dans
      LM Studio, que c'est Nemotron qui a travaillé »

En cherchant, on trouve que les deux voies ne s'étiquettent pas avec la même
honnêteté :

    # voie cloud — introspection de l'objet réel
    _p, _m = describe_llm(_base_llm)
    model_used = f"llm:{_p}/{_m}"

    # voie SLM — un réglage statique
    model_used = f"slm:{settings.slm_model}"

Or ``get_slm()`` ne lit PAS ``settings.slm_model`` : il rend
``get_llm_for_tier(ComplexityTier.SIMPLE)``, le tier A configuré dans l'UI.
``SLM_MODEL`` est un reliquat du chemin Ollama que plus rien ne raccorde au
modèle servi.

⚠️ **Le pire n'était pas l'étiquette.** Le même réglage alimentait
``fit_messages_to_context(model=…)``, une table de fenêtres de contexte. Un nom
qui ne correspond à rien y retombe sur le défaut de 8 192 tokens : l'historique
d'un modèle qui en tenait bien plus était tronqué en silence. C'est mot pour
mot la classe de défaut que ``config_reality`` traque depuis le 26/07 — une
correspondance dont le repli est *plausible*, donc que personne ne vérifie.

Run with:  cd backend && python -m pytest tests/test_slm_label_is_real.py -v
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeSettings:
    slm_model = "reglage-statique-obsolete"


def test_the_name_comes_from_the_model_not_the_setting(monkeypatch):
    """LE pin de l'incident : c'est l'objet qui parle, pas la configuration."""
    from app.agent import nodes

    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm",
        lambda llm: ("lm_studio", "nemotron-3-nano-4b"),
    )
    nom = nodes._slm_real_name(SimpleNamespace(), _FakeSettings())
    assert nom == "nemotron-3-nano-4b", (
        f"vu {nom!r} — l'étiquette doit venir du modèle qui a répondu"
    )
    assert nom != _FakeSettings.slm_model


def test_it_falls_back_to_the_setting_when_introspection_fails(monkeypatch):
    """Un repli reste nécessaire — mais il vaut « au mieux », pas « vrai ».

    Sans lui, une introspection cassée ferait tomber le tour entier pour une
    question de nom d'affichage.
    """
    from app.agent import nodes

    def _boom(_llm):
        raise RuntimeError("introspection cassée")

    monkeypatch.setattr("app.services.llm_provider.describe_llm", _boom)
    assert nodes._slm_real_name(SimpleNamespace(), _FakeSettings()) == (
        "reglage-statique-obsolete"
    )


def test_an_unknown_model_falls_back_rather_than_naming_a_question_mark(monkeypatch):
    """``describe_llm`` rend « ? » quand il ne reconnaît pas l'objet.

    Afficher « slm:? » serait pire que le réglage : ça ne nomme rien ET ça
    n'oriente vers aucune configuration à corriger.
    """
    from app.agent import nodes

    monkeypatch.setattr(
        "app.services.llm_provider.describe_llm", lambda llm: ("unknown", "?"),
    )
    assert nodes._slm_real_name(SimpleNamespace(), _FakeSettings()) == (
        "reglage-statique-obsolete"
    )


def test_the_slm_path_no_longer_reads_the_static_setting_for_its_label():
    """Garde structurel : les deux usages qui comptaient sont débranchés.

    L'étiquette ET la fenêtre de contexte lisaient `settings.slm_model`. Ce
    pin échoue si l'un des deux y revient — c'est la seule façon d'empêcher la
    régression, le défaut étant invisible tant qu'on ne compare pas l'écran à
    LM Studio.
    """
    import inspect

    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert 'f"slm:{settings.slm_model}"' not in src, (
        "l'étiquette doit venir de `_slm_real_name`, pas du réglage statique"
    )
    assert "model=settings.slm_model" not in src, (
        "la fenêtre de contexte doit être cherchée sur le VRAI modèle : un nom "
        "fantôme y retombe sur 8 192 tokens et tronque l'historique"
    )
    assert "_slm_real_name" in src


def test_the_unbound_model_is_kept_for_introspection():
    """`bind_tools` rend un RunnableBinding qui n'expose pas `.model`.

    Décrire l'objet bindé rendrait « ? » à tous les coups, et le repli
    ramènerait le réglage statique — le correctif serait vert et inopérant.
    La voie cloud garde déjà `_base_llm` pour la même raison.
    """
    import inspect

    from app.agent import nodes

    src = inspect.getsource(nodes.create_agent_node)
    assert "_slm_base = get_slm()" in src or "_slm_base = nonlocal_base" in src, (
        "le modèle NON bindé doit être conservé pour l'introspection"
    )
    assert "_slm_real_name(_slm_base" in src, (
        "c'est le modèle non bindé qu'il faut décrire, pas `_slm_with_tools`"
    )
