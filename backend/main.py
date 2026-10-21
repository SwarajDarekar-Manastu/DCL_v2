"""The one FastAPI app. ROLE decides which routers of backend/api are mounted (file 10 §2.1)."""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from types import ModuleType

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    assets,
    auth,
    benchmark,
    engine,
    entities,
    health,
    models,
    review,
    settings,
    sync,
    viewer,
    ws,
)
from backend.config import ConfigError, Role, get_settings

API_ROUTERS: list[ModuleType] = [
    health,
    auth,
    sync,
    review,
    settings,
    entities,
    engine,
    viewer,
    assets,
    benchmark,
    ws,
]
MODEL_ROUTERS: list[ModuleType] = [health, models]
ROUTERS_BY_ROLE: dict[Role, list[ModuleType]] = {
    Role.API: API_ROUTERS,
    Role.MODELS: MODEL_ROUTERS,
    Role.ALL: API_ROUTERS + [models],
}
DEFAULT_PORT_BY_ROLE: dict[Role, int] = {Role.API: 8200, Role.MODELS: 8500, Role.ALL: 8200}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tasks: list[asyncio.Task[None]] = []
    redis_url = getattr(settings, "redis_url", None)
    if settings.role in (Role.API, Role.ALL) and redis_url:
        tasks.append(asyncio.create_task(ws.redis_bridge(str(redis_url)), name="console-redis-bridge"))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):  # shutdown must not raise
                await task


def _role() -> Role:
    role = get_settings().role
    if role is None:
        raise ConfigError("ROLE is required to start backend.main (api | models | all)")
    return role


def create_app() -> FastAPI:
    role = _role()
    app = FastAPI(title=f"DCL backend ({role})", lifespan=lifespan)
    origins = getattr(get_settings(), "console_allowed_origins", None)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    for module in ROUTERS_BY_ROLE[role]:
        app.include_router(module.router)
    return app


def run() -> None:
    role = _role()
    uvicorn.run("backend.main:create_app", factory=True, host="0.0.0.0", port=DEFAULT_PORT_BY_ROLE[role])  # noqa: S104


if __name__ == "__main__":
    run()
