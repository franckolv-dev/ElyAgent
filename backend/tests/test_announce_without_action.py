# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_announce_without_action.py
# @brief      Bug terrain 2026-06-12 — « Je vais faire une recherche web » +
#             zéro tool_call + fin de tour = réponse morte, puis confabulation
#             (« j'attends les résultats du tool ») sur les tours suivants.
# @license    Elastic License 2.0
# =============================================================================
"""Pins du garde « annonce sans action ».

Cas vécu : « C'est quoi Choose France 2026 ? » routé tier simple → Gemma
LOCAL avec 80 outils bindés (57 s de prompt processing !) → annonce de
recherche en texte, aucun tool_call, silence. Trois défenses posées :

1. ``detect_empty_promise`` reconnaît les annonces d'INVESTIGATION (pas
   seulement les promesses de livraison) → le retry [empty_promise] couvre
   le cas cloud.
2. Escalade au bind : tier SIMPLE local + outils requis → MEDIUM (la règle
   absolue du bench Ministral, appliquée au niveau du bind).
3. H-1 se déclenche aussi sur l'ANNONCE dans la réponse (pas uniquement
   les verbes d'action de la question).

Run with:  cd backend && python -m pytest tests/test_announce_without_action.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tool_call_recovery import detect_empty_promise

_BACKEND = Path(__file__).resolve().parents[1]


# ── 1. Le détecteur reconnaît les annonces d'investigation ───────────────────

class TestSearchIntentDetection:
    @pytest.mark.parametrize("content", [
        # le cas terrain exact (capture 12:39)
        'Je vais faire une recherche web pour obtenir les détails sur "Choose France 2026".',
        # les confabulations des tours suivants (captures 12:42 et 14:58)
        "Je suis en train de chercher les détails sur Choose France 2026. Laisse-moi lire les résultats.",
        "J'ai lancé la recherche web et j'attends les résultats.",
        "Je vais chercher les dernières news sur les petits modèles locaux.",
        "Laisse-moi vérifier les sources disponibles.",
        "Let me search the web for that.",
        "I'm looking into the latest releases.",
        "I'll check the documentation.",
    ])
    def test_investigation_announcements_detected(self, content):
        assert detect_empty_promise(content) is True

    @pytest.mark.parametrize("content", [
        # comptes rendus (pas des promesses) — ne doivent JAMAIS déclencher
        "Voici les résultats de la recherche : Choose France 2026 est un sommet…",
        "D'après mes recherches, le sommet s'est tenu le 1er juin.",
        "La recherche montre 93 milliards d'euros d'investissements.",
        "J'ai trouvé les informations demandées : …",
        # conversation normale
        "Bonjour ! Comment puis-je t'aider aujourd'hui ?",
        "F(12) = 144.",
    ])
    def test_reports_and_chitchat_not_detected(self, content):
        assert detect_empty_promise(content) is False

    def test_delivery_promise_still_detected(self):
        """La famille historique (livraison) reste couverte."""
        assert detect_empty_promise(
            "Je vais télécharger le fichier sur ton Drive."
        ) is True


# ── 2 & 3. Câblage source-level (pattern maison) ─────────────────────────────

def _nodes_src() -> str:
    return (_BACKEND / "app/agent/nodes.py").read_text(encoding="utf-8")


class TestWiring:
    def test_bind_escalation_present(self):
        """SIMPLE local + outils requis → MEDIUM, débrayable par le même
        kill-switch que H-1 (bench de modèles locaux)."""
        src = _nodes_src()
        assert "[bind-escalation]" in src
        block = src.split("[bind-escalation]")[0][-2000:]
        assert "ComplexityTier.SIMPLE" in block
        assert "HALLUCINATION_GUARD_DISABLED" in block

    def test_h1_uses_response_announcement(self):
        """H-1 doit se déclencher sur l'annonce DANS LA RÉPONSE, pas
        seulement sur les verbes d'action de la question."""
        src = _nodes_src()
        assert "_resp_announces" in src
        assert "(_query_has_action or _resp_announces)" in src

    def test_empty_promise_retry_still_wired(self):
        src = _nodes_src()
        assert "detect_empty_promise(_post_content_str)" in src
        assert "[empty_promise]" in src
