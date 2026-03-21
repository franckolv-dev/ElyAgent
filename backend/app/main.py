from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers import auth, chat, hosts, admin, health
from app.routers import validation, tts
from app.middleware.rate_limit import setup_rate_limiter
from app.services.memory_manager import get_memory_manager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await get_memory_manager().init_collections()
    yield


app = FastAPI(
    title="Cyber-Entity Agent API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
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
