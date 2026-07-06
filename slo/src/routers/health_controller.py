"""Liveness probe used by Docker, Compose, and uptime monitoring.

Per ``build-routers.md`` §"Sample Controller", real controllers must
namespace under ``/api/v1``. ``/healthz`` deliberately escapes the
prefix because infra probes target the literal path.
"""
from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Returns 200 with ``{"status": "ok"}`` when the app is up."""
    return {"status": "ok"}
