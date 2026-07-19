# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/event_envelope.py
# @brief      EventEnvelope — bus d'événements typé et corrélé (P1/J4).
# @license    Elastic License 2.0
# =============================================================================
"""Journal d'événements typé, corrélé, SANS secret ni PII (P1/J4).

But (cadrage §4.4) : pouvoir reconstruire ce qu'Ely a fait — quels outils,
quelles approbations, quels résultats, quel coût — **par corrélation**, sans
lire un seul prompt privé.

Garanties :

* l'identité utilisateur n'apparaît que **hachée** (``user_id_hash``) ;
* le seul champ libre, ``attributes``, est **assaini** (secrets et PII
  redactés via la couche ``mcp_outbound``, valeurs bornées) ;
* aucun champ ne porte de prompt, message ou contenu brut.

L'export OpenTelemetry est **optionnel et config-gated** : le bus fonctionne
sans collector ; l'exporter ne s'active que si le SDK est présent ET
``otel_enabled``.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import deque
from contextvars import ContextVar
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Identifiant de corrélation du tour/mission, posé par tool_node (comme
# ORCHESTRATE_CONVERSATION_ID). Tous les événements d'un tour le partagent.
CORRELATION_ID: ContextVar[str] = ContextVar("trust_correlation_id", default="")

_VALUE_CAP = 256
# Tampon en mémoire (diagnostic + tests). Process-local, éphémère.
_RING: "deque[EventEnvelope]" = deque(maxlen=2000)


class EventKind(str, Enum):
    SESSION = "session"
    MODEL = "model"
    TOOL = "tool"
    APPROVAL = "approval"
    SUBAGENT = "subagent"
    MEMORY = "memory"
    COST = "cost"
    INCIDENT = "incident"
    COMPENSATION = "compensation"   # annulation d'une action (Reversible Journal)
    ROUTING = "routing"             # décision de routage LLM (C3d-4)


class EventEnvelope(BaseModel):
    event_id: str
    correlation_id: str
    causation_id: Optional[str] = None
    kind: EventKind
    ts: float
    user_id_hash: str
    capability_id: Optional[str] = None
    fingerprint: Optional[str] = None     # empreinte du plan d'action (J2)
    outcome: Optional[str] = None
    latency_ms: Optional[float] = None
    attributes: dict = Field(default_factory=dict)


def hash_user(user_id: str) -> str:
    """Pseudonyme stable et non réversible de l'utilisateur (jamais l'id brut)."""
    return hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:16]


def _sanitize_attributes(attrs: Optional[dict]) -> dict:
    """Redacte secrets et PII, borne les valeurs. Les nombres/bools passent."""
    if not attrs:
        return {}
    from app.services.mcp_outbound import scan_outbound

    out: dict = {}
    for k, v in attrs.items():
        key = str(k)
        # Nombres et booléens : sûrs, passent tels quels (bool ⊂ int).
        if isinstance(v, (int, float)):
            out[key] = v
            continue
        sv = str(v)
        try:
            findings = scan_outbound({key: sv})
        except Exception:  # pragma: no cover — défensif
            findings = [object()]  # en cas de doute : redacte
        out[key] = "[redacted]" if findings else sv[:_VALUE_CAP]
    return out


def _otel_export(env: "EventEnvelope") -> None:
    """Export OpenTelemetry best-effort. No-op si le SDK est absent ou le flag off."""
    try:
        from app.config import get_settings
        if not getattr(get_settings(), "otel_enabled", False):
            return
        import importlib.util
        if importlib.util.find_spec("opentelemetry") is None:
            return
        from opentelemetry import trace  # pragma: no cover — SDK absent en CI
        span = trace.get_current_span()
        span.add_event(env.kind.value, attributes={
            "correlation_id": env.correlation_id,
            "capability_id": env.capability_id or "",
            "outcome": env.outcome or "",
        })
    except Exception:  # pragma: no cover — l'observabilité ne casse jamais le flux
        pass


def emit(
    kind: EventKind,
    *,
    user_id: str = "",
    capability_id: Optional[str] = None,
    fingerprint: Optional[str] = None,
    outcome: Optional[str] = None,
    latency_ms: Optional[float] = None,
    causation_id: Optional[str] = None,
    attributes: Optional[dict] = None,
) -> EventEnvelope:
    """Émet un événement typé, assaini et corrélé. Ne lève jamais."""
    env = EventEnvelope(
        event_id=uuid.uuid4().hex,
        correlation_id=CORRELATION_ID.get() or "",
        causation_id=causation_id,
        kind=kind,
        ts=time.time(),
        user_id_hash=hash_user(user_id),
        capability_id=capability_id,
        fingerprint=fingerprint,
        outcome=outcome,
        latency_ms=latency_ms,
        attributes=_sanitize_attributes(attributes),
    )
    _RING.append(env)
    try:
        logger.info("[event] %s", env.model_dump_json())
    except Exception:  # pragma: no cover
        pass
    _otel_export(env)
    return env


def recent_events(correlation_id: str) -> list[EventEnvelope]:
    """Événements récents (en mémoire) partageant ce ``correlation_id``."""
    return [e for e in _RING if e.correlation_id == correlation_id]
