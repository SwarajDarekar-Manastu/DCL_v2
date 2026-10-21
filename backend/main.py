"""The one FastAPI app. ROLE decides which routers of backend/api are mounted (file 10 §2.1)."""

from contextlib import asynccontextmanager
from types import ModuleType

import uvicorn
from fastapi import FastAPI

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
from backend.config import Role, get_settings

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
async def lifespan(_: FastAPI):
    get_settings()
    yield


def create_app() -> FastAPI:
    role = get_settings().role
    app = FastAPI(title=f"DCL backend ({role})", lifespan=lifespan)
    for module in ROUTERS_BY_ROLE[role]:
        app.include_router(module.router)
    return app


def run() -> None:
    role = get_settings().role
    uvicorn.run("backend.main:create_app", factory=True, host="0.0.0.0", port=DEFAULT_PORT_BY_ROLE[role])  # noqa: S104


if __name__ == "__main__":
    run()
