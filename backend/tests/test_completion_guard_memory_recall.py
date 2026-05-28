# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_completion_guard_memory_recall.py
# @brief      2026-05-23 — pin the memory-recall question bypass in
#             completion_guard so the assistant's honest reply to "qu'as-tu
#             enregistré sur X ?" doesn't trigger the false positive.
# @license    Elastic License 2.0
# =============================================================================
"""Regression for completion_guard false positive on memory-recall questions.

Reproduces the bug Franck observed on 2026-05-23 (DeepSeek v4-pro, fresh
conversation) :

  User : "Qu'est ce que tu as enregistré concernant mes commandes amazon ?"
  Ely  : "Voici ce que j'ai retrouvé concernant tes commandes Amazon : …"
  → completion_guard.fr.first_person_past fires (matches "j'ai retrouvé")
  → response is replaced by a warning message
  → user loses access to facts that were actually correctly recalled
    from the auto-injected user_profile in the system prompt

Fix : `is_memory_recall_question(user_message)` whitelist. When the user
explicitly asks the assistant to recite memory, the guard bypasses for
that turn.

Tests pin :
  - The whitelist hits exactly the recall patterns + the FR exact phrase
    Franck used today
  - The whitelist does NOT hit ordinary destructive requests
    ("supprime mes mails")
  - `detect_unbacked_completion_claim` returns no hallucination when
    user_message is a recall question, even with past-tense reply content
  - Without the user_message kwarg (legacy callers), behaviour is
    unchanged (backward compat)
"""
from __future__ import annotations

import pytest

from app.services.completion_guard import (
    detect_unbacked_completion_claim,
    is_memory_recall_question,
)


# ── is_memory_recall_question — positive cases ────────────────────────


@pytest.mark.parametrize("text", [
    # The exact phrase Franck typed today
    "Qu'est ce que tu as enregistré concernant mes commandes amazon ?",
    # Variations
    "qu'as-tu enregistré sur mon compte amazon ?",
    "qu'as-tu noté à propos de ma femme ?",
    "qu'as-tu retenu de notre dernière conversation ?",
    "qu'as-tu mémorisé sur mes préférences ?",
    "qu'as-tu stocké comme infos sur Doctolib ?",
    "qu'as-tu gardé en mémoire concernant le projet ?",
    "Te souviens-tu de mon rendez-vous chez le médecin ?",
    "tu te souviens de ce qu'on s'est dit hier ?",
    "te rappelles-tu de l'URL Doctolib ?",
    "tu te rappelles de mon login Amazon ?",
    "Que sais-tu sur mon agenda ?",
    "que connais-tu de mes habitudes ?",
    "qu'as-tu en mémoire sur ma famille ?",
    "qu'est-ce que tu sais sur ma profession ?",
    "qu'est-ce que tu as retenu sur le projet ELY ?",
    "Liste-moi ce que tu as noté sur mon compte amazon",
    "montre-moi ce que tu as enregistré comme préférences",
    "donne-moi tout ce que tu sais sur mes contacts",
    "rappelle-moi mes préférences",
])
def test_french_recall_questions_are_recognised(text: str) -> None:
    assert is_memory_recall_question(text), f"Should detect: {text!r}"


@pytest.mark.parametrize("text", [
    "what have you saved about my amazon account?",
    "What did you note about my schedule?",
    "Do you remember the Doctolib URL?",
    "Do you recall what we discussed yesterday?",
    "Do you know about my preferences?",
    "Tell me what you know about my family.",
    "show me what you have noted",
    "list everything you remember about ELY",
])
def test_english_recall_questions_are_recognised(text: str) -> None:
    assert is_memory_recall_question(text), f"Should detect: {text!r}"


# ── is_memory_recall_question — negative cases (no false positives) ──


@pytest.mark.parametrize("text", [
    # Destructive requests — these MUST keep triggering the guard
    "Supprime tous mes mails SHEIN",
    "Envoie un mail à Franck",
    "Trash all my newsletter emails",
    "delete the file foo.txt",
    # Generic past-tense questions — not addressed as recall
    "Le rendez-vous a-t-il eu lieu hier ?",
    "Quelle est la météo demain ?",
    "Combien coûte mon abonnement Doctolib ?",
    # Empty / blank
    "",
    "   ",
    "?",
    # Generic questions about facts in the world (not memory)
    "Quelle est la capitale de la France ?",
    "What is the weather today?",
])
def test_non_recall_questions_are_not_flagged(text: str) -> None:
    assert not is_memory_recall_question(text), (
        f"Should NOT detect as recall: {text!r}"
    )


# ── Full guard with bypass ────────────────────────────────────────────


def test_recall_question_bypasses_guard_on_past_tense_reply() -> None:
    """The exact bug Franck observed : user asks recall, assistant answers
    with past-tense ("j'ai retrouvé…"), guard should NOT fire."""
    user = "Qu'est ce que tu as enregistré concernant mes commandes amazon ?"
    reply = (
        "Voici ce que j'ai retrouvé concernant tes commandes Amazon : "
        "Tu as demandé une vérification de tes commandes Amazon, ce qui "
        "a été effectué via analyse d'image. J'ai noté les livraisons "
        "suivantes : UNCIN (17/05), PRONTOSAN (18/05), MEDiBrace (21/05)."
    )

    verdict = detect_unbacked_completion_claim(
        reply, tools_invoked_in_turn=[], user_message=user,
    )
    assert verdict.is_hallucination is False
    assert verdict.reason == "memory_recall_question_bypass"


def test_recall_bypass_does_not_apply_when_user_asked_destructive() -> None:
    """If the user asked for an action ("supprime"), the guard MUST fire
    on a past-tense reply without tool calls — even on a phrase that
    looks like memory recall (e.g. assistant adding "j'ai noté que…")."""
    user = "Supprime tous mes mails SHEIN, s'il te plaît."
    reply = "C'est fait, j'ai supprimé tous les mails SHEIN."

    verdict = detect_unbacked_completion_claim(
        reply, tools_invoked_in_turn=[], user_message=user,
    )
    assert verdict.is_hallucination is True
    assert "completion_claim" in verdict.reason


def test_guard_remains_active_without_user_message_kwarg() -> None:
    """Backward compat : callers that don't pass `user_message` (legacy
    code paths) keep the original strict behaviour."""
    reply = "C'est fait, j'ai supprimé les 12 mails newsletter."
    verdict = detect_unbacked_completion_claim(
        reply, tools_invoked_in_turn=[],
    )
    # Without user_message context, guard treats as hallucination
    assert verdict.is_hallucination is True


def test_recall_bypass_when_no_completion_claim_in_reply() -> None:
    """Even before the new bypass, a reply with no completion claim
    wouldn't fire. The bypass should be a no-op in that case (reason
    differs but is_hallucination stays False)."""
    user = "Qu'as-tu enregistré sur moi ?"
    reply = "Je n'ai rien d'enregistré sur toi pour le moment."

    verdict = detect_unbacked_completion_claim(
        reply, tools_invoked_in_turn=[], user_message=user,
    )
    assert verdict.is_hallucination is False
    # The bypass fires before the pattern scan, so reason is the bypass
    assert verdict.reason == "memory_recall_question_bypass"


def test_chat_router_passes_user_message_to_guard() -> None:
    """Hermetic source-grep guard : the chat.py call site must include
    `user_message=user_content` so the bypass actually fires in prod."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "chat.py"
    ).read_text(encoding="utf-8")
    # Must call the guard with user_message
    assert "user_message=user_content" in src, (
        "chat.py must pass `user_message=user_content` to "
        "detect_unbacked_completion_claim — otherwise the new bypass "
        "never fires in production."
    )
