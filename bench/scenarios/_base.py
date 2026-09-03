# =============================================================================
# @project    ELY — Exactly Like You
# @file       bench/scenarios/_base.py
# @brief      Sprint 3.7.3 J1 — shared helpers for canonical bench scenarios.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#            https://opensource.org/licenses/MIT
# =============================================================================
"""Shared helpers + conventions for the canonical bench harness.

A canonical scenario is any module under ``bench/scenarios/canonical/``
named ``scenario_<id>.py`` exposing :

    NAME        = "<short title>"
    DESCRIPTION = "<one-liner>"
    TAGS        = ["shallow", ...]      # optional, defaults to ["shallow"]
    async def run() -> dict: ...

The runner discovers scenarios automatically and filters by ``--tag``.
Tag taxonomy (Sprint 3.7.3 design) ::

    "shallow"   — service-level only, no LLM call, sub-second. CI-cheap.
    "medium"    — orchestrator path with mocked LLM, a few seconds.
    "deep"      — real LLM call (capped budget), tens of seconds.
                  Excluded from the nightly CI run by default.

This module centralises the bits every scenario kept duplicating :
unique throw-away user provisioning, PII anonymisation, check-dict
to result-shape conversion. Code that wasn't shared before is left
inline in the existing scenarios for now — the goal is to make NEW
scenarios cheap to write, not to retrofit the 5 existing ones in J1.
"""
from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterable


# ── Tag taxonomy ──────────────────────────────────────────────────────────
TAG_SHALLOW = "shallow"
TAG_MEDIUM  = "medium"
TAG_DEEP    = "deep"

ALL_TAGS = (TAG_SHALLOW, TAG_MEDIUM, TAG_DEEP)

# Default tag when a scenario doesn't declare one. Matches the existing
# 5 scenarios' actual behaviour (no LLM call, sub-second). Documented
# in the module docstring so scenario authors know to override.
DEFAULT_TAGS: tuple[str, ...] = (TAG_SHALLOW,)


def normalise_tags(raw: object) -> list[str]:
    """Coerce a ``TAGS`` declaration into a clean list of known tags.

    Unknown values are dropped with no error (forward-compatible). A
    scenario with no TAGS at all gets ``DEFAULT_TAGS``.
    """
    if not raw:
        return list(DEFAULT_TAGS)
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if not isinstance(t, str):
            continue
        t = t.strip().lower()
        if t in ALL_TAGS and t not in seen:
            seen.add(t)
            out.append(t)
    return out or list(DEFAULT_TAGS)


def tags_intersect(scenario_tags: Iterable[str], selected: Iterable[str]) -> bool:
    """True if any selected tag matches any of the scenario's tags."""
    return bool(set(scenario_tags) & set(selected))


# ── Throw-away user fixture ───────────────────────────────────────────────
@asynccontextmanager
async def throwaway_user(prefix: str = "bench") -> AsyncIterator[str]:
    """Yield a unique user id, drop the row + every user-scoped artefact
    on exit so re-runs stay idempotent on a shared SQLite file.

    The cleanup list tracks the tables a bench scenario is realistically
    going to populate. Extending it is fine — the deletes are guarded
    by ``user_id == uid`` so other users' data stays untouched.
    """
    # Imports are deferred so the helper is safe to import from a context
    # that hasn't yet bootstrapped `sys.path` for `import app...`.
    from app.database import async_session, init_db
    from app.models.user import User
    from sqlalchemy import delete, select

    await init_db()
    uid = f"{prefix}_{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        db.add(User(
            id=uid,
            username=f"{prefix}_{uid[-8:]}",
            email=f"{uid}@bench.local",
            hashed_password="x",
        ))
        await db.commit()
    try:
        yield uid
    finally:
        await _cleanup_user(uid)


# Tables wiped by ``throwaway_user`` on exit. Each row needs a
# ``user_id`` column. Order matters where FK references exist : skills
# (children of failure_cases via ``learned_skill_id``) come before
# failure_cases so we don't break the nullable FK if the scenario
# crashed mid-run. Conversations come LAST because most other tables
# hold a ``conversation_id`` FK that's NOT a real SQL FK in SQLite —
# we just want to leave it in a coherent state for debug.
#
# NOTE: ``MissionCritique`` is NOT in this list — it has no ``user_id``
# column (only ``mission_id``), so the generic ``user_id == uid`` delete
# could never match it. Missions + their critiques are handled by
# ``_cleanup_missions`` below, keyed on ``Mission.user_id``.
_CLEANUP_MODELS: tuple[tuple[str, str], ...] = (
    ("app.models.learned_skill",      "LearnedSkill"),
    ("app.models.failure_case",       "FailureCase"),
    ("app.models.hitl_refusal",       "HitlRefusal"),
    ("app.models.hitl_preference",    "HitlPreference"),
    ("app.models.hallucination_block","HallucinationBlock"),
    ("app.models.provider_switch",    "ProviderSwitch"),
    ("app.models.user_state",         "UserState"),
    ("app.models.conversation",       "Conversation"),
)


async def _cleanup_missions(uid: str) -> None:
    """Drop a user's missions + their critiques (FK-aware).

    ``MissionCritique`` references ``missions.id`` with an ``ondelete=
    CASCADE`` clause, but SQLite does NOT enforce FKs unless
    ``PRAGMA foreign_keys=ON`` is set per-connection — which we don't
    rely on here. So we delete the children explicitly first, then the
    missions. Both are scoped to the throw-away user, so no other data
    is touched. Best-effort: a schema mismatch on either table is
    swallowed rather than stranding the rest of the cleanup.
    """
    from app.database import async_session
    from sqlalchemy import delete, select

    try:
        from app.models.mission import Mission
        from app.models.mission_critique import MissionCritique
    except Exception:
        return  # missions not present in this build — nothing to clean

    try:
        async with async_session() as db:
            mission_ids = (await db.execute(
                select(Mission.id).where(Mission.user_id == uid)
            )).scalars().all()
            if mission_ids:
                await db.execute(
                    delete(MissionCritique).where(
                        MissionCritique.mission_id.in_(mission_ids)
                    )
                )
                await db.execute(delete(Mission).where(Mission.user_id == uid))
                await db.commit()
    except Exception:
        # Schema mismatch / partial state — best effort, keep going.
        return


async def _cleanup_user(uid: str) -> None:
    """Wipe every user-scoped artefact then drop the user row itself.

    Each table is handled in its own session so a single import error
    or schema-mismatch failure cannot leave the outer session in a
    rolled-back state and strand the rest of the cleanups.
    """
    import importlib
    from app.database import async_session
    from app.models.user import User
    from sqlalchemy import delete, select

    # Missions + critiques first (FK-aware, keyed on Mission.user_id).
    await _cleanup_missions(uid)

    for mod_name, cls_name in _CLEANUP_MODELS:
        try:
            cls = getattr(importlib.import_module(mod_name), cls_name)
        except Exception:
            # Module not present in this build (e.g. running against
            # an older DB schema in tests) — skip silently.
            continue
        try:
            async with async_session() as db:
                await db.execute(delete(cls).where(cls.user_id == uid))
                await db.commit()
        except Exception:
            # Schema mismatch on this one table — best effort, keep going.
            continue

    # Finally drop the User row itself.
    try:
        async with async_session() as db:
            u = (await db.execute(
                select(User).where(User.id == uid)
            )).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
                await db.commit()
    except Exception:
        pass


# ── PII anonymisation (regex pass — robust for the mining script) ─────────
_EMAIL_RE  = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE  = re.compile(r"\+?\d[\d\s().-]{7,}\d")          # rough FR/intl
_IBAN_RE   = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_CARD_RE   = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_GMAPS_RE  = re.compile(r"https?://(?:www\.)?google\.[a-z.]+/maps[^\s)]+")
_URL_RE    = re.compile(r"https?://\S+")


def anonymise_text(text: str | None) -> str:
    """Best-effort regex-only PII scrub. Use for ``mission_critique`` /
    ``main_issue`` fields before saving them into a scenario file.

    Removes : emails, phone numbers, IBAN, credit cards, Google Maps
    links, generic URLs. Replaces each match with a stable placeholder
    so the scenario remains human-readable.

    Does NOT scrub proper nouns — those need an LLM pass. The mining
    script can optionally chain a Mistral call after this for full
    anonymisation, but the regex pass is enough for the J1 baseline.
    """
    if not text:
        return text or ""
    text = _EMAIL_RE.sub("<email>",  text)
    text = _IBAN_RE.sub("<iban>",    text)
    text = _CARD_RE.sub("<card>",    text)
    text = _GMAPS_RE.sub("<maps>",   text)
    text = _URL_RE.sub("<url>",      text)
    text = _PHONE_RE.sub("<phone>",  text)
    return text


# ── Check-dict → result-shape helper ──────────────────────────────────────
def from_checks(checks: dict[str, bool], **extra) -> dict:
    """Convert a ``{"check_name": bool}`` dict into the runner's expected
    result shape.

    Returns ::

        {
          "pass": <all checks True>,
          "checks": {...},                  # mirror for the markdown digest
          "failed_checks": ["..."],         # only when there's a failure
          **extra,                          # caller's own metadata
        }
    """
    all_pass = all(checks.values())
    payload: dict = {"pass": all_pass, "checks": dict(checks), **extra}
    if not all_pass:
        payload["failed_checks"] = [k for k, v in checks.items() if not v]
    return payload


# ── Mission + critique seeding (for critique-replay scenarios) ─────────────
async def seed_mission_with_critique(
    uid: str,
    *,
    status: str,
    goal: str,
    critic_model: str,
    quality_score: int,
    honest_completion: bool,
    wasted_effort: bool,
    user_should_have_been_warned: bool,
    main_issue: str | None,
    tier_llm: str | None = None,
    prompt_version: str = "benchv1",
) -> tuple[str, int]:
    """Insert a terminal ``Mission`` + its ``MissionCritique`` for ``uid``.

    Returns ``(mission_id, critique_id)``. Both rows are reclaimed by
    ``throwaway_user`` on context exit (see ``_cleanup_missions``), so a
    scenario doesn't need its own teardown.

    Mirrors how the real ``mission_critic.py`` cron writes a critique
    (``critic_run_at`` stamped on the mission, one critique row, terminal
    status). ``main_issue`` is passed through ``anonymise_text`` defensively
    even though synthetic catalogue issues carry no real PII — so the
    helper stays safe if a caller ever feeds it a mined string.
    """
    from datetime import datetime, timezone

    from app.database import async_session
    from app.models.mission import Mission
    from app.models.mission_critique import MissionCritique

    now = datetime.now(timezone.utc)
    terminal = status in ("completed", "failed", "aborted")
    async with async_session() as db:
        mission = Mission(
            user_id=uid,
            title=(goal or "bench mission")[:120],
            goal=goal,
            status=status,
            source="autonomous",
            started_at=now,
            completed_at=now if terminal else None,
            critic_run_at=now,
        )
        db.add(mission)
        await db.flush()          # populate the uuid PK
        mission_id = mission.id

        critique = MissionCritique(
            mission_id=mission_id,
            critic_model=critic_model,
            quality_score=quality_score,
            honest_completion=honest_completion,
            wasted_effort=wasted_effort,
            user_should_have_been_warned=user_should_have_been_warned,
            main_issue=anonymise_text(main_issue) if main_issue else None,
            prompt_version=prompt_version,
        )
        db.add(critique)
        await db.flush()          # populate the autoincrement PK
        critique_id = critique.id

        await db.commit()
        return mission_id, critique_id
