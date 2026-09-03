# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/tests/test_event_envelope.py
# @brief      P1/J4 — bus d'événements typé : sûr (no secret/PII), corrélé.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
from __future__ import annotations

import re
import uuid

from app.services.event_envelope import (
    CORRELATION_ID,
    EventEnvelope,
    EventKind,
    emit,
    hash_user,
    recent_events,
)


# ── Identité hachée ──────────────────────────────────────────────────────


def test_user_id_is_hashed_never_raw():
    uid = "user-123-abc"
    h = hash_user(uid)
    assert h != uid
    assert re.fullmatch(r"[0-9a-f]{16}", h)
    assert hash_user(uid) == h          # déterministe


def test_emit_hashes_user():
    env = emit(EventKind.TOOL, user_id="secret-user-id", capability_id="web_search")
    assert env.user_id_hash != "secret-user-id"
    assert "secret-user-id" not in env.model_dump_json()


# ── Assainissement des attributs (secrets + PII) ─────────────────────────


def test_secret_in_attribute_is_redacted():
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUV012345"
    env = emit(EventKind.TOOL, user_id="u", capability_id="x",
               attributes={"token": secret, "count": 3, "note": "ok"})
    assert env.attributes["token"] == "[redacted]"
    assert env.attributes["count"] == 3        # nombre conservé
    assert env.attributes["note"] == "ok"      # valeur sûre conservée
    assert secret not in env.model_dump_json()  # ne fuit nulle part


def test_pii_in_attribute_is_redacted():
    env = emit(EventKind.TOOL, user_id="u", capability_id="x",
               attributes={"to": "jean.dupont@example.com"})
    assert env.attributes["to"] == "[redacted]"


def test_attribute_value_is_bounded():
    env = emit(EventKind.TOOL, user_id="u", capability_id="x",
               attributes={"big": "a" * 5000})
    assert len(env.attributes["big"]) <= 256


def test_emit_never_raises_on_bad_attributes():
    env = emit(EventKind.INCIDENT, user_id="u", attributes={"obj": object()})
    assert isinstance(env, EventEnvelope)


# ── Pas de contenu brut dans le contrat ──────────────────────────────────


def test_envelope_has_no_raw_content_field():
    fields = set(EventEnvelope.model_fields)
    forbidden = {"prompt", "messages", "content", "args", "arguments", "result", "body"}
    assert fields.isdisjoint(forbidden)


# ── Corrélation / reconstruction ─────────────────────────────────────────


def test_events_are_correlated_and_reconstructable():
    cid = f"corr_{uuid.uuid4().hex}"
    other = f"corr_{uuid.uuid4().hex}"
    CORRELATION_ID.set(cid)
    emit(EventKind.APPROVAL, user_id="u", capability_id="gmail_send_email", outcome="allow")
    emit(EventKind.TOOL, user_id="u", capability_id="gmail_send_email", outcome="success", latency_ms=42.0)

    events = recent_events(cid)
    kinds = [e.kind for e in events]
    assert EventKind.APPROVAL in kinds and EventKind.TOOL in kinds
    # tous portent le bon id de corrélation
    assert all(e.correlation_id == cid for e in events)
    # un autre tour n'est pas mélangé
    assert recent_events(other) == []


def test_event_carries_fingerprint_for_join_with_actions():
    cid = f"corr_{uuid.uuid4().hex}"
    CORRELATION_ID.set(cid)
    emit(EventKind.TOOL, user_id="u", capability_id="x", fingerprint="abc123", outcome="success")
    ev = recent_events(cid)[-1]
    assert ev.fingerprint == "abc123"   # permet de relier événement ↔ plan d'action
