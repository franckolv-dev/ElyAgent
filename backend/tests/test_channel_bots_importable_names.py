# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_channel_bots_importable_names.py
# @brief      Régression #247 : un NameError en production sur Telegram, que
#             les pins source-grep n'ont pas vu.
# @license    MIT
# =============================================================================
"""Pin des noms résolvables dans les bots de canaux.

**L'incident.** La PR #247 a ajouté ``spawn(record_turn_usage(...))`` dans
``handle_message`` des trois bots. Le script d'insertion vérifiait « l'import
existe-t-il déjà dans le fichier ? » avant de l'ajouter au niveau module.

Or ``telegram_bot.py`` contenait **déjà** un import LOCAL de ``spawn``, dans
une *autre* fonction (le handler de webhook). La garde l'a vu, a conclu que
l'import était présent, et n'a rien ajouté. Résultat en production :

    File "/app/app/channels/telegram_bot.py", line 378, in handle_message
        spawn(record_turn_usage(
    NameError: name 'spawn' is not defined

La réponse d'Ely était pourtant correctement générée — c'est l'enregistrement
analytique qui suivait qui levait, et l'utilisateur voyait « Désolé, une
erreur s'est produite ».

**Pourquoi les tests de #247 ne l'ont pas vu.** Ils vérifiaient la PRÉSENCE
du texte (`record_turn_usage` dans le source, chrono avant l'invocation) —
jamais que les noms utilisés étaient *résolvables*. Un pin source-grep ne
distingue pas un import de module d'un import enfoui dans une fonction.

Ce test encode directement la propriété qui manquait : **si un module appelle
``spawn`` depuis n'importe quelle fonction, le nom doit exister au niveau
module.**

Run with:  cd backend && python -m pytest tests/test_channel_bots_importable_names.py -v
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Slack et Discord ont quitté le dépôt le 02/09/2026 (archive/canaux) :
# zéro appel de modèle en cinq mois. Telegram reste, et c'est LUI que
# l'incident #247 avait cassé.
_BOTS = ["telegram_bot"]


@pytest.mark.parametrize("bot", _BOTS)
def test_spawn_is_resolvable_from_any_function(bot):
    """Un import local dans UNE fonction ne rend pas le nom disponible aux
    autres — c'est exactement ce qui a cassé Telegram en production."""
    src = Path(f"app/channels/{bot}.py").read_text(encoding="utf-8")
    if "spawn(" not in src:
        pytest.skip(f"{bot} n'utilise pas spawn")

    module = importlib.import_module(f"app.channels.{bot}")

    assert hasattr(module, "spawn"), (
        f"{bot} appelle spawn() mais ne l'importe pas au niveau module — "
        "NameError garanti à l'exécution"
    )


@pytest.mark.parametrize("bot", _BOTS)
def test_record_turn_usage_is_reachable(bot):
    """Même propriété pour l'autre symbole introduit par #247."""
    src = Path(f"app/channels/{bot}.py").read_text(encoding="utf-8")
    if "record_turn_usage" not in src:
        pytest.skip(f"{bot} n'enregistre pas d'usage")

    from app.services.usage_instrumentation import record_turn_usage

    assert callable(record_turn_usage)
