---
name: build-middleware
description: 'Python: Adding FastAPI cross-cutting middleware (DB sessions, request tracking, auth).'
when_to_use: For Python projects only. Use when introducing a new request-scoped concern that wraps the
  app.
group: languages
kind: skill
source_prompt: build-middleware.md
---

# Middleware

## Skill summary

- **Name:** `build-middleware`
- **Description:** Adding FastAPI cross-cutting middleware (DB sessions, request tracking, auth).
- **When to use:** Use when introducing a new request-scoped concern that wraps the app.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-middleware.md`

## Examples

- The user asks: "Add or revise the middleware for this feature."
- You want the canonical build pattern before touching middleware.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

Middleware in our FastAPI applications intercepts every request before it reaches the route handler and every response before it leaves. We use middleware to manage cross-cutting concerns like database session lifecycle, request context tracking, and CORS configuration.

All custom middleware lives under `src/middleware/` with each middleware in its own file.

## Middleware Architecture

Middleware is registered in `src/web_app.py` inside the `_initialize_middleware` function. The order of registration matters — FastAPI processes middleware in **reverse order** of registration. The last middleware added is the first to execute on an incoming request.

```python
from src.middleware.db import DbMiddleware
from src.middleware.request_id import RequestCtxMiddleware
from fastapi.middleware.cors import CORSMiddleware

def _initialize_middleware(app: FastAPI) -> FastAPI:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(DbMiddleware)
    app.add_middleware(RequestCtxMiddleware)
    return app
```

Given this registration order, the execution flow for an incoming request is:

```
Request → RequestCtxMiddleware → DbMiddleware → CORSMiddleware → Route Handler
Response ← RequestCtxMiddleware ← DbMiddleware ← CORSMiddleware ← Route Handler
```

`RequestCtxMiddleware` runs first because it was added last. This means by the time `DbMiddleware` runs, `request.state.ctx` is already available with the request ID.

## Building a Custom Middleware

All custom middleware inherits from `BaseHTTPMiddleware` provided by Starlette. The structure follows a consistent pattern.

### Base Structure

```python
from typing import Callable, Any
from fastapi.requests import Request
from starlette.types import ASGIApp
from starlette.middleware.base import BaseHTTPMiddleware


class CustomMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        # Pre-processing: runs before the route handler
        # Attach data to request.state for downstream access

        response: Any = await call_next(request)

        # Post-processing: runs after the route handler
        # Modify response headers, log metrics, etc.

        return response
```

Key points:
1. The `__init__` method receives the ASGI app and passes it to the parent class. If your middleware needs configuration parameters, accept them here.
2. The `dispatch` method is where all the logic lives. It receives the incoming `request` and a `call_next` callable that forwards the request to the next middleware or route handler.
3. Use `request.state` to attach data that route handlers and other middleware can access. This is the primary mechanism for passing context through the request lifecycle.

### Middleware with Configuration Parameters

When a middleware needs external configuration, accept parameters in `__init__` and register them using `app.add_middleware` with keyword arguments.

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable):
        # Use self.max_requests and self.window_seconds
        response = await call_next(request)
        return response
```

Registration:

```python
app.add_middleware(RateLimitMiddleware, max_requests=200, window_seconds=120)
```

## The DbMiddleware — Database Session Injection

The `DbMiddleware` is the core middleware for managing database connections. It creates an async database session at the start of each request, attaches it to `request.state.db`, and ensures the session is properly closed when the request completes — even if an exception occurs.

### Implementation

```python
from time import time
from typing import Callable, Any, Optional
from fastapi.requests import Request
from starlette.types import ASGIApp
from starlette.middleware.base import BaseHTTPMiddleware
from connectors.async_postgres import get_async_session, async_scoped_session
from sqlalchemy.ext.asyncio import AsyncSession


class DbMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Dispatches the request to the next middleware or endpoint, while managing the database session.

        Args:
            request (Request): The incoming request.
            call_next (Callable): The next middleware or endpoint to call.

        Returns:
            Any: The response from the next middleware or endpoint.
        """
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
```

### How It Works

1. **Session Creation**: Before the route handler executes, `get_async_session()` creates a new `AsyncSession` from the async session factory defined in `connectors/async_postgres.py`.
2. **Injection via `request.state`**: The session is attached to `request.state.db`. Every route handler receives the `request` object and can access the session as `request.state.db`.
3. **Guaranteed Cleanup**: The `try/finally` block ensures the session is always closed, even if the route handler raises an exception. This prevents connection leaks.
4. **Session Type Handling**: The cleanup logic checks whether the session is async or synchronous and calls the appropriate close method. This supports codebases that may use both session types.

### Accessing the Database Session in Route Handlers

Route handlers access the session directly from `request.state.db` and pass it to domain services and application services.

```python
from fastapi import Request, APIRouter, status
from fastapi.responses import JSONResponse
from src.routers.base_controller import success_response
from src.domains.user.service import UserService, User
from src.domains.user.dao import UserProfileDAO

router = APIRouter(prefix="/api/v1")


@router.get("/users/{id}", name="get_user")
async def get_user(request: Request, id: int):
    user: User = await UserService.get(id=id, db_session=request.state.db)
    user_profile_dao: UserProfileDAO = UserProfileDAO.model_validate(user)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_response(payload=user_profile_dao),
    )
```

This pattern keeps the database session scoped to the request lifecycle. The session is created when the request enters the middleware pipeline and closed when the response leaves it.

### Passing the Session to Services

Domain services and application services always accept `db_session` as a parameter. They never create their own sessions — the middleware owns the session lifecycle.

```python
class UserService:
    @staticmethod
    async def get(id: int, db_session: AsyncSession) -> User:
        stmt = sa.select(User).where(User.id == id)
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()
```

Application services receive the session via their constructor:

```python
class SignupAppService:
    def __init__(self, params: SignupDAO, db_session: AsyncSession):
        self.params = params
        self.db_session = db_session

    async def invoke(self) -> User:
        user: User = await UserService.build_and_create(
            email=self.params.email,
            db_session=self.db_session,
        )
        return user
```

## The RequestCtxMiddleware — Request Context Tracking

The `RequestCtxMiddleware` generates a unique request ID for every incoming request and attaches a context object to `request.state.ctx`. This context is used for logging, error tracking, and tracing.

### Implementation

```python
from contextvars import ContextVar
from uuid import UUID, uuid4
from typing import Callable, Final, Optional
from fastapi.requests import Request
from starlette.types import ASGIApp
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, ConfigDict
from src.domains.user.dao import UserDAO

REQUEST_ID_CTX_KEY: Final[str] = "request_id"
_request_id_ctx_var: ContextVar[Optional[str]] = ContextVar(
    REQUEST_ID_CTX_KEY, default=None
)


async def _set_request_id() -> str:
    rid: str = str(uuid4())
    _request_id_ctx_var.set(rid)
    return rid


class RequestCtxDAO(BaseModel):
    request_id: Optional[UUID | str] = None
    path: Optional[str] = None
    request_ip: Optional[str] = None
    current_user: Optional[UserDAO] = Field(default=None)
    model_config = ConfigDict(
        title="request_ctx",
        from_attributes=True,
        arbitrary_types_allowed=True,
        json_encoders={
            UUID: lambda o: str(o),
        },
    )


def _get_request_id():
    return _request_id_ctx_var.get()


REQUEST_CTX_KEY: Final[str] = "ctx"
_request_ctx: ContextVar[Optional[RequestCtxDAO]] = ContextVar(
    REQUEST_CTX_KEY, default=RequestCtxDAO()
)


async def _set_request_ctx(request: Request) -> ContextVar[Optional[RequestCtxDAO]]:
    _rid: str = await _set_request_id()
    _rip: str = request.headers.get("x-forwarded-for", "")
    _ctx: RequestCtxDAO = RequestCtxDAO(
        request_id=_rid, path=request.base_url.path, request_ip=_rip
    )
    _request_ctx.set(_ctx)
    request.state.ctx = _ctx
    return _request_ctx


async def _get_request_ctx() -> Optional[RequestCtxDAO]:
    return _request_ctx.get()


class RequestCtxMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        await _set_request_ctx(request=request)
        response = await call_next(request)
        return response
```

### Key Design Decisions

1. **ContextVar for async safety**: The request ID and context are stored in `ContextVar` instances, which are safe across async tasks within the same request. This allows any code — not just route handlers — to access the current request context.
2. **Pydantic DAO for the context**: `RequestCtxDAO` is a Pydantic model that can hold the request ID, client IP, path, and the authenticated user. This makes the context typed and serializable.
3. **Dual storage**: The context is stored both in a `ContextVar` (for access in background tasks or deep call stacks) and in `request.state.ctx` (for direct access in route handlers and exception handlers).

## Testing with Middleware

When testing controllers, the database middleware needs to be swapped out so the test's transactional session is used instead. The `get_test_app` helper replaces the `DbMiddleware` with a test middleware that injects the test session.

```python
from typing import Dict, List, Callable
from fastapi import FastAPI, Request
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm.session import Session


async def get_test_app(app: FastAPI, dbsession: Session) -> FastAPI:
    """Replaces DbMiddleware with a test middleware that injects the test db session.

    Args:
        app (FastAPI): The default app object
        dbsession (Session): The test database session

    Returns:
        FastAPI: A FastAPI app configured for testing
    """

    async def test_db_session_middleware(request: Request, call_next):
        request.state.db = dbsession
        response = await call_next(request)
        return response

    user_middlewares = app.user_middleware
    middlewares: List = []
    for middleware in user_middlewares:
        options: Dict = middleware.options
        dispatch: Callable = middleware.options.get("dispatch", None)
        qualifying_name: str = None

        if dispatch:
            qualifying_name = dispatch.__qualname__

        if (
            options
            and dispatch
            and (
                qualifying_name == "db_session_middleware"
                or qualifying_name == "get_test_app.<locals>.test_db_session_middleware"
            )
        ) or str(middleware.cls.__name__) == "DbMiddleware":
            middlewares.append(
                Middleware(BaseHTTPMiddleware, dispatch=test_db_session_middleware)
            )
        else:
            middlewares.append(middleware)
    app.user_middleware = middlewares
    app.middleware_stack = app.build_middleware_stack()
    return app
```

This approach ensures that all route handlers receive the test's transactional session via `request.state.db`, and the transaction is rolled back after each test for isolation.

## Guidelines

1. **One concern per middleware**. Each middleware should handle exactly one cross-cutting concern. Do not combine database session management with request logging in a single middleware.
2. **Always use `try/finally` for resource cleanup**. If your middleware allocates a resource (database session, file handle, external connection), ensure it is cleaned up in a `finally` block.
3. **Use `request.state` for injection**. Attach data to `request.state` so downstream handlers and services can access it. This is the standard FastAPI mechanism for passing data through the request pipeline.
4. **Registration order matters**. Middleware added last executes first. Place foundational middleware (like `RequestCtxMiddleware`) at the end of the registration list so it runs before other middleware that might depend on it.
5. **Keep middleware async**. All middleware dispatch methods should be `async def`. Use `await` for any I/O operations within the middleware.
6. **Do not catch exceptions in middleware unless you handle them**. Let exceptions propagate to FastAPI's exception handlers. The `DbMiddleware` uses `try/finally` (not `try/except`) specifically because it needs cleanup but should not swallow errors.
7. **Middleware files go in `src/middleware/`**. Each middleware class gets its own file named after its concern: `db.py`, `request_id.py`, `rate_limit.py`, etc.
