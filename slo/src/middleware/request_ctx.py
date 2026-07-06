"""Request context middleware — populates ``request.state.ctx``.

Mirrors lattice's ``src/middleware/request_id.py`` 1:1 with the same
``RequestCtxDAO`` + ``ContextVar`` propagation pattern. Downstream
handlers, logging, and the central exception-handler read
``request.state.ctx.request_id`` to correlate work across services.
"""
from contextvars import ContextVar
from typing import Callable, Final, Optional
from uuid import UUID, uuid4

from fastapi.requests import Request
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp


__all__ = ["RequestContext", "RequestCtxDAO", "RequestCtxMiddleware"]


REQUEST_ID_CTX_KEY: Final[str] = "request_id"
_request_id_ctx_var: ContextVar[Optional[str]] = ContextVar(
    REQUEST_ID_CTX_KEY,
    default=None,
)


class RequestCtxDAO(BaseModel):
    """Per-request context attached to ``request.state.ctx``."""

    request_id: Optional[UUID | str] = None
    path: Optional[str] = None
    request_ip: Optional[str] = None

    model_config = ConfigDict(
        title="request_ctx",
        from_attributes=True,
        arbitrary_types_allowed=True,
        json_encoders={
            UUID: lambda o: str(o),
        },
    )


REQUEST_CTX_KEY: Final[str] = "ctx"
_request_ctx: ContextVar[Optional[RequestCtxDAO]] = ContextVar(
    REQUEST_CTX_KEY,
    default=RequestCtxDAO(),
)


class RequestContext:
    """Accessor for the per-request ``ContextVar`` pair.

    The ``ContextVar`` instances themselves stay module-level because FastAPI /
    Starlette rely on contextvar inheritance across the asyncio task boundary —
    moving them onto the class would break that propagation. This class is a
    thin, named-arg, classmethod-only API over those module vars.
    """

    @classmethod
    async def set_id(cls) -> str:
        """Generate a fresh request id and bind it to the current ContextVar.

        Returns:
            str: The newly minted request id.
        """
        rid: str = str(uuid4())
        _request_id_ctx_var.set(rid)
        return rid

    @classmethod
    async def get_id(cls) -> Optional[str]:
        """Return the current request id from the ContextVar, if any.

        Returns:
            Optional[str]: The active request id, or ``None`` when unset.
        """
        return _request_id_ctx_var.get()

    @classmethod
    async def set(cls, *, request: Request) -> ContextVar[Optional[RequestCtxDAO]]:
        """Populate ``request.state.ctx`` and the module ContextVar.

        Args:
            request (Request): The incoming HTTP request whose ``state.ctx``
                should be stamped with a fresh ``RequestCtxDAO``.

        Returns:
            ContextVar[Optional[RequestCtxDAO]]: The module-level ContextVar
            after binding, returned for parity with the prior helper signature.
        """
        rid: str = await cls.set_id()
        rip: str = request.headers.get("x-forwarded-for", "")
        ctx: RequestCtxDAO = RequestCtxDAO(
            request_id=rid,
            path=request.base_url.path,
            request_ip=rip,
        )
        _request_ctx.set(ctx)
        request.state.ctx = ctx
        return _request_ctx

    @classmethod
    async def get(cls) -> Optional[RequestCtxDAO]:
        """Return the current ``RequestCtxDAO`` from the ContextVar, if any.

        Returns:
            Optional[RequestCtxDAO]: The active per-request DAO, or ``None``
            when unset.
        """
        return _request_ctx.get()


class RequestCtxMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Attach a ``RequestCtxDAO`` to ``request.state.ctx`` before the route runs.

        Args:
            request (Request): The incoming request.
            call_next (Callable): The next middleware or endpoint.

        Returns:
            Response: The response from the next middleware or endpoint,
                with the ``X-Request-ID`` header set.
        """
        await RequestContext.set(request=request)
        response: Response = await call_next(request)
        if isinstance(request.state.ctx, RequestCtxDAO) and request.state.ctx.request_id:
            response.headers["X-Request-ID"] = str(request.state.ctx.request_id)
        return response
