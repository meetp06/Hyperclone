import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.queue import close_pool
from app.services.redis_client import close_redis

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="Pioneer API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Next picks 3001/3002/etc when 3000 is busy; match any localhost dev port.
    allow_origin_regex=r"^http://localhost:\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Routers wired in subsequent steps.
from app.routers import (  # noqa: E402
    access,
    agents,
    auth,
    automations,
    chat,
    connectors,
    drafts,
    memories,
    workspaces,
)

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(connectors.router)
app.include_router(memories.router)
app.include_router(chat.router)
app.include_router(agents.router)
app.include_router(automations.router)
# Phase 3
app.include_router(access.audit_router)
app.include_router(access.agents_access_router)
# Phase 4
app.include_router(drafts.router)
