# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_kimi_k3_window.py
# @brief      Kimi passe en v3, avec sa vraie fenêtre d'un million de tokens.
# @license    Elastic License 2.0
# =============================================================================
"""Pin de la fenêtre de Kimi K3.

Franck migre l'API Moonshot de ``kimi-k2.6`` vers ``kimi-k3`` (nom officiel
dans leur documentation). Sa fenêtre annoncée est de **1 000 000 de tokens** —
là où mes valeurs prudentes du 26/07 plaçaient ``kimi-k2`` à 32 768 faute de
chiffre fiable.

L'écart illustre le coût de la prudence : sur un modèle à 1 M, tronquer à
32 768 jette **97 %** du contexte disponible. La valeur prudente protège d'un
rejet par le fournisseur, mais elle n'est bonne que tant qu'on ignore la vraie.
Dès qu'on la connaît, il faut la mettre.

L'entrée ``kimi-k2`` est conservée : une instance restée en 2.x continuerait
de résoudre plutôt que de retomber sur 8 192.

Run with:  cd backend && python -m pytest tests/test_kimi_k3_window.py -v
"""
from __future__ import annotations


def test_kimi_k3_declares_its_real_window():
    from app.services.context_manager import get_context_window

    assert get_context_window("kimi-k3") == 1_000_000


def test_the_previous_generation_still_resolves():
    """Ne pas casser une instance restée en 2.x pendant la bascule."""
    from app.services.context_manager import _CONTEXT_WINDOWS, get_context_window

    assert get_context_window("kimi-k2.6") != _CONTEXT_WINDOWS["_default"]
