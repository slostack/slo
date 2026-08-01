"""FastAPI app initialisation — middleware + router + exception-handler triad.

Mirrors lattice's ``src/main.py`` triad pattern. Routers raise typed
:class:`src.exceptions.ApiException` subclasses (or Pydantic
``ValidationError``); the handlers below translate every one into the
``data`` / ``errors`` / ``api_version`` envelope from
``base_controller``. Routers MUST NOT return
``JSONResponse(FailureResponseDAO.build(...))`` inline.
"""
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from config.logger import log_error
from src.exceptions import ApiException
from src.middleware.request_ctx import RequestCtxDAO, RequestCtxMiddleware
from src.routers.base_controller import FailureResponseDAO
from src.routers.health_controller import router as health_router


INTERNAL_ERROR: str = "Internal Error"


def initialize_web_app(app: FastAPI) -> FastAPI:
    """Wire middleware, routers, and exception handlers in canonical order.

    Returns the same ``app`` (mutated) so the call can be chained from
    ``src.main``.
    """
    app = _initialize_middleware(app=app)
    app = _initialize_routers(app=app)
    app = _initialize_exception_handlers(app=app)
    return app


def _initialize_middleware(app: FastAPI) -> FastAPI:
    """Install CORS and request-context middleware in order."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestCtxMiddleware)
    return app


def _initialize_routers(app: FastAPI) -> FastAPI:
    """Mount every router. Sub-spec 01.j will append the agent router."""
    app.include_router(health_router)
    return app


def _request_id(request: Request) -> str:
    """Best-effort extract of the request id stamped by ``RequestCtxMiddleware``."""
    state = getattr(request, "state", None)
    ctx = getattr(state, "ctx", None) if state is not None else None
    request_id = getattr(ctx, "request_id", None) if ctx is not None else None
    return str(request_id) if request_id else ""


def _initialize_exception_handlers(app: FastAPI) -> FastAPI:
    """Wire central exception handlers that emit ``FailureResponseDAO`` envelopes."""

    @app.exception_handler(ApiException)
    async def handle_api_exception(request: Request, exc: ApiException) -> JSONResponse:
        error_id: str = str(uuid4())
        request_id: str = _request_id(request=request)
        log_error(
            msg=f"error_id={error_id} rid={request_id} ApiException: {exc.msg}",
            e=exc,
            stack_trace=False,
        )
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO.build(
                error_code=exc.code,
                errors=[exc.msg],
                payload={"error_id": error_id, "request_id": request_id},
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        error_id: str = str(uuid4())
        request_id: str = _request_id(request=request)
        first_error: dict = exc.errors()[0] if exc.errors() else {}
        message: str = str(first_error.get("msg") or "Validation Error")
        log_error(
            msg=f"error_id={error_id} rid={request_id} RequestValidationError: {exc}",
            e=exc,
            stack_trace=False,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=FailureResponseDAO.build(
                error_code="unprocessable_entity",
                errors=[message],
                payload={"error_id": error_id, "request_id": request_id},
            ),
        )

    @app.exception_handler(PydanticValidationError)
    async def handle_pydantic_validation_error(
        request: Request,
        exc: PydanticValidationError,
    ) -> JSONResponse:
        error_id: str = str(uuid4())
        request_id: str = _request_id(request=request)
        first_error: dict = exc.errors()[0] if exc.errors() else {}
        message: str = str(first_error.get("msg") or "Validation Error")
        log_error(
            msg=f"error_id={error_id} rid={request_id} ValidationError: {exc}",
            e=exc,
            stack_trace=False,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=FailureResponseDAO.build(
                error_code="unprocessable_entity",
                errors=[message],
                payload={"error_id": error_id, "request_id": request_id},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_uncaught_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        error_id: str = str(uuid4())
        request_id: str = _request_id(request=request)
        log_error(
            msg=(
                f"error_id={error_id} rid={request_id} "
                f"Unhandled Exception: {exc}"
            ),
            e=exc,
            stack_trace=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=FailureResponseDAO.build(
                error_code="internal_server_error",
                errors=[INTERNAL_ERROR],
                payload={"error_id": error_id, "request_id": request_id},
            ),
        )

    return app


# Re-export RequestCtxDAO for callers that want the dependency type.
__all__ = ["initialize_web_app", "RequestCtxDAO"]
