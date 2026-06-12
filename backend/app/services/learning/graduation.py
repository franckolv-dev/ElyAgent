# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/graduation.py
# @brief      Sprint 4d (V4) J1 — stats & gates de graduation d'un learned
#             tool vers le code core. Mécanique de conversion : J4.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.0.0
# @link       https://github.com/franckolv-dev/ElyAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""Graduation des learned tools — design note Sprint 4d §4.

Un python_tool « gradue » quand il a fait ses preuves à l'usage : il est
alors converti en fichier core (J4) et livré par PR GitHub (J5). Ce module
J1 fournit la VÉRITÉ par outil sur laquelle les gates s'appuient :

- :func:`tool_origin` — « learned » ou « builtin » au moment d'un signal
  (erreur, refus HITL). Posé à la capture dans ``signals.py``, jamais
  recalculé après coup : un tool gradué garde ses signaux « learned »
  historiques et accumule des signaux « builtin » ensuite.
- :func:`compute_graduation_stats` — invocations, erreurs/refus récents,
  âge, et le verdict gate par gate.

Seuils — arbitrage Franck 2026-06-10 : profil « souple » tant que le
funnel est naissant (design note §6.1). Env-tunables sans rebuild de code
(mais rebuild d'image) :

- ``GRADUATION_MIN_INVOCATIONS``  (défaut 10)
- ``GRADUATION_ERROR_FREE_DAYS``  (défaut 14)
- ``GRADUATION_MIN_AGE_DAYS``     (défaut 7)

Les gates « revalidation 7 étages » et « dépendances de composition »
arrivent avec le codegen (J4) — elles nécessitent le dry-run.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Valeurs de la colonne {error_log,hitl_refusals}.tool_origin
ORIGIN_LEARNED = "learned"
ORIGIN_BUILTIN = "builtin"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def graduation_thresholds() -> dict[str, int]:
    """Seuils courants (lus à chaque appel — pas de cache, l'admin doit
    voir l'effet d'un changement d'env au redémarrage suivant)."""
    return {
        "min_invocations": _env_int("GRADUATION_MIN_INVOCATIONS", 10),
        "error_free_days": _env_int("GRADUATION_ERROR_FREE_DAYS", 14),
        "min_age_days": _env_int("GRADUATION_MIN_AGE_DAYS", 7),
    }


# ─────────────────────────────────────────────────────────────────────────
# Origine d'un tool au moment d'un signal
# ─────────────────────────────────────────────────────────────────────────


async def tool_origin(user_id: str, tool_name: str) -> str:
    """« learned » si ``tool_name`` est un python_tool ACTIF de ce user.

    Filtre ``status='active'`` à dessein : seuls les actifs sont bindés au
    LLM (learned_tools_runtime), donc un signal sur ce nom ne peut venir
    que d'eux. Après graduation (status='graduated'), c'est le tool core
    homonyme qui est bindé → « builtin », ce qui est exact.

    Best-effort fail-safe : toute erreur → « builtin » (ne sur-attribue
    jamais un échec à un learned tool).
    """
    if not user_id or not tool_name:
        return ORIGIN_BUILTIN
    try:
        from app.database import async_session
        from app.models.learned_skill import (
            LearnedSkill,
            SkillContentFormat,
            SkillStatus,
        )
        async with async_session() as db:
            row = await db.execute(
                select(LearnedSkill.id)
                .where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.name == tool_name,
                    LearnedSkill.content_format == SkillContentFormat.PYTHON_TOOL,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
                .limit(1)
            )
            return ORIGIN_LEARNED if row.first() else ORIGIN_BUILTIN
    except Exception as exc:
        logger.debug("tool_origin lookup failed (fail-safe builtin): %s", exc)
        return ORIGIN_BUILTIN


# ─────────────────────────────────────────────────────────────────────────
# Stats & gates
# ─────────────────────────────────────────────────────────────────────────


def _naive_utc(dt: datetime | None) -> datetime | None:
    """SQLite stocke les DateTime naïfs — normalise pour comparer."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def compute_graduation_stats(db: AsyncSession, skill: Any) -> dict[str, Any]:
    """Stats + verdict gate par gate pour un ``LearnedSkill``.

    Retourne un dict JSON-sérialisable (consommé tel quel par l'endpoint
    admin et par l'UI J3) :

    ``{skill_id, tool_name, thresholds, stats:{…}, gates:[{key,label,ok,
    value,threshold}], eligible}``

    ``eligible`` = toutes les gates calculables passent. Les gates J4
    (revalidation, composition) ne sont PAS incluses ici — le dry-run de
    graduation les jouera ; ``eligible`` signifie « digne d'un dry-run »,
    pas « PR garantie ».
    """
    from app.models.error_log import ErrorLog
    from app.models.hitl_refusal import HitlRefusal
    from app.models.io_tool_dispatch import IoToolDispatch
    from app.models.learned_skill import SkillContentFormat, SkillStatus

    th = graduation_thresholds()
    now = _now_naive()
    error_cutoff = now - timedelta(days=th["error_free_days"])

    # ── Invocations : use_count (bump runtime) + dispatches sandbox (io) ──
    io_dispatches = (
        await db.execute(
            select(func.count())
            .select_from(IoToolDispatch)
            .where(IoToolDispatch.skill_id == skill.id)
        )
    ).scalar_one()
    invocations = int(skill.use_count or 0) + int(io_dispatches)

    # ── V4.1 — distribution des outcomes sandbox (gates io) ──────────────
    # Seules les métriques MESURABLES : l'audit trace les labels déclarés-
    # résolus et les domaines déclarés, pas leur usage réel — les gates de
    # « cohérence déclaré vs utilisé » seraient toujours trivialement
    # vertes, donc on ne les pose pas.
    io_outcomes: dict[str, int] = {}
    if (getattr(skill, "tool_profile", "pure") or "pure") == "io":
        rows = (
            await db.execute(
                select(IoToolDispatch.outcome, func.count())
                .where(IoToolDispatch.skill_id == skill.id)
                .group_by(IoToolDispatch.outcome)
            )
        ).all()
        io_outcomes = {outcome: int(n) for outcome, n in rows}

    # ── Signaux récents (fenêtre error_free_days) ─────────────────────────
    # Match par (user, nom, origine learned) : tool_origin posé à la capture
    # garantit qu'on ne compte pas les erreurs d'un builtin homonyme ; les
    # rows pré-J1 (origin NULL) sont comptées AUSSI par prudence — un échec
    # non attribuable ne doit pas accélérer une graduation.
    def _recent_count_query(model):
        return (
            select(func.count())
            .select_from(model)
            .where(
                model.user_id == skill.user_id,
                model.tool_name == skill.name,
                model.created_at >= error_cutoff,
                model.tool_origin.in_([ORIGIN_LEARNED]) | model.tool_origin.is_(None),
            )
        )

    errors_recent = (await db.execute(_recent_count_query(ErrorLog))).scalar_one()
    refusals_recent = (await db.execute(_recent_count_query(HitlRefusal))).scalar_one()

    last_error_at = (
        await db.execute(
            select(func.max(ErrorLog.created_at)).where(
                ErrorLog.user_id == skill.user_id,
                ErrorLog.tool_name == skill.name,
            )
        )
    ).scalar_one()

    created = _naive_utc(skill.created_at)
    age_days = (now - created).days if created else 0

    profile = getattr(skill, "tool_profile", "pure") or "pure"

    gates = [
        {
            "key": "status_active",
            "label": "Statut actif (promu, bindé au LLM)",
            "ok": skill.status == SkillStatus.ACTIVE,
            "value": skill.status,
            "threshold": SkillStatus.ACTIVE,
        },
        {
            "key": "python_tool",
            "label": "Format python_tool (les playbooks ne graduent pas)",
            "ok": skill.content_format == SkillContentFormat.PYTHON_TOOL,
            "value": skill.content_format,
            "threshold": SkillContentFormat.PYTHON_TOOL,
        },
        {
            "key": "profile_supported",
            "label": "Profil supporté par le codegen (pure in-process, io sandbox conservée)",
            "ok": profile in ("pure", "io"),
            "value": profile,
            "threshold": "pure|io",
        },
        {
            "key": "invocations",
            "label": f"≥ {th['min_invocations']} invocations",
            "ok": invocations >= th["min_invocations"],
            "value": invocations,
            "threshold": th["min_invocations"],
        },
        {
            "key": "error_free",
            "label": f"0 erreur sur {th['error_free_days']} j",
            "ok": int(errors_recent) == 0,
            "value": int(errors_recent),
            "threshold": 0,
        },
        {
            "key": "refusal_free",
            "label": f"0 refus HITL sur {th['error_free_days']} j",
            "ok": int(refusals_recent) == 0,
            "value": int(refusals_recent),
            "threshold": 0,
        },
        {
            "key": "age",
            "label": f"≥ {th['min_age_days']} j d'ancienneté",
            "ok": age_days >= th["min_age_days"],
            "value": age_days,
            "threshold": th["min_age_days"],
        },
    ]

    # ── V4.1 — gates spécifiques io (sandbox) ─────────────────────────────
    # Zéro dispatch = zéro preuve : gates rouges (cohérent avec la gate
    # invocations, qui échoue déjà à 0).
    if profile == "io":
        total = sum(io_outcomes.values())
        returned = io_outcomes.get("returned", 0)
        timeouts = io_outcomes.get("timeout", 0)
        gates.append({
            "key": "io_returned_rate",
            "label": "≥ 80 % des dispatchs sandbox aboutis (returned)",
            "ok": total > 0 and returned >= total * 0.8,
            "value": f"{returned}/{total}",
            "threshold": "80%",
        })
        gates.append({
            "key": "io_timeout_rate",
            "label": "< 5 % de timeouts sandbox",
            "ok": total > 0 and timeouts < max(1, total * 0.05),
            "value": f"{timeouts}/{total}",
            "threshold": "<5%",
        })

    return {
        "skill_id": skill.id,
        "tool_name": skill.name,
        "thresholds": th,
        "stats": {
            "invocations": invocations,
            "use_count": int(skill.use_count or 0),
            "io_dispatches": int(io_dispatches),
            "io_outcomes": io_outcomes,
            "errors_recent": int(errors_recent),
            "refusals_recent": int(refusals_recent),
            "age_days": age_days,
            "last_error_at": last_error_at.isoformat() if last_error_at else None,
            "last_used_at": skill.last_used_at.isoformat() if skill.last_used_at else None,
        },
        "gates": gates,
        "eligible": all(g["ok"] for g in gates),
    }
