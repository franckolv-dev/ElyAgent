# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_action_plan.py
# @brief      P1/J2 — ActionPlan canonique + empreinte (« l'approuvé == l'exécuté »).
# @license    MIT
# =============================================================================
from __future__ import annotations

import re

from app.services.action_plan import (
    ActionPlan,
    build_action_plan,
    fingerprint,
    verify,
)


def _plan(**kw):
    base = dict(capability_id="gmail_send_email", version=1,
                arguments={"to": "a@b.com", "subject": "Hi"}, effects=["comms_external"],
                user_id="u1")
    base.update(kw)
    return ActionPlan(**base)


# ── Déterminisme + canonicalité ──────────────────────────────────────────


def test_fingerprint_is_deterministic():
    assert fingerprint(_plan()) == fingerprint(_plan())


def test_fingerprint_is_64_hex():
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint(_plan()))


def test_fingerprint_ignores_key_order():
    a = _plan(arguments={"to": "a@b.com", "subject": "Hi"})
    b = _plan(arguments={"subject": "Hi", "to": "a@b.com"})
    assert fingerprint(a) == fingerprint(b)


def test_fingerprint_ignores_effects_order():
    a = _plan(effects=["comms_external", "external_mutation"])
    b = _plan(effects=["external_mutation", "comms_external"])
    assert fingerprint(a) == fingerprint(b)


# ── Sensibilité : tout changement d'action change l'empreinte ─────────────


def test_fingerprint_changes_on_capability():
    assert fingerprint(_plan()) != fingerprint(_plan(capability_id="gmail_reply_email"))


def test_fingerprint_changes_on_arguments():
    assert fingerprint(_plan()) != fingerprint(_plan(arguments={"to": "evil@x.com", "subject": "Hi"}))


def test_fingerprint_changes_on_effects():
    assert fingerprint(_plan()) != fingerprint(_plan(effects=["comms_external", "destructive"]))


def test_fingerprint_binds_the_user():
    # Un plan approuvé pour un user ne vaut pas pour un autre.
    assert fingerprint(_plan(user_id="u1")) != fingerprint(_plan(user_id="u2"))


def test_fingerprint_ignores_conversation():
    a = _plan()
    a.conversation_id = "c1"
    b = _plan()
    b.conversation_id = "c2"
    assert fingerprint(a) == fingerprint(b)


# ── « L'approuvé == l'exécuté » ──────────────────────────────────────────


def test_verify_matches_identical_action():
    approved = fingerprint(_plan())
    assert verify(approved, _plan()) is True


def test_verify_detects_tampered_action():
    # On approuve l'envoi à a@b.com ; au moment d'exécuter, le destinataire a changé.
    approved = fingerprint(_plan(arguments={"to": "a@b.com", "subject": "Hi"}))
    tampered = _plan(arguments={"to": "attacker@x.com", "subject": "Hi"})
    assert verify(approved, tampered) is False


def test_verify_rejects_empty_fingerprint():
    assert verify("", _plan()) is False


# ── Le plan lit le manifeste ─────────────────────────────────────────────


def test_build_action_plan_sources_effects_from_manifest():
    plan = build_action_plan("drive_delete_file", {"file_id": "X"}, "u1", "conv1")
    assert plan.capability_id == "drive_delete_file"
    assert "destructive" in plan.effects        # vient du CapabilityManifest
    assert plan.user_id == "u1"


def test_build_action_plan_uses_display_args_only():
    # build_action_plan reçoit display_args (le caller exclut déjà creds/user_id) ;
    # l'empreinte ne porte donc jamais de credential.
    plan = build_action_plan("web_search", {"query": "météo"}, "u1")
    assert plan.arguments == {"query": "météo"}
    assert "user_google_credentials_json" not in fingerprint_payload(plan)


def fingerprint_payload(plan) -> str:
    # Helper : on vérifie qu'aucune clé secrète n'entre dans l'empreinte.
    import json
    return json.dumps({
        "capability_id": plan.capability_id, "version": plan.version,
        "arguments": plan.arguments, "effects": plan.effects, "user_id": plan.user_id,
    })
