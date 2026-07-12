from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import router
from .config import get_settings
from .database import engine, session_factory
from .logging import configure_logging
from .models import Base, RegistrationToken
from .security import hash_token

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI):
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
    await logger.ainfo("api.started", environment=settings.app_env)
    yield
    await engine.dispose()
    await logger.ainfo("api.stopped")


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/healthz", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
