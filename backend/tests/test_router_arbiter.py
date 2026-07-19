# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_router_arbiter.py
# @brief      C3d-5 — arbitre local (passe 2 du routeur) : parse tolérant,
#             trace, et boucle d'apprentissage vers le routeur rapide.
# @license    Elastic License 2.0
# =============================================================================
"""C3d-5 — dernier lot du chantier C3d.

La passe 2 du routeur (LLM tier SIMPLE, échéance 10 s posée par C3d-2) était
fragile et muette : parse par égalité STRICTE (un modèle local qui enrobe sa
réponse → arbitrage jeté → general), aucune trace structurée, et sa décision
n'apprenait rien au routeur rapide (propose_keyword existait SANS appelant —
un funnel de plus sans déclencheur).

Run with:  cd backend && python -m pytest tests/test_router_arbiter.py -v
"""
from __future__ import annotations

from pathlib import Path

from app.agent.supervisor import _parse_router_domain, _routing_keyword_candidate

_REPO = Path(__file__).resolve().parents[1]


# ── Parse tolérant ──────────────────────────────────────────────────────────


def test_exact_domain_passes_through():
    assert _parse_router_domain("workspace") == "workspace"
    assert _parse_router_domain("  Research \n") == "research"
    assert _parse_router_domain("general") == "general"


def test_padded_answer_is_recovered():
    """Le cas réel des petits modèles locaux : réponse enrobée."""
    assert _parse_router_domain("La catégorie est workspace.") == "workspace"
    assert _parse_router_domain("Réponse : desktop (fichiers locaux)") == "desktop"


def test_specialist_wins_over_general_substring():
    """« general » est un substring fréquent des explications — un
    spécialiste présent dans la sortie doit gagner."""
    assert _parse_router_domain(
        "workspace serait mieux que general ici"
    ) == "workspace"


def test_garbage_and_empty_fall_back_to_general():
    assert _parse_router_domain("je ne sais pas") == "general"
    assert _parse_router_domain("") == "general"
    assert _parse_router_domain(None) == "general"  # type: ignore[arg-type]


# ── Candidate mot-clé (apprentissage prudent) ───────────────────────────────


def test_short_query_becomes_keyword_candidate():
    assert _routing_keyword_candidate("Vérifie mes mails") == "vérifie mes mails"
    assert _routing_keyword_candidate("météo") == "météo"


def test_long_or_empty_query_learns_nothing():
    assert _routing_keyword_candidate(
        "peux tu chercher sur le web les annonces de la semaine et les résumer"
    ) is None
    assert _routing_keyword_candidate("") is None
    assert _routing_keyword_candidate("   ") is None


# ── Pins de câblage ─────────────────────────────────────────────────────────


def test_pass2_uses_tolerant_parse_and_traces():
    src = (_REPO / "app/agent/supervisor.py").read_text(encoding="utf-8")
    assert src.count("_parse_router_domain(") >= 2, (  # def + call site
        "La passe 2 doit parser la sortie de l'arbitre avec le parse tolérant."
    )
    assert 'arbiter="llm-pass2"' in src, (
        "L'arbitrage LLM doit émettre sa décision dans la trace de routage."
    )


def test_pass2_feeds_routing_learning():
    src = (_REPO / "app/agent/supervisor.py").read_text(encoding="utf-8")
    assert "propose_keyword" in src and "router-llm-pass2" in src, (
        "La décision de l'arbitre doit proposer un mot-clé au routeur rapide "
        "(fire-and-forget, seuil de confiance côté routing_learning)."
    )
