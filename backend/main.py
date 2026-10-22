"""The one FastAPI app. DCL_ROLE decides which routers of backend/api are mounted (file 10 §2.1)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from types import ModuleType

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    assets,
    audit,
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
from backend.celery_redis.queues import Queue
from backend.common.telemetry import instrument_fastapi, register_queue_depth, setup_telemetry
from backend.config import ConfigError, Role, get_settings

log = logging.getLogger(__name__)

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
    audit,
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
        if setup_telemetry(f"dcl-{settings.role}"):
            register_queue_depth(str(redis_url), [str(q) for q in Queue])
    engine_started = False
    if settings.role in (Role.API, Role.ALL):
        try:
            await engine.start_engine()  # warm the Answer Engine so the first request is not slow
            engine_started = True
        except ConfigError as exc:  # the other routers still serve without the engine
            log.warning("answer engine not started: %s", exc)
    try:
        yield
    finally:
        if engine_started:
            with contextlib.suppress(Exception):
                await engine.stop_engine()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):  # shutdown must not raise
                await task


def _role() -> Role:
    role = get_settings().role
    if role is None:
        raise ConfigError("DCL_ROLE is required to start backend.main (api | models | all)")
    return role


def create_app() -> FastAPI:
    role = _role()
    setup_telemetry(f"dcl-{role}", str(get_settings().env))
    app = FastAPI(title=f"DCL backend ({role})", lifespan=lifespan)
    instrument_fastapi(app)
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
