# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/regression.py
# @brief      Boucle d'auto-diagnostic J1 — « régression visible ».
#             Taux de succès RÉEL par tier/canal/jour + alerte sur chute.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Détection de régression — boucle d'auto-diagnostic, jalon J1.

Le premier livrable mesurable de la design note §6 : Ely surveille son
**taux de succès réel** (et non plus seulement *déclaré*) par groupe
d'exécution (source × tier × modèle × canal), dans le temps, et lève une
**alerte de chute** quand un groupe régresse — exactement le signal qui
aurait ouvert la journée du 13/06 (*« depuis gpt-5.5 sur le tier C, X
missions sur Y ont échoué »*) au lieu de la subir.

Lecture seule, zéro effet de bord : on lit la table ``execution_outcomes``
(alimentée par :func:`app.services.learning.signals.record_execution_outcome`)
et on agrège en mémoire (volume faible — exécutions terminées, rétention
90 j). Aucune dépendance LLM.

Deux taux par groupe :
  - ``declared_success_rate`` = (succeeded + dubious) / total
    → ce que le système CROYAIT réussi.
  - ``real_success_rate``     = succeeded / total
    → ce qui a réellement abouti (les ``dubious`` — succès de façade
      détectés à J2 — comptent contre).

En J1 ``dubious`` vaut toujours 0, donc les deux taux coïncident ; ils
divergeront dès que J2 branchera les heuristiques. C'est voulu : J1 pose
la mesure, J2 lui donne du tranchant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models.execution_outcome import ExecutionOutcome
from app.services.learning.signals import (
    OUTCOME_DUBIOUS,
    OUTCOME_FAILED,
    OUTCOME_SUCCEEDED,
)

# Dimensions de regroupement par défaut. Une exécution est rangée sous la
# combinaison des dimensions NON nulles qui la décrivent (ex pour une mission
# « source=mission · model_used=gpt-5.5 », pour une tâche « source=scheduled ·
# channel=telegram »).
DEFAULT_GROUP_DIMS: tuple[str, ...] = ("source", "tier_llm", "model_used", "channel")

# Seuils par défaut de l'alerte de chute. Volontairement prudents (anti-pattern
# §8 : « crier au loup » tue l'adhésion) — il faut un échantillon des deux côtés
# ET une chute franche pour lever une alerte.
DEFAULT_MIN_SAMPLES: int = 5
DEFAULT_DROP_THRESHOLD: float = 0.30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """SQLite renvoie des datetimes naïfs (stockés en UTC). On les rend
    tz-aware pour pouvoir les comparer aux fenêtres calculées en UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def parse_window(window: str | None, *, default_days: int = 30) -> timedelta:
    """Accepte ``"7d"``, ``"30d"``, ``"90d"``, ``"24h"``. Défaut sur déchet."""
    if not window:
        return timedelta(days=default_days)
    s = window.strip().lower()
    try:
        if s.endswith("d"):
            return timedelta(days=int(s[:-1]))
        if s.endswith("h"):
            return timedelta(hours=int(s[:-1]))
    except ValueError:
        pass
    return timedelta(days=default_days)


def _blank() -> dict[str, int]:
    return {"succeeded": 0, "dubious": 0, "failed": 0, "total": 0}


def _tally(acc: dict[str, int], outcome: str) -> None:
    acc["total"] += 1
    if outcome == OUTCOME_SUCCEEDED:
        acc["succeeded"] += 1
    elif outcome == OUTCOME_DUBIOUS:
        acc["dubious"] += 1
    else:  # OUTCOME_FAILED ou inconnu (défensif)
        acc["failed"] += 1


def _with_rates(acc: dict[str, int]) -> dict[str, Any]:
    t = acc["total"] or 1
    return {
        **acc,
        "real_success_rate": round(acc["succeeded"] / t, 4),
        "declared_success_rate": round((acc["succeeded"] + acc["dubious"]) / t, 4),
        "dubious_rate": round(acc["dubious"] / t, 4),
        "failed_rate": round(acc["failed"] / t, 4),
    }


def _group_label(row: ExecutionOutcome, dims: tuple[str, ...]) -> str:
    parts: list[str] = []
    for d in dims:
        v = getattr(row, d, None)
        if v:
            parts.append(f"{d}={v}")
    return " · ".join(parts) or "?"


async def _fetch(user_id: str | None, since: datetime) -> list[ExecutionOutcome]:
    async with async_session() as db:
        q = select(ExecutionOutcome).where(ExecutionOutcome.created_at >= since)
        if user_id:
            q = q.where(ExecutionOutcome.user_id == user_id)
        rows = (await db.execute(
            q.order_by(ExecutionOutcome.created_at.asc())
        )).scalars().all()
    return list(rows)


def _detect_regressions(
    rows: list[ExecutionOutcome],
    *,
    now: datetime,
    recent_td: timedelta,
    baseline_td: timedelta,
    min_samples: int,
    drop_threshold: float,
    dims: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Compare, par groupe, le taux de succès RÉEL d'une fenêtre récente à
    celui d'une fenêtre de référence qui la précède.

    Fenêtres : récente = ``[now - recent_td, now]`` ; référence =
    ``[now - baseline_td, now - recent_td)``. Une alerte est levée si les
    deux fenêtres ont ≥ ``min_samples`` exécutions ET que le taux récent a
    chuté d'au moins ``drop_threshold`` vs la référence.
    """
    recent_since = now - recent_td
    baseline_since = now - baseline_td
    base: dict[str, dict[str, int]] = {}
    rec: dict[str, dict[str, int]] = {}
    for r in rows:
        key = _group_label(r, dims)
        created = _as_utc(r.created_at)
        if created >= recent_since:
            rec.setdefault(key, _blank())
            _tally(rec[key], r.outcome)
        elif created >= baseline_since:
            base.setdefault(key, _blank())
            _tally(base[key], r.outcome)

    alerts: list[dict[str, Any]] = []
    for key in set(base) & set(rec):
        b, c = base[key], rec[key]
        if b["total"] < min_samples or c["total"] < min_samples:
            continue
        b_rate = b["succeeded"] / b["total"]
        c_rate = c["succeeded"] / c["total"]
        drop = b_rate - c_rate
        if drop >= drop_threshold:
            alerts.append({
                "group": key,
                "kind": "success_drop",
                "baseline_real_success_rate": round(b_rate, 4),
                "recent_real_success_rate": round(c_rate, 4),
                "drop": round(drop, 4),
                "baseline_n": b["total"],
                "recent_n": c["total"],
                "severity": "high" if drop >= 0.5 else "medium",
            })
    alerts.sort(key=lambda a: a["drop"], reverse=True)
    return alerts


async def regression_report(
    *,
    user_id: str | None = None,
    window: str = "30d",
    recent: str = "3d",
    baseline: str = "14d",
    min_samples: int = DEFAULT_MIN_SAMPLES,
    drop_threshold: float = DEFAULT_DROP_THRESHOLD,
    group_dims: tuple[str, ...] = DEFAULT_GROUP_DIMS,
) -> dict[str, Any]:
    """Rapport de régression — boucle d'auto-diagnostic J1.

    ``user_id=None`` → vue globale (toutes les exécutions, tous users :
    utile pour repérer une régression d'INFRA qui touche tout le monde).
    """
    now = _utcnow()
    window_td = parse_window(window)
    recent_td = parse_window(recent, default_days=3)
    baseline_td = parse_window(baseline, default_days=14)

    # On récupère assez large pour que la fenêtre de référence soit toujours
    # complète, même si baseline > window.
    fetch_since = now - max(window_td, baseline_td)
    all_rows = await _fetch(user_id, fetch_since)

    # Groupes + série journalière : sur la fenêtre d'affichage `window` only.
    window_since = now - window_td
    window_rows = [r for r in all_rows if _as_utc(r.created_at) >= window_since]

    groups: dict[str, dict[str, int]] = {}
    daily: dict[str, dict[str, int]] = {}
    totals = _blank()
    for r in window_rows:
        _tally(totals, r.outcome)
        gk = _group_label(r, group_dims)
        groups.setdefault(gk, _blank())
        _tally(groups[gk], r.outcome)
        day = _as_utc(r.created_at).date().isoformat()
        daily.setdefault(day, _blank())
        _tally(daily[day], r.outcome)

    group_list = [
        {"group": k, **_with_rates(v)}
        for k, v in sorted(groups.items(), key=lambda kv: kv[1]["total"], reverse=True)
    ]
    daily_list = [{"day": d, **_with_rates(v)} for d, v in sorted(daily.items())]

    alerts = _detect_regressions(
        all_rows,
        now=now,
        recent_td=recent_td,
        baseline_td=baseline_td,
        min_samples=min_samples,
        drop_threshold=drop_threshold,
        dims=group_dims,
    )

    return {
        "window": window,
        "since": window_since.isoformat(),
        "generated_at": now.isoformat(),
        "user_id": user_id,
        "totals": _with_rates(totals),
        "groups": group_list,
        "daily": daily_list,
        "alerts": alerts,
        "params": {
            "recent": recent,
            "baseline": baseline,
            "min_samples": min_samples,
            "drop_threshold": drop_threshold,
        },
    }
