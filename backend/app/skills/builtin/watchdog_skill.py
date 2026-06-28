# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/watchdog_skill.py
# @brief      🔍 Watchdog skill — monitor URLs and search queries for changes.
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
"""🔍 Watchdog skill — monitor URLs and search queries for changes."""
from typing import Annotated
from langchain_core.tools import tool
from langchain_core.tools import InjectedToolArg
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry


@tool
async def watchdog_add(
    name: str,
    target: str,
    watch_type: str = "url",
    check_interval_minutes: int = 60,
    notify_channel: str = "web",
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Add a new watch task to monitor a URL or search query for changes.

    Args:
        name: Descriptive name for this watch task (e.g., "Prix iPhone Apple Store")
        target: URL to monitor OR search query to track
        watch_type: "url" to monitor a specific page, "search" to monitor search results
        check_interval_minutes: How often to check for changes (default: 60 minutes)
        notify_channel: Where to send alerts: "web" or "telegram"
    """
    import httpx
    # Use the service directly instead of going through HTTP
    try:
        from app.database import async_session
        from app.models.watch_task import WatchTask
        from app.services.watchdog_service import schedule_watch_task

        task = WatchTask(
            user_id=user_id,
            name=name,
            watch_type=watch_type,
            target=target,
            check_interval_minutes=check_interval_minutes,
            notify_channel=notify_channel,
        )
        async with async_session() as db:
            db.add(task)
            await db.commit()
            await db.refresh(task)
        schedule_watch_task(task)
        return f"✅ Surveillance créée : '{name}' — vérification toutes les {check_interval_minutes} min. Alerte via {notify_channel}."
    except Exception as exc:
        return f"Erreur lors de la création de la surveillance : {exc}"


@tool
async def watchdog_list(
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """List all active watch tasks for the current user."""
    from app.database import async_session
    from app.models.watch_task import WatchTask
    from sqlalchemy import select

    try:
        async with async_session() as db:
            result = await db.execute(
                select(WatchTask).where(WatchTask.user_id == user_id)
            )
            tasks = result.scalars().all()

        if not tasks:
            return "Aucune surveillance active."

        lines = [f"Surveillances actives ({len(tasks)}) :"]
        for t in tasks:
            status = "✅" if t.enabled else "⏸️"
            last = t.last_checked_at.strftime("%d/%m %H:%M") if t.last_checked_at else "jamais"
            lines.append(
                f"{status} {t.name} — {t.target[:60]} "
                f"(toutes les {t.check_interval_minutes}min, dernier check: {last}, "
                f"{t.change_count} changement(s))"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Erreur : {exc}"


@tool
async def watchdog_remove(
    name: str,
    user_id: Annotated[str, InjectedToolArg] = "",
) -> str:
    """Remove a watch task by name.

    Args:
        name: Name of the watch task to remove
    """
    from app.database import async_session
    from app.models.watch_task import WatchTask
    from app.services.watchdog_service import unschedule_watch_task
    from sqlalchemy import select

    try:
        async with async_session() as db:
            result = await db.execute(
                select(WatchTask).where(
                    WatchTask.user_id == user_id,
                    WatchTask.name == name,
                )
            )
            task = result.scalar_one_or_none()
            if not task:
                return f"Aucune surveillance nommée '{name}' trouvée."
            task_id = task.id
            await db.delete(task)
            await db.commit()
        unschedule_watch_task(task_id)
        return f"✅ Surveillance '{name}' supprimée."
    except Exception as exc:
        return f"Erreur : {exc}"


_watchdog_skill = Skill(
    name="watchdog",
    display_name="Veille & surveillance",
    description="Surveille des URLs et requêtes de recherche pour détecter les changements",
    icon="🔍",
    domains=[Domain.INFRA],
    tools=[watchdog_add, watchdog_list, watchdog_remove],
    scopes=[],
    enabled_by_default=True,
)

get_skill_registry().register(_watchdog_skill)
