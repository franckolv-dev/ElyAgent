"""Reviewed, reversible tool bindings consumed by both agent model paths.

A binding only exposes existing schemas. User preferences and the execution
and approval gateways still decide which tools may run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from app.database import async_session
from app.models.execution_diagnosis import ExecutionDiagnosis
from app.models.execution_outcome import ExecutionOutcome
from app.models.proposed_patch import ProposedPatch

logger = logging.getLogger(__name__)


def binding_payload(value: str) -> dict:
    """Validate stored data at the boundary, including legacy/manual records."""
    from app.services.learning.patch_service import PatchError
    try:
        payload = json.loads(value)
        if not isinstance(payload, dict) or not isinstance(payload.get('request'), str):
            raise ValueError
        names = payload.get('tools')
        if not normalize_request(payload['request']) or not isinstance(names, list) or not names:
            raise ValueError
        if not all(isinstance(name, str) and re.fullmatch(r'[a-zA-Z0-9_-]+', name) for name in names):
            raise ValueError
        return payload
    except (TypeError, ValueError) as exc:
        raise PatchError('Correctif illisible : rejetez cette proposition et préparez-en une nouvelle.') from exc


def matches_request(requested: str, observed: str) -> bool:
    requested, observed = normalize_request(requested), normalize_request(observed)
    return bool(requested and f' {requested} ' in f' {observed} ')


async def recorded_request(db, user_id: str, outcome) -> str:
    """Read the execution's immutable conversation, never today's task text."""
    from app.models.conversation import Conversation, Message
    if not outcome.conversation_id:
        return ''
    conv = await db.get(Conversation, outcome.conversation_id)
    if not conv or conv.user_id != user_id:
        return ''
    return (await db.execute(select(Message.content).where(
        Message.conversation_id == conv.id, Message.role == 'user',
        Message.created_at <= outcome.created_at,
    ).order_by(Message.created_at.desc()).limit(1))).scalar_one_or_none() or ''


def normalize_request(text: str) -> str:
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+', text))


async def original_request(db, diag, outcome) -> str:
    from app.models.scheduled_task import ScheduledTask
    from app.models.mission import Mission
    if outcome.source == 'scheduled':
        task = await db.get(ScheduledTask, outcome.source_id)
        return task.prompt if task and task.user_id == diag.user_id else ''
    if outcome.source == 'mission':
        mission = await db.get(Mission, outcome.source_id)
        return mission.goal if mission and mission.user_id == diag.user_id else ''
    return await recorded_request(db, diag.user_id, outcome)


def candidate_tools(query: str) -> list[str]:
    from app.skills.registry import get_skill_registry
    from app.agent.nodes import _slm_toolset
    from app.agent.tool_filter import tools_named_in_text
    registry = get_skill_registry()
    tools = _slm_toolset(registry, query) + tools_named_in_text(registry.all_tools, query)
    return sorted({t.name for t in tools})


async def propose_binding(diagnosis_id: int) -> ProposedPatch:
    from app.services.learning.patch_service import PatchError
    async with async_session() as db:
        diag = await db.get(ExecutionDiagnosis, diagnosis_id)
        if not diag or diag.category != 'binding' or diag.status not in {'open', 'validated'}:
            raise PatchError('Cet incident ne permet pas de proposer une liaison d’outils.')
        previous = (await db.execute(select(ProposedPatch).where(
            ProposedPatch.execution_diagnosis_id == diag.id,
            ProposedPatch.status.in_(['proposed', 'applied']),
        ).order_by(ProposedPatch.id.desc()).limit(1))).scalar_one_or_none()
        if previous:
            return previous
        outcome = await db.get(ExecutionOutcome, diag.execution_outcome_id)
        query = await original_request(db, diag, outcome) if outcome else ''
        if not query.strip():
            raise PatchError('La demande d’origine est introuvable. Aucune correction ne peut être appliquée sans sa cible.')
        names = candidate_tools(query)
        from app.skills.preferences_runtime import disabled_tool_names
        disabled = await disabled_tool_names(diag.user_id)
        names = [name for name in names if name not in disabled]
        if not set(names) - {"find_tool", "report_missing_capability", "web_search"}:
            raise PatchError('Aucun outil existant identifié : une intervention est nécessaire, aucun outil ne sera généré.')
        payload = json.dumps({'request': query, 'tools': names}, ensure_ascii=False, indent=2)
        patch = ProposedPatch(
            execution_diagnosis_id=diag.id, user_id=diag.user_id,
            kind='tool_binding', target_type='user_request',
            target_id=hashlib.sha256(normalize_request(query).encode()).hexdigest(),
            field='tools', old_value=None, new_value=payload,
            rationale='Charger ces outils existants dès le début des demandes identiques, dans les nouvelles conversations comme dans les tâches planifiées. Les permissions restent applicables. L’efficacité doit être confirmée par une prochaine exécution.',
            status='proposed', critic_model='catalogue',
        )
        db.add(patch)
        await db.commit()
        await db.refresh(patch)
        return patch


async def change_binding(patch_id: int, *, revert: bool = False) -> ProposedPatch:
    from app.services.learning.patch_service import PatchError
    from app.skills.registry import get_skill_registry
    async with async_session() as db:
        patch = await db.get(ProposedPatch, patch_id)
        expected = 'applied' if revert else 'proposed'
        if not patch or patch.kind != 'tool_binding' or patch.status != expected:
            raise PatchError('Ce correctif ne peut pas être modifié dans son état actuel.')
        diag = await db.get(ExecutionDiagnosis, patch.execution_diagnosis_id)
        if not revert:
            payload = binding_payload(patch.new_value)
            outcome = await db.get(ExecutionOutcome, diag.execution_outcome_id) if diag else None
            current = await original_request(db, diag, outcome) if outcome else ''
            if normalize_request(current) != normalize_request(payload['request']):
                raise PatchError('La demande a changé ou a été supprimée : rejetez cette proposition et préparez-en une nouvelle.')
            from app.skills.preferences_runtime import disabled_tool_names
            disabled = await disabled_tool_names(patch.user_id)
            available = {t.name for t in get_skill_registry().all_tools if t.name not in disabled}
            if not set(payload['tools']) <= available:
                raise PatchError('Le catalogue a changé : certains outils sont désactivés ou ne sont plus disponibles. Proposez un nouveau correctif.')
        patch.status = 'reverted' if revert else 'applied'
        patch.applied_at = None if revert else datetime.now(timezone.utc)
        if diag:
            diag.status = 'open' if revert else 'actioned'
            diag.processed_at = None if revert else patch.applied_at
            diag.resolution = None if revert else 'Liaison d’outils appliquée ; résultat à confirmer lors d’une prochaine exécution.'
        await db.commit()
        await db.refresh(patch)
        return patch


async def tools_for_request(user_id: str, query: str, tools: list) -> list:
    """Read applied repairs on every bind: restarts and undo need no cache flush."""
    if not user_id or not query:
        return []
    async with async_session() as db:
        patches = (await db.execute(select(ProposedPatch).where(
            ProposedPatch.user_id == user_id, ProposedPatch.kind == 'tool_binding',
            ProposedPatch.status == 'applied',
        ))).scalars().all()
    names: set[str] = set()
    for patch in patches:
        from app.services.learning.patch_service import PatchError
        try:
            payload = binding_payload(patch.new_value)
        except PatchError:
            logger.warning('Ignoring malformed binding patch %s', patch.id)
            continue
        # Scheduled jobs may wrap the request with a date or delivery context.
        if matches_request(payload['request'], query):
            names.update(payload['tools'])
    return [tool for tool in tools if tool.name in names]
