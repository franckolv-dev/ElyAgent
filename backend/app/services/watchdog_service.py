# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/services/watchdog_service.py
# @brief      Watchdog service — polls URLs/searches and notifies on change.
#
# @author     Franck OLLIVIER <franck.olv@gmail.com>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    PolyForm Strict License 1.0.0
#             https://polyformproject.org/licenses/strict/1.0.0/
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
#   - INTERDIT : Toute utilisation commerciale sans accord préalable.
#   - INTERDIT : Redistribution de versions modifiées de ce code.
# =============================================================================
"""Watchdog service — polls URLs/searches and notifies on change."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import async_session
from app.models.watch_task import WatchTask

logger = logging.getLogger(__name__)

# Internal Docker service hostnames that must never be fetched
_INTERNAL_HOSTNAMES = frozenset({
    "qdrant", "ollama", "backend", "redis", "postgres", "db",
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
})


def _is_safe_url(url: str) -> bool:
    """Block SSRF: reject private IPs, localhost, metadata endpoints."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() in _INTERNAL_HOSTNAMES:
            return False
        # Block AWS/GCP/Azure metadata endpoints
        if hostname in ("169.254.169.254", "metadata.google.internal"):
            return False
        # Resolve and check IP range if it looks like a literal IP
        try:
            addr = ipaddress.ip_address(hostname)
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
            ):
                return False
        except ValueError:
            pass  # hostname (not a literal IP) — DNS resolution omitted for simplicity
        return True
    except Exception:
        return False

_watchdog_scheduler: AsyncIOScheduler | None = None


def get_watchdog_scheduler() -> AsyncIOScheduler:
    global _watchdog_scheduler
    if _watchdog_scheduler is None:
        _watchdog_scheduler = AsyncIOScheduler(timezone="Europe/Paris")
    return _watchdog_scheduler


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def _fetch_content(target: str, watch_type: str) -> str:
    """Fetch content for a watch target.

    HIGH-6: URL safety check applied before any network request.
    For search-type tasks, the query is sent to DuckDuckGo (always safe).
    For URL-type tasks, the target URL must pass the SSRF filter.
    """
    if watch_type != "search" and not _is_safe_url(target):
        raise ValueError(f"SSRF protection: unsafe URL blocked: {target!r}")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        if watch_type == "search":
            # Use DuckDuckGo HTML search
            r = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": target},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            # Extract snippet text (first 2000 chars of results)
            text = r.text[:5000]
            # Remove HTML tags roughly
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:2000]
        else:
            r = await client.get(target, headers={"User-Agent": "Mozilla/5.0"})
            text = r.text[:5000]
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:2000]


async def _check_task(task_id: str) -> None:
    """Check a single watch task for changes."""
    from datetime import datetime, timezone

    async with async_session() as db:
        result = await db.execute(select(WatchTask).where(WatchTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task or not task.enabled:
            return

    try:
        content = await _fetch_content(task.target, task.watch_type)
        new_hash = _hash_content(content)

        async with async_session() as db:
            result = await db.execute(select(WatchTask).where(WatchTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return

            changed = task.last_content_hash and task.last_content_hash != new_hash
            task.last_checked_at = datetime.now(timezone.utc)
            task.last_content_hash = new_hash
            task.last_content_preview = content[:300]

            if changed:
                task.change_count = (task.change_count or 0) + 1
                await db.commit()
                await _notify_change(task, content[:500])
                logger.info("Watch task '%s' detected change", task.name)
            else:
                await db.commit()

    except Exception as exc:
        logger.warning("Watchdog check failed for task %s: %s", task_id, exc)


async def _notify_change(task: WatchTask, preview: str) -> None:
    """Notify the user of a detected change."""
    message = (
        f"🔔 Veille — {task.name}\n\n"
        f"Un changement a été détecté sur : {task.target}\n\n"
        f"Aperçu :\n{preview}"
    )

    if task.notify_channel == "telegram":
        try:
            from app.channels.telegram_bot import _bot_app, _linked_users
            if _bot_app:
                tg_id = next((tid for tid, uid in _linked_users.items() if uid == task.user_id), None)
                if tg_id:
                    await _bot_app.bot.send_message(chat_id=tg_id, text=message[:4096])
                    return
        except Exception as exc:
            logger.warning("Telegram notify failed: %s", exc)

    # Web delivery via WebSocket
    try:
        import json
        from app.services import ws_registry
        ws = ws_registry.get(task.user_id)
        if ws:
            await ws.send_text(json.dumps({
                "type": "watchdog_alert",
                "task_name": task.name,
                "target": task.target,
                "content": preview,
            }))
    except Exception as exc:
        logger.warning("WebSocket notify failed: %s", exc)


async def load_and_schedule_watch_tasks() -> None:
    """Load all enabled watch tasks and schedule them."""
    scheduler = get_watchdog_scheduler()

    async with async_session() as db:
        result = await db.execute(select(WatchTask).where(WatchTask.enabled == True))
        tasks = result.scalars().all()

    for task in tasks:
        scheduler.add_job(
            _check_task,
            "interval",
            minutes=task.check_interval_minutes,
            args=[task.id],
            id=f"watch_{task.id}",
            replace_existing=True,
            name=f"watch:{task.name}",
        )

    if not scheduler.running:
        scheduler.start()

    logger.info("Watchdog started with %d tasks", len(tasks))


def schedule_watch_task(task: WatchTask) -> None:
    scheduler = get_watchdog_scheduler()
    scheduler.add_job(
        _check_task,
        "interval",
        minutes=task.check_interval_minutes,
        args=[task.id],
        id=f"watch_{task.id}",
        replace_existing=True,
        name=f"watch:{task.name}",
    )
    if not scheduler.running:
        scheduler.start()


def unschedule_watch_task(task_id: str) -> None:
    scheduler = get_watchdog_scheduler()
    try:
        scheduler.remove_job(f"watch_{task_id}")
    except Exception:
        pass


async def stop_watchdog() -> None:
    global _watchdog_scheduler
    if _watchdog_scheduler and _watchdog_scheduler.running:
        _watchdog_scheduler.shutdown(wait=False)
        _watchdog_scheduler = None
        logger.info("Watchdog stopped")
