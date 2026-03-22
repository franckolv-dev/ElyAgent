from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.models import system_config as _  # ensure SystemConfig table is registered
from app.models import scheduled_task as __  # ensure ScheduledTask table is registered
from app.routers import auth, chat, hosts, admin, health
from app.routers import validation, tts, scheduler as scheduler_router
from app.routers import google as google_router
from app.middleware.rate_limit import setup_rate_limiter
from app.services.memory_manager import get_memory_manager
from app.services.fts_store import get_fts_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await get_memory_manager().init_collections()
    await get_fts_store().init()

    # Start Telegram bot if configured
    from app.channels.telegram_bot import start_telegram_bot, stop_telegram_bot
    await start_telegram_bot()

    # Start scheduled tasks
    from app.services.scheduler import load_and_schedule_tasks, stop_scheduler
    await load_and_schedule_tasks()

    yield

    await stop_scheduler()
    await stop_telegram_bot()


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
