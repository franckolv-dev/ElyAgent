# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/journal_service.py
# @brief      Reversible Action Journal — enregistrer / annuler une action.
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Service du Reversible Action Journal (substrat, suite de P1 — J1).

* ``record_reversible`` — appelé après le SUCCÈS d'un outil dans ``tool_node``.
  No-op si : flag OFF, pas de ``compensation`` au manifeste, handle inconnu, ou
  capture vide. Sinon écrit une entrée ``recorded``.
* ``undo`` — exécute la compensation enregistrée. **Fail-closed** : refus si
  propriétaire ≠ user, statut ≠ ``recorded``, ou entrée expirée. Idempotent
  (annuler deux fois ne ré-exécute jamais la compensation).
* ``list_reversible`` — entrées annulables d'un utilisateur (pour la surface
  d'annulation à venir en J2).

Le journal ne contient jamais de secret/PII : ``compensation_args`` se limite à
des identifiants (cf. ``compensation_registry``), et les creds sont re-résolus
à l'annulation, jamais stockés.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Borne du JSON d'identifiants mémorisé (même esprit que l'idempotence).
_ARGS_CAP = 4 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite renvoie souvent du naïf — on normalise en UTC aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _ttl_seconds() -> int:
    from app.config import get_settings
    return int(getattr(get_settings(), "reversible_journal_ttl_seconds", 7 * 24 * 3600) or 7 * 24 * 3600)


def _enabled() -> bool:
    from app.config import get_settings
    return bool(getattr(get_settings(), "reversible_journal_enabled", False))


def _emit(user_id: str, capability_id: str, fingerprint: str | None, outcome: str,
          attributes: dict | None = None) -> None:
    """Événement de compensation (corrélé, sans contenu). Ne lève jamais."""
    try:
        from app.services.event_envelope import EventKind, emit
        emit(EventKind.COMPENSATION, user_id=user_id, capability_id=capability_id,
             fingerprint=fingerprint, outcome=outcome, attributes=attributes)
    except Exception:  # pragma: no cover — l'observabilité ne casse jamais le flux
        pass


async def snapshot_before(tool_name: str, args: dict, user_id: str) -> dict | None:
    """(J3) Capture l'état AVANT exécution pour une compensation par snapshot.

    Appelé par tool_node juste avant ``tool.ainvoke``. Renvoie le snapshot (dict)
    pour les capacités dont la compensation est de type snapshot (rename/move),
    sinon None. Best-effort : jamais bloquant pour l'exécution de l'outil."""
    if not _enabled() or not user_id:
        return None
    from app.services.capability_manifest import get_manifest
    comp_name = get_manifest(tool_name).compensation
    if not comp_name:
        return None
    from app.services.compensation_registry import get_compensation
    comp = get_compensation(comp_name)
    if comp is None or comp.snapshot is None:
        return None
    try:
        return await comp.snapshot(dict(args or {}), user_id)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("snapshot_before a échoué (%s): %s", tool_name, exc)
        return None


def resultat_en_echec(result: str | None) -> bool:
    """Ce retour d'outil dit-il que l'action n'a PAS abouti ?

    Même règle que la garde anti-rejeu (``replay_guard._ECHEC_PREFIXES``) :
    une seule définition de l'échec, lue aux deux endroits qui en dépendent."""
    from app.agent.replay_guard import _ECHEC_PREFIXES
    return str(result or "").lstrip().lower().startswith(_ECHEC_PREFIXES)


async def record_reversible(
    tool_name: str,
    args: dict,
    result: str,
    user_id: str,
    fingerprint: str | None = None,
    pre_snapshot: dict | None = None,
) -> str | None:
    """Journalise une action annulable après son succès. Retourne l'id, ou None.

    No-op (None) si le flag est OFF, si l'utilisateur est absent, si le
    manifeste ne déclare pas de compensation, si le handle est inconnu, ou si
    rien d'exploitable n'a pu être retenu pour annuler.

    Deux modes : *snapshot* (l'état d'avant, capturé par ``snapshot_before`` et
    passé via ``pre_snapshot``) ou *opération inverse* (``capture`` post-succès)."""
    if not _enabled() or not user_id:
        return None
    # Trou n°2 (nommé dans compensation_registry, fermé le 03/09/2026) : les
    # outils d'Ely rendent leurs échecs en TEXTE (« Erreur … »), et la
    # passerelle journalisait sans le lire. Annuler une action qui n'a pas eu
    # lieu détruirait l'état d'avant, pas celui d'Ely.
    if resultat_en_echec(result):
        return None

    from app.services.capability_manifest import get_manifest
    comp_name = get_manifest(tool_name).compensation
    if not comp_name:
        return None

    from app.services.compensation_registry import get_compensation
    comp = get_compensation(comp_name)
    if comp is None:
        logger.debug("compensation '%s' déclarée mais non enregistrée (tool=%s)", comp_name, tool_name)
        return None

    try:
        if comp.snapshot is not None:
            comp_args = pre_snapshot or {}      # capturé AVANT l'exécution
        elif comp.capture is not None:
            comp_args = comp.capture(dict(args or {}), result or "")
        else:
            return None
    except Exception as exc:
        logger.debug("compensation capture a échoué (%s): %s", tool_name, exc)
        return None
    # La capture doit produire de quoi annuler (au moins une valeur non vide).
    if not comp_args or not any(v for v in comp_args.values()):
        return None

    rid = uuid.uuid4().hex
    payload = json.dumps(comp_args, ensure_ascii=False, default=str)[:_ARGS_CAP]
    now = _now()
    try:
        from app.database import async_session
        from app.models.reversible_action import ReversibleActionRecord
        async with async_session() as db:
            db.add(ReversibleActionRecord(
                id=rid, user_id=user_id, capability_id=tool_name,
                fingerprint=fingerprint, compensation=comp_name,
                compensation_args=payload, status="recorded",
                created_at=now, expires_at=now + timedelta(seconds=_ttl_seconds()),
            ))
            await db.commit()
    except Exception as exc:  # pragma: no cover — best-effort, jamais bloquant
        logger.warning("record_reversible a échoué (%s): %s", tool_name, exc)
        return None

    _emit(user_id, tool_name, fingerprint, "recorded")
    return rid


async def list_reversible(user_id: str, limit: int = 20) -> list[dict]:
    """Actions encore annulables (``recorded``, non expirées) de l'utilisateur."""
    if not user_id:
        return []
    from sqlalchemy import select

    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord

    now = _now()
    out: list[dict] = []
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(ReversibleActionRecord)
                .where(
                    ReversibleActionRecord.user_id == user_id,
                    ReversibleActionRecord.status == "recorded",
                )
                .order_by(ReversibleActionRecord.created_at.desc())
                .limit(max(1, int(limit)))
            )).scalars().all()
        for r in rows:
            if _aware(r.expires_at) <= now:
                continue
            out.append({
                "id": r.id,
                "capability_id": r.capability_id,
                "compensation": r.compensation,
                "created_at": _aware(r.created_at).isoformat() if r.created_at else None,
                "expires_at": _aware(r.expires_at).isoformat(),
            })
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("list_reversible a échoué (%s): %s", (user_id or "")[:8], exc)
    return out


async def undo(record_id: str, user_id: str) -> dict:
    """Annule une action journalisée. Fail-closed.

    Retour : ``{"ok": True, "capability_id": ...}`` en cas de succès, sinon
    ``{"ok": False, "reason": ...}`` (``not_found`` / ``forbidden`` /
    ``not_revertible:<status>`` / ``expired`` / ``unknown_compensation`` /
    ``revert_failed``)."""
    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord

    # 1. Charger + valider (fail-closed) sous transaction.
    async with async_session() as db:
        rec = await db.get(ReversibleActionRecord, record_id)
        if rec is None:
            return {"ok": False, "reason": "not_found"}
        if rec.user_id != user_id:
            return {"ok": False, "reason": "forbidden"}
        if rec.status != "recorded":
            # Idempotent : déjà annulée / échouée / expirée → pas de ré-exécution.
            return {"ok": False, "reason": f"not_revertible:{rec.status}"}
        if _aware(rec.expires_at) <= _now():
            rec.status = "expired"
            await db.commit()
            return {"ok": False, "reason": "expired"}
        capability_id = rec.capability_id
        comp_name = rec.compensation
        fingerprint = rec.fingerprint
        try:
            comp_args = json.loads(rec.compensation_args or "{}")
        except Exception:
            comp_args = {}

    from app.services.compensation_registry import get_compensation
    comp = get_compensation(comp_name)
    if comp is None:
        return {"ok": False, "reason": "unknown_compensation"}

    # 2. Exécuter la compensation hors transaction (appel réseau possible).
    try:
        await comp.revert(comp_args, user_id)
    except Exception as exc:
        logger.warning("undo: compensation a échoué (%s/%s): %s", capability_id, comp_name, exc)
        async with async_session() as db:
            rec = await db.get(ReversibleActionRecord, record_id)
            if rec is not None and rec.status == "recorded":
                rec.status = "revert_failed"
                await db.commit()
        _emit(user_id, capability_id, fingerprint, "revert_failed")
        return {"ok": False, "reason": "revert_failed", "error": type(exc).__name__}

    # 3. (J4) Vérifier que l'annulation a réellement pris (best-effort).
    #    verified = True/False si une vérification existe, None sinon.
    verified: bool | None = None
    if comp.verify is not None:
        try:
            verified = bool(await comp.verify(comp_args, user_id))
        except Exception as exc:  # pragma: no cover — la vérif ne casse jamais l'undo
            logger.debug("undo: verify a échoué (%s/%s): %s", capability_id, comp_name, exc)
            verified = None

    # 4. Marquer annulée.
    async with async_session() as db:
        rec = await db.get(ReversibleActionRecord, record_id)
        if rec is not None and rec.status == "recorded":
            rec.status = "reverted"
            rec.reverted_at = _now()
            await db.commit()
    _emit(user_id, capability_id, fingerprint, "reverted",
          attributes=None if verified is None else {"verified": verified})
    return {"ok": True, "capability_id": capability_id, "verified": verified}


async def purge_expired() -> int:
    """(J4) Supprime les entrées dont la fenêtre d'annulation est passée.

    Borne la table : une entrée hors fenêtre n'est de toute façon plus annulable
    (recorded expirée) ou n'est conservée que pour l'audit (reverted/échec). On
    filtre en Python (comparaison aware) pour éviter tout piège de format de date
    SQLite. Idempotent, jamais bloquant ; retourne le nombre supprimé."""
    from sqlalchemy import delete, select

    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord

    now = _now()
    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(ReversibleActionRecord.id, ReversibleActionRecord.expires_at)
            )).all()
            stale = [rid for rid, exp in rows if exp is not None and _aware(exp) <= now]
            if stale:
                await db.execute(
                    delete(ReversibleActionRecord).where(ReversibleActionRecord.id.in_(stale))
                )
                await db.commit()
            if stale:
                logger.info("reversible journal: %d entrée(s) expirée(s) purgée(s)", len(stale))
            return len(stale)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("purge_expired a échoué: %s", exc)
        return 0


async def stats() -> dict:
    """(J4) Métriques du journal : compteurs par statut + taux de succès d'annulation."""
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.reversible_action import ReversibleActionRecord

    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(ReversibleActionRecord.status, func.count())
                .group_by(ReversibleActionRecord.status)
            )).all()
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("stats a échoué: %s", exc)
        rows = []
    by_status = {s: n for s, n in rows}
    reverted = by_status.get("reverted", 0)
    attempted = reverted + by_status.get("revert_failed", 0)
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "revert_success_rate": round(reverted / attempted, 3) if attempted else None,
    }
