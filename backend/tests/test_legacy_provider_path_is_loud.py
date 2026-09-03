# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_legacy_provider_path_is_loud.py
# @brief      Le chemin par NOM de fournisseur impose un modèle en dur —
#             il doit le dire.
# @license    MIT
# =============================================================================
"""Pins du chemin historique de résolution par nom de fournisseur.

**Ce qu'il a coûté.** La configuration des tiers de Franck référençait
``"openai_codex"`` — le NOM du fournisseur — en tête de medium, complex et
image. Ce nom emprunte le chemin historique, qui code le modèle en dur :

    if provider_id == "openai_codex":
        return _make_openai_codex(model="gpt-5.5", …)

Son instance ``gpt-5.6-terra`` n'était donc **jamais atteinte** pour ces trois
tiers. Et ``gpt-5.5`` n'ayant aucun tarif, ``estimate_cost`` lui appliquait
**4,00 USD par million inventés**, sur la majorité de son trafic — alors que
le modèle réellement voulu est consommé au forfait et coûte 0.

Rien n'a signalé quoi que ce soit pendant des mois : le chemin fonctionnait,
il produisait un modèle valide, il était simplement **le mauvais**.

**Ce que ce lot fait, et ne fait pas.**

- Il ne SUPPRIME pas le chemin : des configurations légitimes référencent un
  fournisseur par son nom sans avoir créé d'instance.
- Il ne SUBSTITUE pas automatiquement l'instance : dès qu'un fournisseur en a
  plusieurs (Franck a deux DeepSeek, trois LM Studio), la machine devrait
  deviner laquelle. C'est précisément l'ambiguïté qu'elle ne doit pas trancher.
- Il le rend **bruyant** : chaque recours à un défaut codé en dur s'annonce,
  nomme le modèle imposé, et dit quoi faire.

Le contrôle de réalité (#269) attrape la CONSÉQUENCE côté résolveur ; ce lot
annonce la CAUSE au moment de la décision.

Run with:  cd backend && python -m pytest tests/test_legacy_provider_path_is_loud.py -v
"""
from __future__ import annotations

import logging


def test_every_legacy_provider_declares_its_hardcoded_model():
    """La table rend visible ce qui était éparpillé dans une cascade de `if` :
    on voit d'un coup d'œil quels modèles sont imposés sans configuration."""
    from app.services.llm_provider import LEGACY_DEFAULT_MODELS

    for provider in ("openai_codex", "anthropic", "deepseek", "mistral", "gemini"):
        assert provider in LEGACY_DEFAULT_MODELS, (
            f"{provider} impose un modèle en dur sans le déclarer"
        )


def test_using_a_legacy_default_is_announced(caplog):
    """LE test du lot : le silence est ce qui a coûté cher."""
    from app.services.llm_provider import _LEGACY_WARNED, warn_legacy_default

    _LEGACY_WARNED.clear()
    with caplog.at_level(logging.WARNING):
        warn_legacy_default("openai_codex", "gpt-5.5")

    assert "openai_codex" in caplog.text
    assert "gpt-5.5" in caplog.text


def test_the_warning_says_what_to_do(caplog):
    """Un avertissement qui constate sans indiquer la sortie se lit une fois
    puis se subit — comme le « Unknown model » que personne n'a jamais vu."""
    from app.services.llm_provider import _LEGACY_WARNED, warn_legacy_default

    _LEGACY_WARNED.clear()
    with caplog.at_level(logging.WARNING):
        warn_legacy_default("openai_codex", "gpt-5.5")

    assert "instance" in caplog.text.lower()


def test_the_warning_does_not_repeat_on_every_call(caplog):
    """Le résolveur est appelé à chaque tour : répéter noierait le signal,
    et un avertissement noyé ne vaut pas mieux que pas d'avertissement."""
    from app.services.llm_provider import _LEGACY_WARNED, warn_legacy_default

    _LEGACY_WARNED.clear()
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            warn_legacy_default("anthropic", "claude-sonnet-4-6")

    assert caplog.text.count("claude-sonnet-4-6") == 1


def test_the_hardcoded_branches_call_the_warning():
    """Pin d'intégration : la table et l'avertissement ne servent à rien s'ils
    ne sont pas branchés là où la décision se prend."""
    from pathlib import Path

    src = Path("app/services/llm_provider.py").read_text(encoding="utf-8")

    assert src.count("warn_legacy_default(") >= 4, (
        "l'avertissement ne couvre pas assez de branches historiques"
    )
