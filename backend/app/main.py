import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

from app.core.config import settings
from app.db import engine
from app.models.mini import Base
from app.plugins.loader import load_plugins
from app.plugins.registry import registry
from app.routes import chat, minis
from app.routes.auth import router as auth_router
from app.routes.upload import router as upload_router
from app.routes.teams import router as teams_router
from app.routes.orgs import router as orgs_router
from app.routes.export import router as export_router
from app.routes.team_chat import router as team_chat_router
from app.routes.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    load_plugins()
    await registry.setup_clients(app)
    if settings.jwt_secret == "dev-secret-change-in-production":
        logger.warning("Using default JWT secret! Set JWT_SECRET env var for production.")
    yield


app = FastAPI(title="Minis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(minis.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(teams_router, prefix="/api")
app.include_router(orgs_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(team_chat_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
