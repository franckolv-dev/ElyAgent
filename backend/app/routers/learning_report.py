# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/routers/learning_report.py
# @brief      Sprint 3.7 V1.5 Jalon 6 — `/api/me/learning-report` endpoint.
#             Renders the 4 learning-signal tables + user_profiles +
#             mission_critiques as a markdown digest (or JSON for the
#             future UI). "Transparence radicale" — the user sees what
#             ELY has learned about them and how it's performing.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
# @version    1.5.0
# =============================================================================
"""Learning report — Sprint 3.7 §7.

5 sections in deterministic order :

  1. **Préférences captées** — facts the user is known to have stated
     (from `user_profiles` SQL).
  2. **Tes refus HITL** — recent HITL refusals + ban decisions.
  3. **Quand ELY a halluciné** — recent `completion_guard` blocks.
  4. **Missions critiquées** — `mission_critiques` rows with
     `quality_score`, `honest_completion`, etc. Surfaces "succès en
     façade" detected by the LLM-as-judge.
  5. **Performance par tier LLM** — aggregated rates per tier on the
     time window (HITL refusal %, hallucination %, feedback mean,
     completion %).

Content negotiation : default `text/markdown`. When the client sends
`Accept: application/json` (or `?format=json`), the endpoint returns
structured data so the V1.5b UI can render its own interactive view.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import desc, func, select

from app.auth.dependencies import get_current_user
from app.database import async_session
from app.models.feedback import Feedback
from app.models.hallucination_block import HallucinationBlock
from app.models.hitl_refusal import HitlRefusal
from app.models.mission import MISSION_TERMINAL_STATUSES, Mission, MissionStep
from app.models.mission_critique import MissionCritique
from app.models.user import User
from app.models.user_memory import UserProfile

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _parse_window(window: str) -> timedelta:
    """Accepts `"7d"`, `"30d"`, `"90d"`, `"24h"`. Default 30d on garbage."""
    if not window:
        return timedelta(days=30)
    s = window.strip().lower()
    try:
        if s.endswith("d"):
            return timedelta(days=int(s[:-1]))
        if s.endswith("h"):
            return timedelta(hours=int(s[:-1]))
    except ValueError:
        pass
    return timedelta(days=30)


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    months = [
        "", "janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc.",
    ]
    return f"{dt.day} {months[dt.month]}"


def _decode_json_field(raw: str | None) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────
# Section loaders
# ─────────────────────────────────────────────────────────────────────────


async def _load_preferences(user_id: str, limit: int = 15) -> list[dict]:
    """Top facts/preferences known about the user (highest confidence first)."""
    async with async_session() as db:
        rows = (await db.execute(
            select(UserProfile)
            .where(UserProfile.user_id == user_id)
            .order_by(desc(UserProfile.confidence), desc(UserProfile.last_seen))
            .limit(limit)
        )).scalars().all()
    return [
        {
            "key": r.key,
            "value": r.value,
            "confidence": r.confidence,
            "source_count": r.source_count,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
        }
        for r in rows
    ]


async def _load_hitl_refusals(
    user_id: str, since: datetime, limit: int = 10,
) -> list[dict]:
    async with async_session() as db:
        rows = (await db.execute(
            select(HitlRefusal)
            .where(
                HitlRefusal.user_id == user_id,
                HitlRefusal.created_at >= since,
            )
            .order_by(desc(HitlRefusal.created_at))
            .limit(limit)
        )).scalars().all()
    return [
        {
            "tool_name": r.tool_name,
            "action_description": r.action_description,
            "decision": r.decision,
            "reason": r.reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _load_hallucinations(
    user_id: str, since: datetime, limit: int = 10,
) -> list[dict]:
    async with async_session() as db:
        rows = (await db.execute(
            select(HallucinationBlock)
            .where(
                HallucinationBlock.user_id == user_id,
                HallucinationBlock.created_at >= since,
            )
            .order_by(desc(HallucinationBlock.created_at))
            .limit(limit)
        )).scalars().all()
    return [
        {
            "model_used": r.model_used,
            "tier_llm": r.tier_llm,
            "reason": r.reason,
            "matched_patterns": _decode_json_field(r.matched_patterns),
            "original_response": (r.original_response or "")[:300],
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _load_mission_critiques(
    user_id: str, since: datetime, limit: int = 10,
) -> list[dict]:
    """Critiques of recent terminal missions, joined back to the mission
    row so we can display goal + status alongside the verdict."""
    async with async_session() as db:
        # Join on mission_id to get the goal/status
        rows = (await db.execute(
            select(MissionCritique, Mission)
            .join(Mission, Mission.id == MissionCritique.mission_id)
            .where(
                Mission.user_id == user_id,
                MissionCritique.created_at >= since,
            )
            .order_by(desc(MissionCritique.created_at))
            .limit(limit)
        )).all()
    out: list[dict] = []
    for critique, mission in rows:
        out.append({
            "mission_id": mission.id,
            "goal": (mission.goal or mission.title or "")[:200],
            "status": mission.status,
            "quality_score": critique.quality_score,
            "honest_completion": critique.honest_completion,
            "wasted_effort": critique.wasted_effort,
            "user_should_have_been_warned": critique.user_should_have_been_warned,
            "main_issue": critique.main_issue,
            "critic_model": critique.critic_model,
            "created_at": critique.created_at.isoformat(),
        })
    return out


async def _load_tier_performance(
    user_id: str, since: datetime,
) -> list[dict]:
    """Per-tier aggregates : message volume (proxy via mission_steps),
    HITL refusal rate, hallucination rate, feedback mean."""
    async with async_session() as db:
        # Volume per tier — from mission_steps.model_used
        vol_rows = (await db.execute(
            select(
                MissionStep.model_used,
                func.count(MissionStep.id).label("n"),
            )
            .join(Mission, Mission.id == MissionStep.mission_id)
            .where(
                Mission.user_id == user_id,
                MissionStep.created_at >= since,
                MissionStep.model_used.isnot(None),
            )
            .group_by(MissionStep.model_used)
        )).all()
        volumes = {row[0]: int(row[1]) for row in vol_rows}

        # HITL refusals per tier
        hitl_rows = (await db.execute(
            select(HitlRefusal.tier_llm, func.count(HitlRefusal.id))
            .where(
                HitlRefusal.user_id == user_id,
                HitlRefusal.created_at >= since,
            )
            .group_by(HitlRefusal.tier_llm)
        )).all()
        hitl_per_tier = {row[0] or "?": int(row[1]) for row in hitl_rows}

        # Hallucinations per tier
        hallu_rows = (await db.execute(
            select(HallucinationBlock.tier_llm, func.count(HallucinationBlock.id))
            .where(
                HallucinationBlock.user_id == user_id,
                HallucinationBlock.created_at >= since,
            )
            .group_by(HallucinationBlock.tier_llm)
        )).all()
        hallu_per_tier = {row[0] or "?": int(row[1]) for row in hallu_rows}

        # Feedback mean per model_used
        fb_rows = (await db.execute(
            select(
                Feedback.model_used,
                func.count(Feedback.id),
                func.avg(Feedback.rating),
            )
            .where(
                Feedback.user_id == user_id,
                Feedback.created_at >= since,
            )
            .group_by(Feedback.model_used)
        )).all()
        feedback_per_model = {
            row[0]: {"count": int(row[1]), "mean": float(row[2] or 0.0)}
            for row in fb_rows
        }

    # Synthesise per tier — note `model_used` in mission_steps usually
    # has the form "llm:provider/model+tools" so we extract the tier proxy
    # by examining if "deepseek-v4-pro" → C, "gemma-4" → A, etc. For V1
    # we just expose model_used as-is and let the UI/markdown render it.
    return [
        {
            "label": model,
            "messages": n,
            "hitl_refusals_total": sum(hitl_per_tier.values()),
            "hallucinations_total": sum(hallu_per_tier.values()),
            "feedback_count": feedback_per_model.get(model, {}).get("count", 0),
            "feedback_mean": round(
                feedback_per_model.get(model, {}).get("mean", 0.0), 2
            ),
        }
        for model, n in sorted(volumes.items(), key=lambda kv: kv[1], reverse=True)
    ]


# ─────────────────────────────────────────────────────────────────────────
# Markdown renderer
# ─────────────────────────────────────────────────────────────────────────


def _render_markdown(data: dict[str, Any], window_label: str) -> str:
    parts: list[str] = []
    parts.append(f"# Ce que tu sais sur moi — {window_label}\n")

    # 1. Préférences
    parts.append("## Préférences captées\n")
    prefs = data["preferences"]
    if not prefs:
        parts.append("_Rien d'enregistré pour le moment._\n")
    else:
        for p in prefs:
            conf = f" *(conf. {p['confidence']:.0%})*" if p["confidence"] < 0.95 else ""
            parts.append(f"- **{p['key']}** : {p['value']}{conf}")
        parts.append("")

    # 2. Refus HITL
    parts.append("## Tes refus HITL\n")
    refusals = data["hitl_refusals"]
    if not refusals:
        parts.append("_Aucun refus sur la période._\n")
    else:
        for r in refusals:
            dt = datetime.fromisoformat(r["created_at"])
            parts.append(
                f"- {_fmt_date(dt)} — **{r['decision']}** sur "
                f"`{r['tool_name']}` ({r['action_description'][:120]})"
            )
        parts.append("")

    # 3. Hallucinations
    parts.append("## Quand ELY a halluciné\n")
    hallus = data["hallucinations"]
    if not hallus:
        parts.append("_Aucune hallucination interceptée sur la période. 🎉_\n")
    else:
        for h in hallus:
            dt = datetime.fromisoformat(h["created_at"])
            tier = h["tier_llm"] or "?"
            parts.append(
                f"- {_fmt_date(dt)} — modèle `{h['model_used']}` (tier {tier}), "
                f"patterns : {', '.join(h['matched_patterns']) or '—'}"
            )
            if h["original_response"]:
                preview = h["original_response"][:200].replace("\n", " ")
                parts.append(f"  > {preview}…")
        parts.append("")

    # 4. Missions critiquées
    parts.append("## Missions critiquées\n")
    critiques = data["mission_critiques"]
    if not critiques:
        parts.append("_Aucune critique de mission sur la période._\n")
    else:
        for c in critiques:
            dt = datetime.fromisoformat(c["created_at"])
            flags = []
            if not c["honest_completion"]:
                flags.append("⚠️ succès en façade")
            if c["wasted_effort"]:
                flags.append("🔁 gâchis")
            if c["user_should_have_been_warned"]:
                flags.append("🚨 user à prévenir")
            flag_str = " · " + " · ".join(flags) if flags else ""
            parts.append(
                f"- {_fmt_date(dt)} — *{c['goal']}* (`{c['status']}`) — "
                f"**{c['quality_score']}/100**{flag_str}"
            )
            if c["main_issue"]:
                parts.append(f"  > {c['main_issue']}")
        parts.append("")

    # 5. Performance par modèle
    parts.append("## Performance par modèle\n")
    perf = data["tier_performance"]
    if not perf:
        parts.append("_Pas assez de données pour cette période._\n")
    else:
        parts.append("| Modèle | Messages | Feedback ⌀ |")
        parts.append("|---|---|---|")
        for p in perf:
            fb = f"{p['feedback_mean']:+.2f} ({p['feedback_count']})" if p["feedback_count"] else "—"
            parts.append(f"| `{p['label']}` | {p['messages']} | {fb} |")
        # Aggregate totals row
        total_hitl = perf[0]["hitl_refusals_total"] if perf else 0
        total_hallu = perf[0]["hallucinations_total"] if perf else 0
        parts.append("")
        parts.append(
            f"**Totaux période** : {total_hitl} refus HITL · "
            f"{total_hallu} hallucinations bloquées."
        )
        parts.append("")

    parts.append(
        "\n---\n*Rapport généré par ELY — Sprint 3.7 V1.5 "
        "(`/api/me/learning-report`). "
        "Les données restent locales, jamais transmises à un tiers.*"
    )
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────


@router.get("/api/me/learning-report")
async def learning_report(
    window: str = Query(
        "30d",
        description="Time window : 7d, 30d, 90d, or e.g. 24h.",
    ),
    format: str | None = Query(
        None,
        description="Force the response format : 'json' or 'markdown'. "
                    "If omitted, content negotiation uses Accept header.",
    ),
    accept: str = Header(default="text/markdown"),
    current_user: User = Depends(get_current_user),
):
    """Generate the per-user learning report — Sprint 3.7 V1.5 §7.

    Format selection :
      - `?format=json` → JSON regardless of Accept
      - `?format=markdown` → markdown regardless of Accept
      - Accept: application/json header → JSON
      - Otherwise → markdown (default)
    """
    user_id = str(current_user.id)
    window_td = _parse_window(window)
    since = datetime.now(timezone.utc) - window_td

    data = {
        "preferences": await _load_preferences(user_id),
        "hitl_refusals": await _load_hitl_refusals(user_id, since),
        "hallucinations": await _load_hallucinations(user_id, since),
        "mission_critiques": await _load_mission_critiques(user_id, since),
        "tier_performance": await _load_tier_performance(user_id, since),
        "window": window,
        "since": since.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    want_json = (
        (format and format.lower() == "json")
        or (not format and "application/json" in accept.lower())
    )
    if want_json:
        return JSONResponse(data)

    return PlainTextResponse(
        _render_markdown(data, window),
        media_type="text/markdown; charset=utf-8",
    )
