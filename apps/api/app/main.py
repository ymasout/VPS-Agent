import asyncio
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import router
from .config import get_settings
from .database import engine, session_factory
from .github import router as github_router
from .logging import configure_logging
from .m3 import router as m3_router
from .maintenance import control_plane_maintenance_loop
from .models import Base, RegistrationToken
from .operations import router as operations_router
from .releases import router as releases_router
from .security import hash_token

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI):
    maintenance_task: asyncio.Task[None] | None = None
    if not settings.skip_database_init:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    if settings.dev_agent_registration_token and not settings.skip_database_init:
        async with session_factory() as session:
            token_hash = hash_token(settings.dev_agent_registration_token)
            if (
                await session.scalar(
                    select(RegistrationToken).where(RegistrationToken.token_hash == token_hash)
                )
                is None
            ):
                from datetime import datetime, timedelta, timezone

                session.add(
                    RegistrationToken(
                        token_hash=token_hash,
                        name="Docker Compose development agent",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                    )
                )
                await session.commit()
    if not settings.skip_database_init:
        maintenance_task = asyncio.create_task(
            control_plane_maintenance_loop(settings),
            name="control-plane-maintenance",
        )
    await logger.ainfo("api.started", environment=settings.app_env)
    yield
    if maintenance_task is not None:
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task
    await engine.dispose()
    await logger.ainfo("api.stopped")


app = FastAPI(title=settings.app_name, version="0.4.0-dev", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(m3_router)
app.include_router(operations_router)
app.include_router(github_router)
app.include_router(releases_router)


@app.get("/healthz", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
