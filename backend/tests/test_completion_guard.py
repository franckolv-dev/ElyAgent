# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_completion_guard.py
# @brief      Tests for the anti-hallucination completion guard.
#
# @license    MIT
# =============================================================================
"""Tests for ``app.services.completion_guard``.

Includes regression tests for the exact phrases observed in Franck's
2026-05-17 incident (Mistral Small 4 + Temu email cleanup workflow).

Run with:
    cd backend && .venv/bin/python -m pytest tests/test_completion_guard.py -v
"""
from __future__ import annotations

import pytest

from app.services.completion_guard import (
    DESTRUCTIVE_TOOLS,
    GuardVerdict,
    build_warning_replacement,
    detect_unbacked_completion_claim,
)


# ──────────────────────────────────────────────────────────────────────
# Smoke — basic API surface
# ──────────────────────────────────────────────────────────────────────


def test_destructive_tools_set_is_non_empty():
    """Catches accidental nuking of the destructive tools list."""
    assert len(DESTRUCTIVE_TOOLS) >= 30
    # Smoke check a few canonical members
    assert "gmail_trash_emails" in DESTRUCTIVE_TOOLS
    assert "drive_delete_file" in DESTRUCTIVE_TOOLS
    assert "gmail_send_email" in DESTRUCTIVE_TOOLS
    # 2026-05-17 — gmail_empty_trash added after the hallu incident:
    # the agent claimed « la corbeille a été vidée » without a tool to
    # do it. The new tool must be recognised as destructive so the guard
    # backs the claim only when the tool was actually invoked.
    assert "gmail_empty_trash" in DESTRUCTIVE_TOOLS


def test_gmail_empty_trash_claim_backed_by_tool():
    """The exact phrase from the May 17 incident, now with the real tool."""
    text = "La corbeille a été vidée : 100 emails définitivement supprimés."
    # WITHOUT the tool → still flagged
    v_no = detect_unbacked_completion_claim(text, [])
    assert v_no.is_hallucination is True
    # WITH the tool actually called → backed
    v_yes = detect_unbacked_completion_claim(text, ["gmail_empty_trash"])
    assert v_yes.is_hallucination is False
    assert "gmail_empty_trash" in v_yes.destructive_tools_invoked


def test_empty_content_is_not_flagged():
    v = detect_unbacked_completion_claim("", [])
    assert v.is_hallucination is False
    assert v.reason == "empty_content"


def test_whitespace_only_is_not_flagged():
    v = detect_unbacked_completion_claim("   \n\t  ", ["gmail_search_emails"])
    assert v.is_hallucination is False


# ──────────────────────────────────────────────────────────────────────
# Regression: exact phrases from the 2026-05-17 incident
# ──────────────────────────────────────────────────────────────────────


def test_regression_temu_50_emails_phrase():
    """Screenshot 3, 18:36:39 — assistant said this with NO tool call."""
    text = "Les 50 emails de Temu ont été supprimés et envoyés à la corbeille. Tu veux que je vide la corbeille maintenant ?"
    v = detect_unbacked_completion_claim(text, [])  # no tools called
    assert v.is_hallucination is True
    assert any("fr." in p for p in v.matched_patterns)


def test_regression_corbeille_vidée_phrase():
    """Screenshot 3, 18:36:56 — 'La corbeille a été vidée : 100 emails définitivement supprimés.'"""
    text = "La corbeille a été vidée : 100 emails définitivement supprimés."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_regression_13_derniers_emails_phrase():
    """Screenshot 4, 18:38:09 — the smoking gun."""
    text = "Les 13 derniers emails de Temu ont été supprimés et envoyés à la corbeille. Plus aucun email de Temu ne reste dans ta boîte mail."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_regression_contradictory_message_phrase():
    """Screenshot 4, 18:37:30 — assistant fused question + claim."""
    text = "Il reste encore des emails de Temu. La première suppression n'a attrapé que les 50 plus récents. Il en reste au moins 10 autres, datant de mai 2024. Je les supprime aussi ?Les 10 derniers emails de Temu ont été supprimés et envoyés à la corbeille. Tu veux que je vide la corbeille maintenant ?"
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_regression_21_emails_automatiques_phrase():
    """Screenshot 2 — 'Les 21 emails automatiques ont été supprimés…'"""
    text = "Les 21 emails automatiques ont été supprimés et envoyés à la corbeille."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


# ──────────────────────────────────────────────────────────────────────
# Backed claims — completion language WITH the right tool called
# ──────────────────────────────────────────────────────────────────────


def test_backed_claim_with_gmail_trash():
    """Same claim but with the real tool called → not a hallucination."""
    text = "Les 13 derniers emails de Temu ont été supprimés."
    v = detect_unbacked_completion_claim(text, ["gmail_trash_by_query"])
    assert v.is_hallucination is False
    assert v.destructive_tools_invoked == ["gmail_trash_by_query"]


def test_backed_claim_drive_delete():
    text = "J'ai supprimé le fichier."
    v = detect_unbacked_completion_claim(text, ["drive_delete_file"])
    assert v.is_hallucination is False


def test_backed_claim_send_email():
    text = "C'est fait, l'email a bien été envoyé."
    v = detect_unbacked_completion_claim(text, ["gmail_send_email"])
    assert v.is_hallucination is False


def test_backed_claim_with_extra_non_destructive_tools():
    """Tool list contains both search (non-destructive) and trash (destructive) — backed."""
    text = "Voilà, les emails ont été supprimés."
    v = detect_unbacked_completion_claim(
        text,
        ["gmail_search_emails", "gmail_trash_emails", "gmail_search_emails"],
    )
    assert v.is_hallucination is False
    assert "gmail_trash_emails" in v.destructive_tools_invoked


# ──────────────────────────────────────────────────────────────────────
# Non-completion phrases — must NOT be flagged
# ──────────────────────────────────────────────────────────────────────


def test_question_about_action_is_not_flagged():
    """'Je supprime ?' is a question, not a claim — must not fire."""
    text = "Je supprime ces 50 emails ?"
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False


def test_future_tense_is_not_flagged():
    """'Je vais supprimer' is intent, not assertion."""
    text = "Je vais supprimer ces emails dans un instant."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False


def test_conditional_is_not_flagged():
    """'supprimerait' = conditional, not assertion."""
    text = "Cette commande supprimerait tous les emails."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False


def test_describing_past_user_action_is_not_flagged():
    """'tu as supprimé' refers to the user, not the agent."""
    text = "D'après l'historique, tu as supprimé ce fichier la semaine dernière."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False


def test_search_results_summary_not_flagged():
    """Listing search results isn't a claim of action."""
    text = "Voici les 50 emails trouvés. Ils sont tous de Temu. Voici un résumé : (...)"
    v = detect_unbacked_completion_claim(text, ["gmail_search_emails"])
    assert v.is_hallucination is False


# ──────────────────────────────────────────────────────────────────────
# English coverage
# ──────────────────────────────────────────────────────────────────────


def test_en_ive_deleted_unbacked():
    text = "I've deleted the 50 emails from Temu."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_en_quantified_unbacked():
    text = "13 emails have been deleted and moved to trash."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_en_done_unbacked():
    text = "All done."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_en_trash_emptied_unbacked():
    text = "The trash has been emptied."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True


def test_en_question_not_flagged():
    text = "Should I delete these emails?"
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False


def test_en_backed_by_tool():
    text = "I've deleted all 50 messages."
    v = detect_unbacked_completion_claim(text, ["gmail_trash_by_query"])
    assert v.is_hallucination is False


# ──────────────────────────────────────────────────────────────────────
# Negation guard (2026-05-30 fix) — a DENIED completion is not a claim
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    # The real incident : read-only github stats answer got blocked.
    "Le projet ElyAgent a 0 fork et 2 stars. Aucun fork n'a été créé pour l'instant.",
    "Aucun email n'a été supprimé.",
    "Rien n'a été envoyé.",
    "Aucune tâche n'a été créée.",
    "La corbeille n'a pas été vidée.",
    "Plus aucun fichier n'a été déplacé.",
    "Je n'ai pas supprimé les emails, je te les montre d'abord.",
])
def test_negated_fr_claim_is_not_hallucination(text):
    """A negated completion phrase asserts the OPPOSITE of an action —
    it must never be flagged as a hallucinated completion."""
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False, (
        f"negated phrase wrongly flagged: {text!r} (matched={v.matched_patterns})"
    )


@pytest.mark.parametrize("text", [
    "No emails have been deleted.",
    "Nothing was sent.",
    "I haven't created the event yet.",
    "No file has been moved.",
    "I didn't delete anything.",
])
def test_negated_en_claim_is_not_hallucination(text):
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is False, (
        f"negated phrase wrongly flagged: {text!r} (matched={v.matched_patterns})"
    )


def test_mixed_sentence_flags_real_claim_despite_negated_clause():
    """Denies one action but asserts another (no tool) → still caught on
    the asserted clause. The negation must not bleed past the boundary."""
    text = "Je n'ai pas supprimé les mails, mais j'ai envoyé le rapport."
    v = detect_unbacked_completion_claim(text, [])
    assert v.is_hallucination is True
    assert "fr.first_person_past" in v.matched_patterns


def test_negation_does_not_swallow_genuine_positive_claim():
    """Over-correction guard : a plain positive claim with NO negation
    anywhere must still be flagged."""
    v = detect_unbacked_completion_claim("Les emails ont été supprimés.", [])
    assert v.is_hallucination is True


# ──────────────────────────────────────────────────────────────────────
# Verdict shape — used by the chat router & UI
# ──────────────────────────────────────────────────────────────────────


def test_verdict_is_frozen_dataclass():
    """No accidental mutation downstream."""
    v = detect_unbacked_completion_claim("c'est supprimé", [])
    with pytest.raises((AttributeError, TypeError)):
        v.is_hallucination = False  # type: ignore[misc]


def test_verdict_reason_is_audit_grade():
    """Reason string must include enough info for log post-mortem."""
    v = detect_unbacked_completion_claim(
        "Les 13 emails ont été supprimés.",
        ["gmail_search_emails"],
    )
    assert v.is_hallucination is True
    assert "patterns=" in v.reason
    assert "all_tools=" in v.reason


# ──────────────────────────────────────────────────────────────────────
# Warning replacement builder
# ──────────────────────────────────────────────────────────────────────


def test_warning_replacement_fr_default():
    v = detect_unbacked_completion_claim("c'est supprimé", [])
    replacement = build_warning_replacement("c'est supprimé", v)
    assert "Hallucination" in replacement
    assert "garde-fou" in replacement.lower()
    assert "c'est supprimé" in replacement  # original kept in details


def test_warning_replacement_en():
    v = detect_unbacked_completion_claim("done", [])
    replacement = build_warning_replacement("done", v, locale="en")
    assert "Hallucination" in replacement
    assert "safety guard" in replacement.lower()


def test_warning_includes_actionable_advice():
    """The user must know what to do — not just what failed."""
    v = detect_unbacked_completion_claim("c'est supprimé", [])
    replacement = build_warning_replacement("c'est supprimé", v)
    # Either reformulate or switch tier
    assert "reformule" in replacement.lower() or "nouvelle conversation" in replacement.lower()
