# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_capability_manifest.py
# @brief      P1/J1 — CapabilityManifest : dérivation, surcharges, invariant HITL.
# @license    Elastic License 2.0
# =============================================================================
"""Le manifeste unifie la sécurité sans la changer.

Invariant central : pour tout outil connu, la décision HITL pilotée par le
manifeste est IDENTIQUE à la règle historique
``(tool in ALWAYS_CRITICAL_TOOLS) or is_critical(desc)`` — à l'unique
exception, délibérée et documentée, des lectures sûres (``web_search``) que le
manifeste marque ``approval=never`` (correction d'un faux positif de mots-clés).
"""
from __future__ import annotations

import pytest

from app.services.capability_manifest import (
    Approval,
    Effect,
    Idempotency,
    _always_effects,
    get_manifest,
    manifest_requires_hitl,
)
from app.services.security_filter import ALWAYS_CRITICAL_TOOLS


# is_critical déterministe injecté : l'invariant ne doit pas dépendre de la
# liste de mots-clés réelle (les deux côtés utilisent la MÊME fonction).
def _fake_is_critical(desc: str) -> bool:
    return "TRIGGER" in desc


def _legacy(tool: str, desc: str) -> bool:
    return (tool in ALWAYS_CRITICAL_TOOLS) or _fake_is_critical(desc)


# Échantillon : critiques (dans ALWAYS_CRITICAL) + non-critiques + surcharges
# ALWAYS. web_search est traité à part (refinement délibéré).
_ALWAYS_SAMPLE = ["ssh_execute", "drive_delete_file", "gmail_send_email",
                  "whatsapp_send", "calendar_delete_event"]
_NONCRIT_SAMPLE = ["calendar_list_events", "gmail_list_emails",
                   "drive_search", "notes_create", "mcp__github__search"]


@pytest.mark.parametrize("tool", _ALWAYS_SAMPLE + _NONCRIT_SAMPLE)
@pytest.mark.parametrize("desc", ["action anodine", "TRIGGER action sensible"])
def test_hitl_decision_matches_legacy_for_known_tools(tool, desc):
    assert manifest_requires_hitl(tool, desc, _fake_is_critical) == _legacy(tool, desc)


def test_web_search_is_deliberately_never_gated():
    # Refinement assumé : une recherche est une lecture sûre, jamais HITL —
    # même si la requête contient un mot-clé que is_critical aurait capté.
    assert manifest_requires_hitl("web_search", "action anodine", _fake_is_critical) is False
    assert manifest_requires_hitl("web_search", "TRIGGER supprimer tout", _fake_is_critical) is False


# ── Surcharges explicites ────────────────────────────────────────────────


def test_override_drive_delete_file():
    m = get_manifest("drive_delete_file")
    assert m.derived is False
    assert m.approval is Approval.ALWAYS
    assert Effect.DESTRUCTIVE in m.effects
    assert m.compensation == "restore_from_trash"
    assert m.permissions == ["google.drive.write"]


def test_override_gmail_send_email():
    m = get_manifest("gmail_send_email")
    assert m.approval is Approval.ALWAYS
    assert Effect.COMMS_EXTERNAL in m.effects
    assert m.idempotency is Idempotency.NONE   # ré-envoyer = nuisible
    assert m.compensation is None


def test_override_web_search_read():
    m = get_manifest("web_search")
    assert m.approval is Approval.NEVER
    assert m.effects == [Effect.READ]
    assert m.idempotency is Idempotency.SUPPORTED


# ── Dérivation automatique ───────────────────────────────────────────────


def test_derived_always_for_critical_tool():
    m = get_manifest("ssh_execute")
    assert m.derived is True
    assert m.approval is Approval.ALWAYS


def test_derived_risk_based_for_plain_tool():
    m = get_manifest("calendar_list_events")
    assert m.derived is True
    assert m.approval is Approval.RISK_BASED


def test_derived_mcp_origin_and_runtime():
    m = get_manifest("mcp__github__create_issue")
    assert m.origin == "mcp"
    assert m.runtime == "remote"


def test_always_effects_hints():
    assert Effect.DESTRUCTIVE in _always_effects("drive_delete_file")
    assert Effect.COMMS_EXTERNAL in _always_effects("gmail_send_email")
    # un mutateur non destructif / non comms reste external_mutation seul
    assert _always_effects("calendar_create_event") == [Effect.EXTERNAL_MUTATION]


def test_real_is_critical_callable_integration():
    from app.services.security_filter import SecurityFilter
    sf = SecurityFilter()
    # outil critique → toujours True ; lecture anodine → False
    assert manifest_requires_hitl("ssh_execute", "Outil: ssh_execute", sf.is_critical) is True
    assert manifest_requires_hitl("calendar_list_events",
                                  "Outil: calendar_list_events | Arguments: {}", sf.is_critical) is False
