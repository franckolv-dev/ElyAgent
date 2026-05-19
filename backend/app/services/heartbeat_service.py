# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/heartbeat_service.py
# @brief      Heartbeat service — autonomous self-check loop for the agent
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
# =============================================================================
"""Heartbeat — autonomous agent loop (Phase 5A, inspired by openclaw).

When a user opts in (heartbeat_enabled=True on their User row), an APScheduler
job invokes the LangGraph agent every `heartbeat_interval_minutes` with a
specific prompt: "read your heartbeat context, act if there is something to
do, otherwise reply HEARTBEAT_OK".

The heartbeat_context is a free-form markdown blob the user maintains
(via PUT /api/heartbeat). It typically describes ongoing tasks, watch-list,
follow-ups — anything the agent should keep an eye on.

Security model
--------------
The heartbeat agent runs through the EXACT same pipeline as a human chat
turn: same supervisor, same tools, same HITL, same tool policies. It is
NOT a backdoor that bypasses guardrails — it just simulates a recurring
"check in" prompt. So actions that would normally trigger HITL still do.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session, engine
from app.models.user import User
from app.services.scheduler import get_scheduler

logger = logging.getLogger(__name__)

HEARTBEAT_PROMPT = (
    "[HEARTBEAT INTERNE — pas une instruction de l'utilisateur]\n\n"
    "Lis ton contexte heartbeat ci-dessous. C'est la liste des choses que "
    "tu surveilles ou des tâches en cours pour cet utilisateur. Si quelque "
    "chose nécessite une action concrète MAINTENANT (un mail à envoyer, un "
    "événement à créer, une recherche à lancer), agis via les outils. "
    "Sinon, réponds simplement « HEARTBEAT_OK » sans rien faire d'autre.\n\n"
    "Règles strictes :\n"
    "- N'invente PAS de tâches qui ne sont pas dans le contexte ci-dessous.\n"
    "- Ne ré-exécute PAS une tâche déjà faite (vérifie via tes outils si besoin).\n"
    "- Si l'utilisateur a écrit du contexte ambigu, réponds HEARTBEAT_OK plutôt "
    "  que de deviner.\n"
    "- Les actions critiques restent soumises à la confirmation HITL — si "
    "  l'utilisateur n'est pas joignable, l'action sera refusée par défaut.\n\n"
    "Contexte heartbeat actuel :\n"
    "─────────────────────────────────────────\n"
    "{context}\n"
    "─────────────────────────────────────────\n"
)


# ──────────────────────────────────────────────────────────────────────────────
# One-shot column migration (heartbeat fields were added in Phase 5A)
# ──────────────────────────────────────────────────────────────────────────────

async def ensure_heartbeat_columns() -> None:
    """Add heartbeat_* columns to the users table if they don't exist.

    `Base.metadata.create_all` only creates missing TABLES, not missing
    COLUMNS on existing tables, so we need a tiny migration step. This is
    portable across SQLite (default) and Postgres.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        bool_default = "0"
    else:
        bool_default = "FALSE"

    columns = [
        ("heartbeat_enabled", f"BOOLEAN NOT NULL DEFAULT {bool_default}"),
        ("heartbeat_interval_minutes", "INTEGER NOT NULL DEFAULT 30"),
        ("heartbeat_context", "TEXT"),
    ]

    async with engine.begin() as conn:
        for col_name, ddl in columns:
            try:
                await conn.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {col_name} {ddl}"
                )
                logger.info("[heartbeat] added column users.%s", col_name)
            except Exception as exc:
                # Already exists, or another harmless error — keep going.
                msg = str(exc).lower()
                if "duplicate" not in msg and "already exists" not in msg:
                    logger.debug(
                        "[heartbeat] ALTER users.%s skipped (%s)", col_name, exc
                    )


# ──────────────────────────────────────────────────────────────────────────────
# Job execution
# ──────────────────────────────────────────────────────────────────────────────

async def _execute_heartbeat(user_id: str) -> None:
    """Invoke the agent for one heartbeat tick on this user."""
    from app.agent.graph import build_agent_graph
    from app.models.conversation import Conversation, Message
    from langchain_core.messages import HumanMessage

    try:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.heartbeat_enabled:
                return
            context = (user.heartbeat_context or "").strip() or "(vide)"
            google_credentials = user.google_credentials or ""

        prompt = HEARTBEAT_PROMPT.format(context=context)

        # Persist a synthetic conversation so the user can audit what the
        # heartbeat asked / did. Title is dated so they're easy to scan.
        async with async_session() as db:
            conv = Conversation(
                user_id=user_id,
                title=f"[Heartbeat] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            )
            db.add(conv)
            await db.flush()
            conv_id = str(conv.id)
            db.add(Message(conversation_id=conv_id, role="user", content=prompt))
            await db.commit()

        agent = build_agent_graph()
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=prompt)],
            "user_id": user_id,
            "conversation_id": conv_id,
            "google_credentials": google_credentials,
        })
        ai_content = result["messages"][-1].content or ""

        # If the agent said HEARTBEAT_OK and didn't call any tool, drop the
        # synthetic conversation entirely — keeps the history clean.
        no_action = ai_content.strip().upper().startswith("HEARTBEAT_OK")
        async with async_session() as db:
            if no_action:
                # Delete the conversation we just created (cascade messages)
                from sqlalchemy import delete
                await db.execute(
                    delete(Message).where(Message.conversation_id == conv_id)
                )
                await db.execute(
                    delete(Conversation).where(Conversation.id == conv_id)
                )
                await db.commit()
                logger.info(
                    "[heartbeat] user %s — no-op (HEARTBEAT_OK)", user_id
                )
            else:
                db.add(Message(
                    conversation_id=conv_id, role="assistant", content=ai_content
                ))
                await db.commit()
                logger.info(
                    "[heartbeat] user %s — acted (%d chars)", user_id, len(ai_content)
                )
    except Exception as exc:
        logger.exception("[heartbeat] failed for user %s: %s", user_id, exc)


# ──────────────────────────────────────────────────────────────────────────────
# Job (re)scheduling
# ──────────────────────────────────────────────────────────────────────────────

def _job_id(user_id: str) -> str:
    return f"heartbeat_{user_id}"


def schedule_heartbeat_for_user(user: User) -> bool:
    """Add or replace the APScheduler job for this user. Returns True on success."""
    if not user.heartbeat_enabled:
        unschedule_heartbeat_for_user(user.id)
        return False
    interval = max(1, int(user.heartbeat_interval_minutes or 30))
    scheduler = get_scheduler()
    scheduler.add_job(
        _execute_heartbeat,
        trigger=IntervalTrigger(minutes=interval),
        args=[user.id],
        id=_job_id(user.id),
        replace_existing=True,
        name=f"heartbeat:{user.username if hasattr(user, 'username') else user.id}",
    )
    if not scheduler.running:
        scheduler.start()
    logger.info(
        "[heartbeat] scheduled for user %s every %d min", user.id, interval
    )
    return True


def unschedule_heartbeat_for_user(user_id: str) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(_job_id(user_id))
        logger.info("[heartbeat] unscheduled for user %s", user_id)
    except Exception:
        pass  # Job didn't exist


async def load_and_schedule_heartbeats() -> None:
    """Called at startup — register a job for every opted-in user."""
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.heartbeat_enabled == True)
        )
        users = result.scalars().all()
    for user in users:
        try:
            schedule_heartbeat_for_user(user)
        except Exception as exc:
            logger.warning(
                "[heartbeat] failed to schedule user %s: %s", user.id, exc
            )
    logger.info("[heartbeat] startup loaded %d active users", len(users))
