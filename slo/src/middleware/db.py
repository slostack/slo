"""DbMiddleware — injects an async DB session into ``request.state.db``.

Mirrors lattice's ``src/middleware/db.py`` 1:1. v1 of slo does not write
to the database, but the middleware is wired so any future domain
service can pull ``request.state.db`` without per-router boilerplate.

When ``SLO_DB_URL_ASYNC`` is unset (i.e. the Postgres dev container is
not running), ``get_async_session`` raises a ``RuntimeError``. The
middleware lets that propagate — the route is responsible for not
asking for a session it doesn't need, OR for catching it at the service
boundary.
"""
from typing import Any, Callable

from fastapi.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from connectors.async_pg import AsyncSessionLocal, get_async_session


class DbMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        """Inject an async database session into ``request.state.db``.

        When ``SLO_DB_URL_ASYNC`` is unset (v1 does not require the DB),
        the middleware leaves ``request.state.db = None`` and passes
        through. Routers that actually need a session must check.

        Args:
            request (Request): The incoming request.
            call_next (Callable): The next middleware or endpoint.

        Returns:
            Any: The response from the next middleware or endpoint.
        """
        if AsyncSessionLocal is None:
            request.state.db = None
            return await call_next(request)

        db: AsyncSession = await get_async_session()
        try:
            request.state.db = db
            response: Any = await call_next(request)
        finally:
            if request.state.db and request.state.db.is_active:
                if isinstance(request.state.db, AsyncSession):
                    db_session: AsyncSession = request.state.db
                    await db_session.close()
                else:
                    request.state.db.close()
        return response
