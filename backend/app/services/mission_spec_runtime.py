# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/mission_spec_runtime.py
# @brief      Sprint 4c J2 — exécution d'une mission structurée : plan
#             déterministe, expansion foreach, statuts par step/item,
#             protocole EDGE_CASE et application des handlers.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
# =============================================================================
"""Spec-driven mission execution helpers.

Consommé par ``agent/missions/nodes.py`` — tout le comportement spec est
gardé derrière ``plan_json["from_spec"]`` : une mission legacy (goal seul)
ne passe JAMAIS ici, zéro régression possible.

Philosophie (backlog 4c) : le LLM reste dans la boucle — la spec CADRE
l'exécution. Concrètement :

- le plan n'est plus généré par le planner LLM : il EST la spec ;
- un step ``foreach`` est étendu paresseusement en items (extraction LLM
  une seule fois, depuis l'output du step source), chaque item = une
  ligne ``mission_step_runs`` ; un tick traite UN item ;
- l'acteur reçoit la liste des edge-cases déclarés du step et le
  PROTOCOLE : s'il rencontre un cas, il ne bricole pas — il répond
  ``EDGE_CASE: <nom> | <détail>`` et l'évaluateur applique le handler
  (skip note, attente utilisateur, échec franc) ;
- jamais de replan : la spec est le contrat, l'échec répété d'un item est
  géré par ``on_error`` (ou skip automatique après 2 tentatives).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy import select, update

from app.database import async_session
from app.models.mission import Mission, MissionStepRun
from app.services.mission_spec import (
    HandlerCall,
    MissionSpec,
    MissionSpecError,
    SpecStep,
    parse_mission_spec,
)

logger = logging.getLogger(__name__)

EDGE_MARKER = "EDGE_CASE:"
MAX_FOREACH_ITEMS = 200
# Plafond de l'archive d'une sortie d'etape (`MissionStepRun.output`).
# C'est elle que relit un `foreach` pour construire ses items : la couper
# trop court, c'est perdre des items en silence. Constante UNIQUE — elle
# etait doublee d'un `[:1500]` cote appelant, et la valeur annoncee n'etait
# donc pas la valeur obtenue.
STEP_OUTPUT_ARCHIVE_CHARS = 6000
# Au-delà de N tentatives sur un item sans handler on_error : skip
# automatique avec note — garantit la vivacité de la mission.
AUTO_SKIP_ATTEMPTS = 2

TERMINAL_RUN_STATUSES = {"done", "skipped", "failed"}


# ── Spec / plan ──────────────────────────────────────────────────────────────


async def load_spec_for_mission(mission_id: str) -> Optional[MissionSpec]:
    """Spec parsée de la mission, None si legacy ou spec illisible."""
    async with async_session() as db:
        spec_yaml = (await db.execute(
            select(Mission.spec_yaml).where(Mission.id == mission_id)
        )).scalar_one_or_none()
    if not spec_yaml:
        return None
    try:
        return parse_mission_spec(spec_yaml)
    except MissionSpecError as exc:
        # Validée à la création — un échec ici signifie une édition
        # manuelle en DB. On le dit, on retombe en legacy.
        logger.error("mission %s : spec_yaml invalide (%s) — exécution legacy", mission_id, exc)
        return None


def build_plan_from_spec(spec: MissionSpec) -> tuple[str, dict]:
    """(plan_text, plan_json) déterministes — AUCUN appel LLM.

    ``plan_json`` reste compatible avec la machinerie existante
    (id/description/status) et embarque le matériel spec (foreach,
    handlers) pour que act/eval soient autonomes dans le checkpoint.
    """
    steps = []
    for s in spec.steps:
        steps.append({
            "id": s.id,
            "description": s.do,
            # `tool_hint` porte le PREMIER outil nommé (la machinerie
            # existante n'en attend qu'un) ; `tools` porte la liste
            # complète, que la sélection lie en entier. Sans ce report, une
            # spec pourrait nommer un outil que personne ne lirait.
            "tool_hint": s.tools[0] if s.tools else None,
            "tools": list(s.tools),
            "foreach": s.foreach,
            "handlers": {
                name: {"action": c.action, "message": c.message}
                for name, c in s.handlers.items()
            },
        })
    plan_json = {"from_spec": True, "steps": steps}
    plan_text = "# Plan (spec structurée)\n\n" + "\n".join(
        f"- [ ] **{s.id}** {s.do.strip().splitlines()[0][:120]}"
        + (f"  *(foreach : {s.foreach})*" if s.foreach else "")
        for s in spec.steps
    )
    return plan_text, plan_json


def is_spec_plan(plan_json: Optional[dict]) -> bool:
    return bool(plan_json and plan_json.get("from_spec"))


# ── Step runs (CRUD minimal) ─────────────────────────────────────────────────


async def ensure_step_run(
    mission_id: str, step_id: str, item_index: int = 0,
    item_value: Optional[str] = None,
) -> MissionStepRun:
    async with async_session() as db:
        existing = (await db.execute(
            select(MissionStepRun).where(
                MissionStepRun.mission_id == mission_id,
                MissionStepRun.step_id == step_id,
                MissionStepRun.item_index == item_index,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return existing
        run = MissionStepRun(
            id=str(uuid.uuid4()), mission_id=mission_id, step_id=step_id,
            item_index=item_index, item_value=item_value, status="pending",
            attempts=0,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run


async def list_step_runs(
    mission_id: str, step_id: Optional[str] = None,
) -> list[MissionStepRun]:
    async with async_session() as db:
        q = select(MissionStepRun).where(MissionStepRun.mission_id == mission_id)
        if step_id is not None:
            q = q.where(MissionStepRun.step_id == step_id)
        q = q.order_by(MissionStepRun.step_id, MissionStepRun.item_index)
        return list((await db.execute(q)).scalars().all())


async def set_step_run_status(
    mission_id: str, step_id: str, item_index: int, *,
    status: str, note: Optional[str] = None, output: Optional[str] = None,
    bump_attempts: bool = False,
) -> None:
    values: dict[str, Any] = {"status": status}
    if note is not None:
        values["note"] = note[:2000]
    if output is not None:
        values["output"] = output[:STEP_OUTPUT_ARCHIVE_CHARS]
    async with async_session() as db:
        if bump_attempts:
            values["attempts"] = MissionStepRun.attempts + 1
        await db.execute(
            update(MissionStepRun).where(
                MissionStepRun.mission_id == mission_id,
                MissionStepRun.step_id == step_id,
                MissionStepRun.item_index == item_index,
            ).values(**values)
        )
        await db.commit()


async def next_pending_run(
    mission_id: str, step_id: str,
) -> Optional[MissionStepRun]:
    """Prochain item à traiter : pending d'abord, puis running (reprise
    après crash de tick — un running orphelin est re-traité)."""
    runs = await list_step_runs(mission_id, step_id)
    for status in ("pending", "running"):
        for r in runs:
            if r.status == status:
                return r
    return None


def step_progress(runs: list[MissionStepRun]) -> tuple[int, int, int]:
    """(terminaux, waiting_user, total) — pour le plan et le viewer."""
    done = sum(1 for r in runs if r.status in TERMINAL_RUN_STATUSES)
    waiting = sum(1 for r in runs if r.status == "waiting_user")
    return done, waiting, len(runs)


# ── Expansion foreach ────────────────────────────────────────────────────────

_EXPAND_PROMPT = """Tu prépares l'itération d'une mission structurée.

Étape source « {source_ref} » — son résultat :
{source_output}

Étape à itérer : « {do} »
Source d'items déclarée : {foreach}

Extrais la LISTE des items sur lesquels itérer. Réponds UNIQUEMENT avec un
tableau JSON de chaînes courtes (un libellé identifiant par item, dans
l'ordre). Maximum {max_items} items. Exemple : ["Acme Corp", "Gamma SARL"]
Si aucun item n'est identifiable, réponds [].
"""


def _strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


async def expand_foreach(
    mission_id: str, user_id: str, step: dict, source_output: str,
) -> list[MissionStepRun]:
    """Extrait les items (UN appel LLM) et crée les lignes step_run.

    Idempotent : si des runs existent déjà pour ce step, ils sont
    retournés tels quels (l'expansion a déjà eu lieu — reprise de tick).
    """
    step_id = step.get("id", "?")
    existing = await list_step_runs(mission_id, step_id)
    if existing:
        return existing

    from app.services.llm_provider import ComplexityTier, get_llm_for_tier

    llm = get_llm_for_tier(ComplexityTier.MEDIUM)
    # `source_ref` doit NOMMER l'étape d'où vient `source_output`. On y
    # recopiait le gabarit : le prompt annonçait « Étape source
    # « {{ societes.output }} » », qui n'est le nom de rien. La forme texte
    # libre n'a pas d'étape à nommer — on la laisse telle quelle, c'est
    # bien ce que l'auteur a écrit.
    from app.services.mission_spec import foreach_ref_of

    _brut = step.get("foreach") or "?"
    prompt = _EXPAND_PROMPT.format(
        source_ref=foreach_ref_of(_brut) or _brut,
        source_output=(source_output or "(vide)")[:6000],
        do=(step.get("description") or "")[:400],
        foreach=step.get("foreach") or "?",
        max_items=MAX_FOREACH_ITEMS,
    )
    items: list[str] = []
    try:
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        # content_to_text : sur tier codex (Responses API), content est une
        # liste de blocs → sans aplatissement _strip_fence().strip() casse,
        # l'except plus bas avalerait l'erreur et skipperait le foreach.
        from app.agent.helpers.message_content import content_to_text
        raw = _strip_fence(content_to_text(getattr(response, "content", "")))
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            items = [str(x)[:300] for x in parsed[:MAX_FOREACH_ITEMS] if str(x).strip()]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mission %s : expansion foreach de %s échouée (%s)",
            mission_id, step_id, exc,
        )

    if not items:
        # Pas d'items identifiables : une seule ligne porte la note — le
        # step sera skippé proprement au lieu de bloquer la mission.
        run = await ensure_step_run(mission_id, step_id, 0, None)
        await set_step_run_status(
            mission_id, step_id, 0, status="skipped",
            note="Aucun item identifiable pour l'itération (résultat source vide ?)",
        )
        return await list_step_runs(mission_id, step_id)

    for idx, value in enumerate(items):
        await ensure_step_run(mission_id, step_id, idx, value)
    logger.info(
        "mission %s : foreach %s étendu en %d item(s)", mission_id, step_id, len(items),
    )
    return await list_step_runs(mission_id, step_id)


# ── Protocole EDGE_CASE ──────────────────────────────────────────────────────


def render_item(text: str, item_value: Optional[str]) -> str:
    """Substitue ``{{ item }}`` (espaces tolérés)."""
    if item_value is None:
        return text
    return re.sub(r"\{\{\s*item\s*\}\}", item_value, text)


def edge_protocol_prompt(handlers: dict[str, Any]) -> str:
    """Bloc ajouté au prompt acteur : les cas prévus + le protocole."""
    if not handlers:
        return ""
    lines = []
    for name, call in handlers.items():
        action = call.get("action") if isinstance(call, dict) else call.action
        lines.append(f"  - {name} (traitement prévu : {action})")
    return (
        "\n\nCAS PARTICULIERS PRÉVUS POUR CETTE ÉTAPE :\n"
        + "\n".join(lines)
        + "\n\nPROTOCOLE : si tu constates l'un de ces cas pour l'item courant, "
        "NE FAIS AUCUN appel d'outil et NE BRICOLE PAS de contournement. "
        f"Réponds EXACTEMENT : {EDGE_MARKER} <nom_du_cas> | <explication courte>. "
        "Le système applique alors le traitement prévu."
    )


def parse_edge_case(text: str) -> Optional[tuple[str, str]]:
    """``EDGE_CASE: not_found | rien sur LinkedIn`` → ("not_found", "rien…")."""
    if not text or EDGE_MARKER not in text:
        return None
    after = text.split(EDGE_MARKER, 1)[1].strip()
    if "|" in after:
        name, detail = after.split("|", 1)
    else:
        name, detail = after, ""
    name = name.strip().lower().replace(" ", "_")
    return (name, detail.strip()[:500]) if name else None


def resolve_handler(handlers: dict[str, Any], case_name: str) -> HandlerCall:
    """Handler du cas signalé ; un cas non déclaré dégrade en resume_next
    (le LLM peut signaler un cas imprévu — on journalise et on avance)."""
    raw = handlers.get(case_name)
    if isinstance(raw, dict) and raw.get("action"):
        return HandlerCall(action=raw["action"], message=raw.get("message"))
    if isinstance(raw, HandlerCall):
        return raw
    return HandlerCall(action="resume_next", message=None)


# rétro-référence utilisée par les tests pour vérifier l'export propre
__all__ = [
    "EDGE_MARKER",
    "build_plan_from_spec",
    "edge_protocol_prompt",
    "ensure_step_run",
    "expand_foreach",
    "is_spec_plan",
    "list_step_runs",
    "load_spec_for_mission",
    "next_pending_run",
    "parse_edge_case",
    "render_item",
    "resolve_handler",
    "set_step_run_status",
    "step_progress",
]


# ── J3 — hook ask_user : notification + réponse + reprise ───────────────────


async def notify_ask_user(
    mission_id: str, user_id: str, step_id: str, item_index: int,
    question: str, item_value: Optional[str] = None,
) -> None:
    """Notifie l'utilisateur qu'une mission attend sa réponse.

    Multicanal best-effort, calqué sur ``_notify_terminal`` du heartbeat :
    chaque canal est isolé — l'échec de l'un n'empêche ni les autres ni la
    mission de continuer sur les items suivants.

    1. **Web UI** : event ``mission_question`` poussé sur TOUTES les
       sockets du user (fan-out B-6) — le viewer J4 affiche ⏸ + le champ
       de réponse.
    2. **ntfy** : push mobile si ``NTFY_URL`` est configurée.
    3. **Telegram** : DM si la mission vient de Telegram (source_ref).
    """
    # Cycle PII missions — la question DOIT arriver en clair à
    # l'utilisateur (ceinture défensive, no-op si l'invariant tient).
    try:
        from app.agent.missions.pii import mission_filter
        _sf = mission_filter(mission_id)
        question = _sf.deanonymize(question or "")
        if item_value:
            item_value = _sf.deanonymize(item_value)
    except Exception:  # noqa: BLE001 — la notification prime
        pass
    async with async_session() as db:
        mission = (await db.execute(
            select(Mission).where(Mission.id == mission_id)
        )).scalar_one_or_none()
    title = getattr(mission, "title", mission_id)

    # 1. Web (fan-out toutes sockets)
    try:
        from app.services import ws_registry
        payload = json.dumps({
            "type": "mission_question",
            "mission_id": mission_id,
            "mission_title": title,
            "step_id": step_id,
            "item_index": item_index,
            "item_value": item_value,
            "question": question,
        }, ensure_ascii=False)
        delivered = await ws_registry.send_text_all(user_id, payload)
        logger.info(
            "mission %s : question ask_user poussée (ws=%d socket(s))",
            mission_id, delivered,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mission %s : push ws de la question échoué : %s", mission_id, exc)

    # 2. ntfy push
    import os
    ntfy_url = os.environ.get("NTFY_URL")
    if ntfy_url:
        try:
            import httpx

            from app.services.ntfy_headers import ascii_header
            body = question if not item_value else f"{item_value} — {question}"
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    ntfy_url,
                    headers={
                        # ascii_header : ce Title (« » + —) n'était JAMAIS
                        # parti — httpx encode les en-têtes en ASCII.
                        "Title": ascii_header(f"Mission « {title} » — question")[:120],
                        "Tags": "question",
                        "Priority": "high",
                    },
                    content=body[:500].encode("utf-8"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mission %s : ntfy question échoué : %s", mission_id, exc)

    # 3. Telegram (si la mission vient de Telegram)
    if (
        mission is not None
        and getattr(mission, "source", "") == "channel"
        and (getattr(mission, "source_ref", "") or "").startswith("telegram:")
    ):
        try:
            tg_chat_id = int(mission.source_ref.split(":", 1)[1])
            from app.channels import telegram_bot as _tb
            if _tb._bot_app is not None:
                text = (
                    f"⏸ Mission « {title} » — question :\n\n{question}\n\n"
                    "Réponds depuis la page Missions de l'interface web."
                )
                # parse_mode=None volontaire (texte user-controlled)
                await _tb._bot_app.bot.send_message(chat_id=tg_chat_id, text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mission %s : Telegram question échoué : %s", mission_id, exc)


def answer_context(run: Any) -> str:
    """Bloc injecté au prompt acteur quand l'item retraité porte une
    réponse utilisateur — c'est la moitié « reprise » du mode chat
    automatisé."""
    answer = getattr(run, "answer", None)
    if not answer:
        return ""
    question = getattr(run, "note", None) or "(question précédente)"
    return (
        f"\n\nRÉPONSE DE L'UTILISATEUR (à la question « {question} ») : "
        f"{answer}\nTiens-en compte pour traiter cet item — ne repose pas "
        f"la même question."
    )


async def submit_answer(
    mission_id: str, step_id: str, item_index: int, answer: str,
) -> Optional[MissionStepRun]:
    """Enregistre la réponse et relance l'item : waiting_user → pending,
    tentatives remises à zéro (la réponse mérite une chance fraîche),
    next_tick immédiat sur la mission. None si l'item n'existe pas ou
    n'attend pas de réponse."""
    async with async_session() as db:
        run = (await db.execute(
            select(MissionStepRun).where(
                MissionStepRun.mission_id == mission_id,
                MissionStepRun.step_id == step_id,
                MissionStepRun.item_index == item_index,
            )
        )).scalar_one_or_none()
        if run is None or run.status != "waiting_user":
            return None
        run.answer = answer[:4000]
        run.status = "pending"
        run.attempts = 0
        await db.commit()
        await db.refresh(run)

    # Reprise immédiate : la mission redevient due au prochain beat.
    try:
        from app.services.mission_heartbeat import schedule_first_tick
        await schedule_first_tick(mission_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mission %s : next_tick immédiat non posé (%s) — reprise au "
            "prochain tick planifié", mission_id, exc,
        )
    logger.info(
        "mission %s : réponse reçue pour %s[%d] — item relancé",
        mission_id, step_id, item_index,
    )
    return run
