# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/anticipation.py
# @brief      C5 — anticipation V1 : détecter les demandes récurrentes et
#             PROPOSER une tâche planifiée (jamais exécuter seule).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Anticipation — C5 V1 (P4 de la roadmap, cadrage validé 22/07).

Constat de l'analyse fonctionnelle du 16/07 : anticipation ≈ 0 — Ely
n'apprend rien des ROUTINES de l'utilisateur. V1 minimale : un cron
hebdo scanne les messages utilisateur des 28 derniers jours, cherche
les quasi-doublons lexicaux revenant à cadence régulière (≥ 3 fois,
même heure ± 2 h ou même jour de semaine), et PROPOSE d'en faire une
tâche planifiée — notification ntfy + panneau /api/me/suggestions.

Principes durs :

- **Jamais d'exécution.** La suggestion est une row + un push ; c'est
  l'utilisateur qui crée (ou pas) la tâche via la modal pré-remplie.
- **Zéro LLM dans la détection** (heuristique pure, leçon récurrente :
  le lexical mène) — un LLM n'intervient nulle part en V1, même pas
  pour libeller (le message d'origine EST le libellé).
- **Anti-spam par existence** : une row par (user, pattern_hash),
  UNIQUE en base ; un refus est définitif.
- Kill-switch : ``ANTICIPATION_DISABLED=true``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models.anticipation import AnticipationSuggestion, SuggestionStatus
from app.models.conversation import Conversation, Message

logger = logging.getLogger(__name__)


ANTICIPATION_WINDOW_DAYS = 28
MIN_OCCURRENCES = 3
HOUR_TOLERANCE = 2.0   # heures — dispersion max pour une cadence « daily »
_MAX_EVIDENCE = 5      # occurrences échantillonnées dans evidence_json
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Conversations SYNTHÉTIQUES exclues du scan — le scheduler persiste chaque
# run comme une conversation « [Planifié] … » avec le prompt en message
# user : sans cette exclusion, le détecteur voit les tâches DÉJÀ planifiées
# comme des routines à proposer (ouroboros — 8 fausses suggestions au
# premier cycle réel, 22/07).
_SYNTHETIC_TITLE_PREFIXES = ("[Planifié]",)


def _not_synthetic_conversation():
    """Clause SQL : conversations humaines seulement."""
    from sqlalchemy import and_, not_
    return and_(*[
        not_(Conversation.title.startswith(p)) for p in _SYNTHETIC_TITLE_PREFIXES
    ])


def _is_disabled() -> bool:
    return os.getenv("ANTICIPATION_DISABLED", "").lower() in ("1", "true", "yes")


def _norm(s: str) -> str:
    """Lowercase + strip accents — même recette que find_tool/_norm."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _cluster_key(text: str) -> str | None:
    """Clé de cluster lexicale : tokens significatifs (≥ 3 caractères
    alphanumériques après normalisation) TRIÉS et dédupliqués.

    Regroupe les QUASI-doublons (mêmes mots, ordre/ponctuation/accents
    différents) — seuil volontairement élevé : les paraphrases lointaines
    sont hors périmètre V1 (cadrage). None pour les messages triviaux
    (< 2 tokens significatifs : « bonjour », « ok »…).
    """
    normed = _norm(text)
    tokens = sorted({
        tok for tok in "".join(
            c if c.isalnum() else " " for c in normed
        ).split() if len(tok) >= 3
    })
    if len(tokens) < 2:
        return None
    return " ".join(tokens)


def _pattern_hash(cluster_key: str) -> str:
    return hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:16]


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def detect_time_regularity(times: list[datetime]) -> dict[str, Any] | None:
    """Cadence régulière dans une liste d'horodatages ? Heuristique pure.

    - « daily » : ≥ MIN_OCCURRENCES jours DISTINCTS et heures resserrées
      (max − min ≤ HOUR_TOLERANCE ; les récurrences à cheval sur minuit
      sont ratées — assumé V1).
    - « weekly » : ≥ MIN_OCCURRENCES semaines ISO distinctes, tous les
      jours de semaine à ± 1 du jour dominant.

    Priorité au daily (plus fréquent = signal plus fort). None sinon.
    """
    if len(times) < MIN_OCCURRENCES:
        return None
    times = sorted(_as_utc(t) for t in times)
    hours = [t.hour + t.minute / 60.0 for t in times]
    days = {t.date() for t in times}
    weeks = {t.isocalendar()[:2] for t in times}
    weekdays = [t.weekday() for t in times]

    # « daily » exige la DENSITÉ, pas seulement des jours distincts : trois
    # lundis consécutifs ont 3 dates distinctes à la même heure mais ne
    # sont pas quotidiens — l'étendue calendaire doit rester ≤ 2× le nombre
    # de jours vus (≥ un jour sur deux), sinon on laisse le weekly trancher.
    span_days = (max(days) - min(days)).days + 1
    dense = span_days <= 2 * len(days)
    if len(days) >= MIN_OCCURRENCES and dense \
            and (max(hours) - min(hours)) <= HOUR_TOLERANCE:
        return {"kind": "daily", "hour": int(round(median(hours))) % 24}

    if len(weeks) >= MIN_OCCURRENCES:
        dominant = max(set(weekdays), key=weekdays.count)
        if all(min(abs(w - dominant), 7 - abs(w - dominant)) <= 1 for w in weekdays):
            return {
                "kind": "weekly",
                "weekday": dominant,
                "hour": int(round(median(hours))) % 24,
            }
    return None


def _cadence_label(cadence: dict[str, Any]) -> str:
    """"daily@09:00" | "weekly:mon@09:00" — descriptif, consommé par la
    modal de création de tâche (PR frontend)."""
    hour = f"{cadence.get('hour', 9):02d}:00"
    if cadence["kind"] == "daily":
        return f"daily@{hour}"
    return f"weekly:{_WEEKDAYS[cadence.get('weekday', 0)]}@{hour}"


async def scan_user(
    user_id: str,
    now: datetime | None = None,
    window_days: int = ANTICIPATION_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Les patterns récurrents d'un utilisateur sur la fenêtre glissante.

    Retourne des candidats ``{pattern_hash, cluster_key, occurrences,
    cadence, suggested_prompt, evidence}`` — AUCUNE écriture ici (le
    cycle décide, avec l'anti-spam). Jamais raise.
    """
    if not user_id:
        return []
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = _as_utc(now).replace(tzinfo=None) - timedelta(days=window_days)
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(Message.content, Message.created_at)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.user_id == user_id,
                    Message.role == "user",
                    Message.created_at >= cutoff,
                    _not_synthetic_conversation(),
                )
                .order_by(Message.created_at.asc())
            )).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("anticipation scan_user(%s) failed: %s", user_id[:8], exc)
        return []

    clusters: dict[str, list[tuple[str, datetime]]] = {}
    for content, created_at in rows:
        key = _cluster_key(content or "")
        if key is None:
            continue
        clusters.setdefault(key, []).append((content, created_at))

    candidates: list[dict[str, Any]] = []
    for key, entries in clusters.items():
        if len(entries) < MIN_OCCURRENCES:
            continue
        cadence = detect_time_regularity([e[1] for e in entries])
        if cadence is None:
            continue
        latest_content = entries[-1][0]
        candidates.append({
            "pattern_hash": _pattern_hash(key),
            "cluster_key": key,
            "occurrences": len(entries),
            "cadence": cadence,
            "suggested_prompt": (latest_content or "").strip()[:500],
            "evidence": [
                {"at": _as_utc(at).isoformat(), "content": (c or "")[:200]}
                for c, at in entries[-_MAX_EVIDENCE:]
            ],
        })
    return candidates


async def _notify_suggestion(*, user_id: str, prompt: str, cadence_label: str) -> None:
    """Push ntfy best-effort — même pattern que candidate_notify (httpx
    5 s, no-op sans NTFY_URL, Title ASCII via ascii_header, leçon #220)."""
    ntfy_url = os.environ.get("NTFY_URL")
    if not ntfy_url:
        return
    try:
        import httpx

        from app.services.ntfy_headers import ascii_header
        body = (
            f"« {prompt[:120]} » revient régulièrement ({cadence_label}).\n"
            "Veux-tu en faire une tâche planifiée ? Panneau Suggestions "
            "dans Ely pour créer (ou refuser)."
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                ntfy_url,
                content=body.encode("utf-8"),
                headers={
                    "Title": ascii_header("Ely - suggestion de routine"),
                    "Tags": "bulb",
                    "Priority": "default",
                },
            )
    except Exception as exc:  # noqa: BLE001 — le push est optionnel
        logger.debug("anticipation ntfy skipped (user=%s): %s", user_id[:8], exc)


async def run_anticipation_cycle(now: datetime | None = None) -> dict[str, Any]:
    """Une passe complète : scan de chaque utilisateur actif, insertion
    des suggestions NOUVELLES (anti-spam par existence de la row, quel
    que soit son status), notification. Jamais raise.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if _is_disabled():
        logger.info("anticipation: cycle skipped — ANTICIPATION_DISABLED")
        return {"skipped_disabled": True, "users": 0, "proposed": 0}

    summary = {"skipped_disabled": False, "users": 0, "proposed": 0}
    cutoff = _as_utc(now).replace(tzinfo=None) - timedelta(days=ANTICIPATION_WINDOW_DAYS)
    try:
        async with async_session() as db:
            user_ids = [
                u for u in (await db.execute(
                    select(Conversation.user_id)
                    .join(Message, Message.conversation_id == Conversation.id)
                    .where(
                        Message.role == "user",
                        Message.created_at >= cutoff,
                        _not_synthetic_conversation(),
                    )
                    .distinct()
                )).scalars().all()
                if u
            ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("anticipation: user scan failed (%s)", exc)
        return summary

    summary["users"] = len(user_ids)
    for uid in user_ids:
        candidates = await scan_user(uid, now=now)
        if not candidates:
            continue
        try:
            async with async_session() as db:
                known = set((await db.execute(
                    select(AnticipationSuggestion.pattern_hash).where(
                        AnticipationSuggestion.user_id == uid,
                    )
                )).scalars().all())
                fresh = [c for c in candidates if c["pattern_hash"] not in known]
                for c in fresh:
                    db.add(AnticipationSuggestion(
                        user_id=uid,
                        pattern_hash=c["pattern_hash"],
                        status=SuggestionStatus.PROPOSED,
                        suggested_prompt=c["suggested_prompt"],
                        suggested_cadence=_cadence_label(c["cadence"]),
                        evidence_json=json.dumps(c["evidence"], ensure_ascii=False),
                    ))
                if fresh:
                    await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("anticipation: insert failed for %s (%s)", uid[:8], exc)
            continue
        for c in fresh:
            summary["proposed"] += 1
            logger.info(
                "anticipation: suggestion proposée user=%s pattern=%s (%s, %d occ.)",
                uid[:8], c["pattern_hash"], _cadence_label(c["cadence"]),
                c["occurrences"],
            )
            await _notify_suggestion(
                user_id=uid,
                prompt=c["suggested_prompt"],
                cadence_label=_cadence_label(c["cadence"]),
            )
    return summary
