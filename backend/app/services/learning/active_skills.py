# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/learning/active_skills.py
# @brief      Sprint 4b Phase 4.b — read + format active LearnedSkills for the agent prompt
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# =============================================================================
"""Active skills query + prompt formatter — Sprint 4b Phase 4.b.

Once an admin has promoted a `candidate` LearnedSkill to `active`
(Phase 4.a), it becomes part of the agent's procedural memory: its
short description gets injected into the system prompt every turn
(via memory_snapshot), and the agent can pull its full content on
demand via the new `skill_view` tool.

Le contenu est CHARGÉ, plus « révélé progressivement » (28/07/2026)
-------------------------------------------------------------------
Le schéma d'origine était : description dans le prompt, procédure complète
récupérée à la demande par ``skill_view(name)``. Mesuré en production :
**0 appel à ``skill_view`` depuis toujours**, pour 26 playbooks actifs et
0 usage. Le tool EST bindé — le modèle le voit et ne l'appelle jamais.

On a donc arrêté de parier sur cette décision : la procédure des playbooks
les plus pertinents est écrite directement dans le prompt
(``PLAYBOOK_CONTENT_BUDGET_CHARS``), et ceux qui ne tiennent pas dans le
budget restent nommés — la troncature est annoncée, jamais silencieuse.

C'est ce que fait Hermes : ``skill_preprocessing.py`` matérialise le contenu
du SKILL.md ; il n'existe pas d'étape « le modèle décide d'ouvrir ».

``skill_view`` reste disponible pour consulter un playbook non détaillé —
il n'est simplement plus le chemin nominal. Il continue d'incrémenter
``use_count`` / ``last_used_at`` pour le curateur.

Les ``python_tool``, eux, sont DÉJÀ bindés : seul leur nom est annoncé,
jamais leur code.

The block is added to the existing `<user_state>` + memory_block in
`memory_snapshot.build_memory_snapshot`. Best-effort: any DB hiccup
returns an empty block (the agent runs without procedural memory
just fine — that's the pre-Phase-4 baseline).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.learned_skill import LearnedSkill, SkillContentFormat, SkillStatus

logger = logging.getLogger(__name__)


# Cap on number of active skills injected per turn. 20 skills ×
# ~50 tokens each = ~1k tokens, an acceptable fraction of the
# ~23k system prompt budget. Tune via `LEARNED_SKILLS_PROMPT_MAX` env.
MAX_SKILLS_IN_PROMPT = 20

# Budget de CONTENU de playbook chargé dans le prompt (28/07/2026).
#
# Jusqu'ici on listait nom + description et on demandait au modèle d'appeler
# ``skill_view`` pour lire la procédure. Mesuré en production : **0 appel à
# ``skill_view`` depuis toujours**, pour 26 playbooks actifs et 0 usage. Le
# tool EST bindé (``tool_sets.py``) — le modèle le voit et ne l'appelle
# jamais. On arrête donc de parier sur cette décision et on charge la
# procédure directement, comme le fait Hermes (``skill_preprocessing.py``
# matérialise le SKILL.md ; il n'y a pas d'étape « le modèle décide d'ouvrir »).
#
# Calibré sur la mesure : chez Franck, 16 playbooks actifs, 15 462 caractères
# de contenu au total, le plus gros à 1 595. 8 000 laisse donc passer les 5 à
# 8 procédures les plus pertinentes ENTIÈRES — la sélection amont ayant déjà
# classé la liste. Le snapshot étant gelé par conversation, c'est payé UNE
# fois, dans le préfixe cacheable.
PLAYBOOK_CONTENT_BUDGET_CHARS = 8_000

# C4-3 — grace window: a skill promoted less than N days ago is ALWAYS
# part of the injected selection (bypasses the use_count sort). Fixes the
# cold-start where a freshly promoted tool (use_count=0) was the first
# one cut from the prompt — seen live 2026-07-19 with levenshtein_distance.
GRACE_WINDOW_DAYS = 7

# Safety cap on the SQL fetch — selection happens in RAM on the full
# active set (a few dozen rows at most today).
_FETCH_CAP = 200

# Hybrid relevance recipe shared with find_tool + mission tool re-rank
# (leçon FR cross-lingual : le lexical MÈNE, le cosine AFFINE).
_SEM_WEIGHT = 0.5


def _norm(s: str) -> str:
    """Lowercase + strip accents — same recipe as find_tool/_norm."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _lexical_score(query: str, text: str) -> float:
    """Token-overlap [0..1] of the normalized query against ``text``.

    Pure + cheap (no encoder): the fraction of significant query tokens
    (≥ 3 chars after accent-stripping) present in the normalized text.
    """
    q_tokens = [tok for tok in _norm(query).split() if len(tok) >= 3]
    if not q_tokens:
        return 0.0
    text_norm = _norm(text)
    return sum(1 for tok in q_tokens if tok in text_norm) / len(q_tokens)


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes — coerce to aware UTC for compares."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _grace_days() -> int:
    try:
        return int(os.getenv("LEARNED_SKILLS_GRACE_DAYS", GRACE_WINDOW_DAYS))
    except (TypeError, ValueError):
        return GRACE_WINDOW_DAYS


def _in_grace(skill, now: datetime) -> bool:
    """True when the skill was promoted less than the grace window ago.

    ``promoted_at`` is NULL for rows that predate the column (bundled
    seeds, historical promotions without backfill) → no grace, by design.
    """
    promoted = _as_aware(getattr(skill, "promoted_at", None))
    if promoted is None:
        return False
    return (now - promoted) < timedelta(days=_grace_days())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# Module-level cache of skill-description embeddings — keyed by skill id,
# invalidated per-row when the embedded text changes (edit/regeneration).
_skill_vectors: dict[str, tuple[str, list[float]]] = {}


async def _semantic_scores(query: str, skills: list) -> dict[str, float]:
    """skill_id → cosine(query, "name: description"). Best-effort.

    Only called when the active set overflows the injection cap (so the
    encoder never loads for the common small-catalog case). The query
    vector is LRU-cached by MemoryInfra (the memory stores embed the same
    user_query earlier in the turn → usually a cache hit); description
    vectors are batch-encoded off the event loop and cached per skill.
    Returns {} when the encoder is unavailable → lexical-only ranking.
    """
    try:
        from app.services.memory import get_memory_infra

        infra = get_memory_infra()
        texts = {s.id: f"{s.name}: {(s.description or '')}" for s in skills}
        missing = [
            (sid, text) for sid, text in texts.items()
            if _skill_vectors.get(sid, ("", None))[0] != text
        ]
        if missing:
            vecs = await asyncio.to_thread(
                lambda: [v.tolist() for v in infra.encoder.embed([t for _, t in missing])]
            )
            for (sid, text), vec in zip(missing, vecs):
                _skill_vectors[sid] = (text, vec)
        qv = await infra.embed(query)
        return {
            sid: _cosine(qv, _skill_vectors[sid][1])
            for sid in texts
            if sid in _skill_vectors
        }
    except Exception as exc:  # noqa: BLE001 — le sémantique est optionnel
        logger.debug("active_skills: semantic scoring unavailable (%s)", exc)
        return {}


async def get_active_skills_for_user(
    user_id: str,
    limit: int = MAX_SKILLS_IN_PROMPT,
    query: str | None = None,
) -> list[LearnedSkill]:
    """Return up to ``limit`` active LearnedSkills for ``user_id``.

    Selection (C4-3 — « injection intelligente ») :

    1. **Grace window** — skills promoted < GRACE_WINDOW_DAYS ago are
       always selected, newest first, at the HEAD of the list (salience:
       the tool the user just validated must be visible to the model).
    2. **Relevance** — when the active set overflows ``limit`` and a
       ``query`` is given (the conversation-opening user message — the
       snapshot is frozen per conversation), the remaining slots are
       re-ranked by hybrid score `lexical + 0.5 × cosine` (cosine is
       best-effort; scoreless ties keep the legacy order below).
    3. **Legacy usage sort** — `use_count desc, last_used_at desc,
       created_at desc`: the pre-C4-3 behaviour, still the base order.

    Deterministic for a given (rows, query) → the frozen snapshot stays
    byte-stable for the whole conversation (prompt-cache friendly).

    Best-effort: a DB outage returns an empty list, the caller will
    just inject an empty block.
    """
    if not user_id:
        return []
    try:
        async with async_session() as db:
            result = await db.execute(
                select(LearnedSkill)
                .where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
                .order_by(
                    LearnedSkill.use_count.desc(),
                    LearnedSkill.last_used_at.desc().nulls_last(),
                    LearnedSkill.created_at.desc(),
                )
                .limit(_FETCH_CAP)
            )
            rows = list(result.scalars().all())
    except Exception as exc:
        logger.debug("get_active_skills_for_user failed (%s) — returning []", exc)
        return []

    if not rows:
        return []

    now = datetime.now(timezone.utc)
    grace = [s for s in rows if _in_grace(s, now)]
    grace.sort(
        key=lambda s: _as_aware(s.promoted_at) or now,
        reverse=True,
    )
    grace = grace[:limit]
    grace_ids = {s.id for s in grace}
    others = [s for s in rows if s.id not in grace_ids]

    if len(rows) > limit and query:
        sem = await _semantic_scores(query, others)
        scored = [
            (
                _lexical_score(query, f"{s.name} {s.description or ''}")
                + _SEM_WEIGHT * sem.get(s.id, 0.0),
                idx,
                s,
            )
            for idx, s in enumerate(others)
        ]
        # Score desc ; à score égal, l'ordre legacy (idx asc) tient.
        scored.sort(key=lambda t: (-t[0], t[1]))
        others = [s for _score, _idx, s in scored]

    return grace + others[: max(0, limit - len(grace))]


def _skill_bullet(s, now: datetime) -> str:
    """One list line — description trimmed to a single ≤200-char line,
    freshly promoted skills tagged « (nouveau) » for salience."""
    desc = (getattr(s, "description", "") or "").replace("\n", " ").strip()
    if len(desc) > 200:
        desc = desc[:197] + "…"
    tag = " (nouveau)" if _in_grace(s, now) else ""
    return f"  - {s.name}{tag} : {desc}"


def _split_on_content_budget(playbooks: list) -> tuple[list, list]:
    """Coupe la liste ORDONNÉE en (détaillés, seulement nommés).

    L'ordre d'entrée porte déjà la pertinence (re-rank amont sur la question
    d'ouverture) : on détaille donc en partant du plus pertinent jusqu'à
    épuiser le budget. Au moins un playbook est toujours détaillé — un budget
    trop serré ne doit pas ramener au comportement « liste seule » qu'on est
    précisément en train de supprimer.
    """
    detailed: list = []
    listed_only: list = []
    used = 0
    for s in playbooks:
        body = (getattr(s, "content", "") or "").strip()
        if detailed and used + len(body) > PLAYBOOK_CONTENT_BUDGET_CHARS:
            listed_only.append(s)
            continue
        detailed.append(s)
        used += len(body)
    return detailed, listed_only


def _skill_with_content(s, now: datetime) -> str:
    """Un playbook rendu ENTIER : son titre, puis sa procédure.

    C'est le geste central du correctif — le modèle n'a plus à décider
    d'ouvrir quoi que ce soit, la marche à suivre est sous ses yeux.
    """
    tag = " (nouveau)" if _in_grace(s, now) else ""
    desc = (getattr(s, "description", "") or "").replace("\n", " ").strip()
    # Même plafond que ``_skill_bullet`` : la description est un TITRE, pas la
    # procédure. Une description à rallonge repousserait le vrai contenu hors
    # du budget — c'est ce que pinnait déjà test_format_block_truncates_long_description.
    if len(desc) > 200:
        desc = desc[:197] + "…"
    body = (getattr(s, "content", "") or "").strip()
    head = f"\n### {s.name}{tag}" + (f" — {desc}" if desc else "")
    return f"{head}\n{body}" if body else head


def format_active_skills_block(skills: list[LearnedSkill]) -> str:
    """Render the active-skills section for the system prompt.

    Returns the empty string when there are no skills — the caller
    safely concatenates without polluting the prompt for first-time
    users.

    C4-3 : playbooks and python_tools carry OPPOSITE instructions — a
    playbook is read via `skill_view` then followed; a python_tool is
    already BOUND and must be called directly (the pre-C4-3 single
    header told the model to `skill_view` its own tools, misleading).

    Format :
        <learned_skills>
        Tu as N playbook(s) appris(es) … via `skill_view` … Liste :
          - name-1 : description
        Tu as (aussi) M outil(s) appris … appelle-les DIRECTEMENT … :
          - tool-1 (nouveau) : description
        </learned_skills>
    """
    if not skills:
        return ""
    now = datetime.now(timezone.utc)
    playbooks = [
        s for s in skills
        if getattr(s, "content_format", None) != SkillContentFormat.PYTHON_TOOL
    ]
    tools = [
        s for s in skills
        if getattr(s, "content_format", None) == SkillContentFormat.PYTHON_TOOL
    ]
    lines = ["<learned_skills>"]
    if playbooks:
        n = len(playbooks)
        lines.append(
            f"Tu as {n} playbook{'s' if n > 1 else ''} appris{'es' if n > 1 else 'e'} "
            "(procédures éprouvées). Quand une tâche correspond à l'un d'eux, "
            "SUIS sa procédure — ne l'improvise pas. Les voici :"
        )
        detailed, listed_only = _split_on_content_budget(playbooks)
        for s in detailed:
            lines.append(_skill_with_content(s, now))
        if listed_only:
            # Jamais de troncature silencieuse : un catalogue amputé sans le
            # dire se lit comme un catalogue complet. Les procédures écartées
            # restent NOMMÉES — le modèle peut demander à les consulter.
            lines.append(
                f"\nEt {len(listed_only)} autre{'s' if len(listed_only) > 1 else ''} "
                "playbook(s) non détaillé(s) ici faute de place — demande à les "
                "consulter si l'un d'eux correspond :"
            )
            lines.extend(_skill_bullet(s, now) for s in listed_only)
    if tools:
        m = len(tools)
        pl = "s" if m > 1 else ""
        aussi = "aussi " if playbooks else ""
        lines.append(
            f"Tu as {aussi}{m} outil{pl} appris{pl} — créé{pl} par ta boucle "
            f"d'apprentissage, validé{pl} par l'humain, DÉJÀ bindé{pl} : "
            "appelle-les DIRECTEMENT comme n'importe quel outil (jamais via "
            "`skill_view`). Liste :"
        )
        lines.extend(_skill_bullet(s, now) for s in tools)
    lines.append("</learned_skills>")
    return "\n".join(lines) + "\n"


async def bump_skill_usage(skill_id: str) -> bool:
    """Increment `use_count` and set `last_used_at = now` for one skill.

    Called by the `skill_view` tool right after a successful fetch.
    Best-effort: a write failure logs at DEBUG and returns False.
    The agent still gets the content — only the analytics suffer.
    """
    if not skill_id:
        return False
    try:
        async with async_session() as db:
            result = await db.execute(
                update(LearnedSkill)
                .where(LearnedSkill.id == skill_id)
                .values(
                    use_count=LearnedSkill.use_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            return result.rowcount > 0
    except Exception as exc:
        logger.debug("bump_skill_usage(%s) failed (swallowed): %s", skill_id, exc)
        return False


async def get_active_skill_by_name(
    user_id: str,
    name: str,
) -> LearnedSkill | None:
    """Fetch one active LearnedSkill by (user_id, name). Used by the
    `skill_view` tool. Returns None on not-found OR on DB outage."""
    if not user_id or not name:
        return None
    try:
        async with async_session() as db:
            return (await db.execute(
                select(LearnedSkill).where(
                    LearnedSkill.user_id == user_id,
                    LearnedSkill.name == name,
                    LearnedSkill.status == SkillStatus.ACTIVE,
                )
            )).scalar_one_or_none()
    except Exception as exc:
        logger.debug("get_active_skill_by_name(%s, %s) failed: %s", user_id[:8] if user_id else "?", name, exc)
        return None
