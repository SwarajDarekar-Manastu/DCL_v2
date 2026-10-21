"""S4: liveness for every role; readiness checks are added as the dependencies land."""

from fastapi import APIRouter

from backend.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "role": get_settings().role}
