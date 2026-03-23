from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.models import system_config as _   # ensure SystemConfig table is registered
from app.models import scheduled_task as __  # ensure ScheduledTask table is registered
from app.models import skill_preference as ___ # ensure SkillPreference table is registered
from app.models import watch_task as _watch_task  # ensure WatchTask table is registered
from app.routers import auth, chat, hosts, admin, health
from app.routers import validation, tts, scheduler as scheduler_router
from app.routers import google as google_router
from app.routers import skills as skills_router
from app.routers import transcribe as transcribe_router
from app.routers import whatsapp_webhook as whatsapp_router
from app.routers import watchdog as watchdog_router
from app.middleware.rate_limit import setup_rate_limiter
from app.services.memory_manager import get_memory_manager
from app.services.fts_store import get_fts_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register all built-in skills BEFORE the agent graph is built
    from app.skills.builtin import register_all
    register_all()

    await init_db()
    await get_memory_manager().init_collections()
    await get_fts_store().init()

    # Start Telegram bot if configured
    from app.channels.telegram_bot import start_telegram_bot, stop_telegram_bot
    await start_telegram_bot()

    # Load WhatsApp linked users
    from app.channels.whatsapp import load_linked_whatsapp_users
    await load_linked_whatsapp_users()

    # Start scheduled tasks
    from app.services.scheduler import load_and_schedule_tasks, stop_scheduler
    await load_and_schedule_tasks()

    # Start watchdog service
    from app.services.watchdog_service import load_and_schedule_watch_tasks, stop_watchdog
    await load_and_schedule_watch_tasks()

    # Start headless browser (graceful no-op if playwright is not installed)
    from app.services.browser_manager import get_browser_manager
    await get_browser_manager().start()

    yield

    await stop_scheduler()
    await stop_watchdog()
    await stop_telegram_bot()
    await get_browser_manager().stop()


app = FastAPI(
    title="Cyber-Entity Agent API",
    version="0.2.0",
    lifespan=lifespan,
)

def _get_cors_origins() -> list[str]:
    s = get_settings()
    if s.cors_origins:
        return [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    return [s.frontend_url]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_rate_limiter(app)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/ws", tags=["chat"])
app.include_router(hosts.router, prefix="/hosts", tags=["hosts"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(validation.router)
app.include_router(tts.router)
app.include_router(google_router.router, prefix="/api")
app.include_router(scheduler_router.router, prefix="/scheduler", tags=["scheduler"])
app.include_router(skills_router.router, prefix="/skills", tags=["skills"])
app.include_router(transcribe_router.router, prefix="/api", tags=["transcribe"])
app.include_router(whatsapp_router.router, prefix="/api", tags=["whatsapp"])
app.include_router(watchdog_router.router, prefix="/watchdog", tags=["watchdog"])
