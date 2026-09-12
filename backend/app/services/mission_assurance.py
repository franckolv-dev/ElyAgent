"""Explicit completion checks and durable receipts. No LLM judges its own work."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from app.database import async_session
from app.models.mission import Mission
from app.models.autonomy import MissionAssurance, ActionReceipt

logger = logging.getLogger(__name__)


class Check(BaseModel):
    kind: Literal["tool_success", "response_contains", "source_count"]
    value: str = Field("", max_length=500)
    count: int = Field(1, ge=1, le=30)

    @model_validator(mode="after")
    def valid_value(self):
        self.value = self.value.strip()
        if self.kind != "source_count" and not self.value:
            raise ValueError("Précise le résultat attendu ou l’outil à vérifier.")
        if self.kind == "tool_success" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", self.value):
            raise ValueError("Nom d’outil invalide.")
        return self


def dependency(tool_name):
    # Use the actual declared tools, not an approximate name prefix.
    from app.skills.builtin import desktop_skill
    from app.agent.tools import browser_extension_tool

    for module, service in [(desktop_skill, "system"), (browser_extension_tool, "chrome")]:
        if any(getattr(tool, "name", None) == tool_name for tool in vars(module).values()):
            return service
    return None


def connected(user_id, service):
    from app.services import desktop_registry, browser_extension_registry

    return (desktop_registry if service == "system" else browser_extension_registry).is_connected(user_id)


async def suspend(mid, reason, question):
    async with async_session() as db:
        m = await db.get(Mission, mid)
        if not m or m.status not in {"running", "planning"}:
            return
        a = await db.get(MissionAssurance, mid)
        if a is None:
            a = MissionAssurance(mission_id=mid, user_id=m.user_id)
            db.add(a)
        a.waiting_for = reason
        a.waiting_since = datetime.now(timezone.utc)
        m.status = "paused" if reason in {"chrome", "system"} else "waiting_user"
        m.pending_question = question
        m.question_asked_at = datetime.now(timezone.utc)
        m.next_tick_at = None
        await db.commit()
    if reason not in {"chrome", "system"}:
        await notify_blocked(mid, question)


async def notify_blocked(mid, question):
    # Local notification only; delivery channels retain their existing settings.
    from app.services.autonomy_policy import should_notify
    from app.models.conversation import Conversation, Message

    async with async_session() as db:
        m = await db.get(Mission, mid)
        if not m or not await should_notify(m.user_id, "blocked"):
            return
        conv = (
            await db.execute(
                select(Conversation)
                .where(Conversation.user_id == m.user_id, Conversation.title == "[Missions] Notifications")
                .limit(1)
            )
        ).scalar_one_or_none()
        if conv is None:
            conv = Conversation(user_id=m.user_id, title="[Missions] Notifications")
            db.add(conv)
            await db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content=f"Mission « {m.title} » : décision attendue. {question}",
            )
        )
        await db.commit()


async def preflight(mid, user_id, tool_name):
    async with async_session() as db:
        m = await db.get(Mission, mid)
        if m is None:
            # Aucune ligne : rien à suspendre ni à accuser (tests, mission
            # supprimée pendant son tick). Une mission d'un AUTRE utilisateur
            # reste bloquée ci-dessous.
            logger.warning("preflight : mission %s sans ligne en base, assurance inactive", str(mid)[:8])
            return None
        if m.user_id != user_id:
            return "Mission introuvable."
        # Un brouillon dispatché à la main (tests) n'est pas une mission arrêtée.
        if m.status not in {"draft", "planning", "running"}:
            return "Mission suspendue. N’exécute plus d’action."
    dep = dependency(tool_name)
    if dep and not connected(user_id, dep):
        text = f"Mission en attente de {'Chrome' if dep == 'chrome' else 'Système'}. Reprise automatique à la reconnexion (maximum 24 h)."
        await suspend(mid, dep, text)
        return text
    return None


async def reserve(mid, user_id, name, args):
    """Return (receipt_id, previous). Reserve before sending any external write."""
    from app.agent.tool_nature import effect_of

    effect = effect_of(name) or "UNKNOWN"
    async with async_session() as db:
        m = await db.get(Mission, mid)
        if m is None:
            return None, None
        if m.user_id != user_id:
            raise ValueError("Mission introuvable")
        key = (
            hashlib.sha256(
                json.dumps([str(m.started_at), name, args], sort_keys=True, default=str).encode()
            ).hexdigest()
            if effect != "LECTURE"
            else uuid.uuid4().hex
        )
        row = (
            await db.execute(
                select(ActionReceipt).where(ActionReceipt.mission_id == mid, ActionReceipt.action_key == key)
            )
        ).scalar_one_or_none()
        if row and row.status == "retry_allowed":
            row.status = "started"
            await db.commit()
            return row.id, None
        if row:
            return None, {"status": row.status, "result": row.result}
        row = ActionReceipt(mission_id=mid, user_id=user_id, tool_name=name, action_key=key, effect=effect)
        db.add(row)
        try:
            await db.commit()
            return row.id, None
        except IntegrityError:
            # Another worker reserved it. Never execute on a uniqueness race.
            return None, {"status": "started", "result": ""}


async def finish(receipt_id, ok, safe_result):
    if not receipt_id:
        return
    async with async_session() as db:
        r = await db.get(ActionReceipt, receipt_id)
        if r:
            r.status = "success" if ok else ("failed" if r.effect == "LECTURE" else "uncertain")
            r.result = str(safe_result)[:16000]
            await db.commit()
    if r and r.status == "uncertain":
        await suspend(
            r.mission_id,
            "uncertain_action",
            "L’exécution de "
            + r.tool_name
            + " est incertaine. Vérifie son effet dans Autonomie → Suivi avant tout nouvel essai.",
        )


async def requirements(mid):
    async with async_session() as db:
        a = await db.get(MissionAssurance, mid)
        if not a or not json.loads(a.checks_json):
            return ""
        return (
            "\nCritères obligatoires de réussite (vérifiés séparément) :\n"
            + a.checks_json
            + "\nLe succès d’un outil est son accusé réel, pas une livraison garantie chez le destinataire.\nDernières vérifications : "
            + a.results_json
        )


async def verify(mid, summary):
    async with async_session() as db:
        a = await db.get(MissionAssurance, mid)
        rows = (await db.execute(select(ActionReceipt).where(ActionReceipt.mission_id == mid))).scalars().all()
        m = await db.get(Mission, mid)
        if m and m.started_at:
            since = m.started_at.replace(tzinfo=timezone.utc)
            rows = [r for r in rows if r.created_at.replace(tzinfo=timezone.utc) >= since]
        checks = json.loads(a.checks_json) if a else []
        results = []
        for c in checks:
            if c["kind"] == "tool_success":
                evidence = [r.id for r in rows if r.tool_name == c["value"] and r.status == "success"]
                ok = len(evidence) >= c["count"]
            elif c["kind"] == "response_contains":
                ok = c["value"].casefold() in summary.casefold()
                evidence = ["Réponse finale"] if ok else []
            else:
                # Count references returned by successful reading tools, not invented URLs.
                urls = set()
                for r in rows:
                    if r.effect == "LECTURE" and r.status == "success":
                        urls.update(re.findall(r'https?://[^\s<>"\)]+', r.result))
                cited = [u for u in urls if u in summary]
                evidence = sorted(cited)
                ok = len(cited) >= c["count"]
            results.append({**c, "passed": ok, "evidence": evidence})
        uncertain = [r.id for r in rows if r.effect != "LECTURE" and r.status in {"started", "uncertain"}]
        if uncertain:
            results.append({"kind": "uncertain_action", "passed": False, "evidence": uncertain})
        if a:
            a.results_json = json.dumps(results, ensure_ascii=False)
            a.verified_at = datetime.now(timezone.utc)
            await db.commit()
        return all(r["passed"] for r in results), results


async def guard_completion(mid, summary):
    ok, results = await verify(mid, summary)
    if ok:
        return
    async with async_session() as db:
        a = await db.get(MissionAssurance, mid)
        m = await db.get(Mission, mid)
        if not m or m.status not in {"planning", "running"}:
            raise ValueError("Mission inactive")
        if a is None:
            a = MissionAssurance(mission_id=mid, user_id=m.user_id)
            db.add(a)
        a.results_json = json.dumps(results, ensure_ascii=False)
        a.retries = (a.retries or 0) + 1
        # One corrective passage; uncertain effects always need human review.
        if a.retries <= 1 and not any(r["kind"] == "uncertain_action" for r in results):
            m.next_tick_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            m.status = "running"
        else:
            m.status = "waiting_user"
            m.next_tick_at = None
            a.waiting_for = "verification"
            a.waiting_since = datetime.now(timezone.utc)
            m.pending_question = "Les critères de réussite ne sont pas tous vérifiés. Consulte Autonomie → Suivi pour les preuves manquantes."
            m.question_asked_at = datetime.now(timezone.utc)
        await db.commit()
    if m.status == "waiting_user":
        await notify_blocked(mid, m.pending_question)
    raise ValueError("Critères de réussite non vérifiés")


async def resume_connected():
    async with async_session() as db:
        rows = (
            await db.execute(
                select(MissionAssurance, Mission)
                .join(Mission, Mission.id == MissionAssurance.mission_id)
                .where(Mission.status == "paused", MissionAssurance.waiting_for.in_(["chrome", "system"]))
            )
        ).all()
        now = datetime.now(timezone.utc)
        for a, m in rows:
            since = a.waiting_since.replace(tzinfo=timezone.utc) if a.waiting_since else now
            if now - since > timedelta(hours=24):
                m.status = "waiting_user"
                a.waiting_for = "recovery_expired"
                m.pending_question = "Connexion absente depuis 24 h. Vérifie l’intégration puis reprends la mission."
            elif connected(m.user_id, a.waiting_for):
                m.status = "planning"
                m.next_tick_at = now
                m.pending_question = None
                a.waiting_for = None
                a.waiting_since = None
        await db.commit()
