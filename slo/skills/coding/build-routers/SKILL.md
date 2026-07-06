---
name: build-routers
description: Adding or modifying FastAPI endpoints, OpenAPI docs, and response wrappers.
when_to_use: Use when creating or changing HTTP routes, controllers, or the request/response
  envelope. Covers the /api/v1 prefix, SuccessResponseDAO/FailureResponseDAO, permissions,
  and Redoc docs.
group: coding
kind: skill
source_prompt: build-routers.md
---

# Routers

## Skill summary

- **Name:** `build-routers`
- **Description:** Adding or modifying FastAPI endpoints, OpenAPI docs, and response wrappers.
- **When to use:** Use when creating or changing HTTP routes, controllers, or the request/response envelope. Covers the /api/v1 prefix, SuccessResponseDAO/FailureResponseDAO, permissions, and Redoc docs.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-routers.md`

## Examples

- The user asks: "Add or revise the routers for this feature."
- You want the canonical build pattern before touching routers.

## Guidance

> **Companion rule:** every new FastAPI app or sub-app (uvicorn-served
> module) MUST also ship with paired VSCode launch configurations in
> both `orders-platform/.vscode/launch.json` and
> `orders-platform/orders_service/.vscode/launch.json`. See
> [`skills/coding/build-vscode-launch-configurations/SKILL.md`](../build-vscode-launch-configurations/SKILL.md).

Routers are the gateway to our workflows. The journey begins from the
main file which launches the application and sets up all the wiring for
the project.

---

## Service Namespace Prefix (MANDATORY)

Every service in the orders-platform monorepo serves its routes under a short,
**service-name-derived URL namespace prefix**. The version channel
(`/api/v1`) is preserved underneath. The two are orthogonal: the
namespace identifies the *service*; `/api/v1` identifies the *API
revision*. Concretely:

```
<service-namespace> + /api/v1 + <route>
```

### Registry

| Service                | Namespace | Full prefix      | Notes |
|------------------------|-----------|------------------|---|
| `orders_service` API      | `/o`      | `/o/api/v1`      | The FastAPI app exposing order/customer/chat routes. |
| `orders_service` A2A agent| `/oa`     | `/oa/api/v1`     | The Agent-to-Agent JSON-RPC + SSE surface. |
| `admin_ui`                | `/au`     | `/au/api/v1`     | The Vue 3 SPA's own server-side routes (if/when added). |
| `verifier`                | `/v`      | `/v/api/v1`      | The verifier API including `/v/api/v1/cli/*` and `/v/api/v1/healthz`. |

The pattern is mechanical: take the service name, take the leading
letters of each word (e.g. `orders_service` → `o`, `admin_ui` → `au`,
`orders_service a2a-agent` → `oa`, `verifier` → `v`). Sub-services within a
host process keep the host's namespace as a prefix
(`oa` extends `o`, not a new top-level).

### The rule

Every `app.include_router(...)` call **must** set
`prefix="<service-namespace>/api/v1"` (or
`prefix="<service-namespace>/api/v1/<group>"` for grouped routers like
`cli`). There are no exceptions. A bare `prefix="/api/v1"` is a
violation, even on the first router in a brand-new service.

```python
# verifier/src/web_app.py — GOOD
app.include_router(router=healthz_router,                 prefix="/v/api/v1")
app.include_router(router=environment_profiles_router,    prefix="/v/api/v1")
app.include_router(router=verification_runs_router,       prefix="/v/api/v1")
app.include_router(router=cli_router,                      prefix="/v/api/v1/cli")
```

```python
# BAD — bare /api/v1 with no service namespace
app.include_router(router=healthz_router, prefix="/api/v1")
```

### Why this exists

Multiple services live behind a single Traefik edge. Without a
service-namespace prefix, routers from different services collide on
`PathPrefix("/api/")`, and Traefik's first-matching-router-wins
semantics produces silently misrouted requests that look like 404s
from the wrong backend. The namespace makes router rules disjoint:

```yaml
# Traefik labels — clean, disjoint matches
traefik.http.routers.orders-api.rule=Host(...) && PathPrefix(`/o/`)
traefik.http.routers.verifier-api.rule=Host(...) && PathPrefix(`/v/`)
```

### Adding a new service

When you introduce a new long-lived service (FastAPI app, A2A agent,
or any process serving HTTP), pick its namespace at the same time you
pick its directory name. Add the row to the registry above, the row to
`skills/coding/application-structure/SKILL.md`, and the entry to
`<knowledge-base>/orders-platform-conventions/service-namespace-prefixes.md`.
The Traefik router rule for that service then uses
``PathPrefix(`<namespace>/`)`` — no `/api/` collision with siblings.

### Cross-references

- Ubiquitous language (one concept, one name across layers) →
  [`skills/design-and-analysis/ubiquitous-language/SKILL.md`](../../design-and-analysis/ubiquitous-language/SKILL.md)
- Traefik wiring at the deploy layer →
  [`skills/coding/build-vscode-launch-configurations/SKILL.md`](../build-vscode-launch-configurations/SKILL.md)
  is unrelated; the canonical entry is
  `<knowledge-base>/orders-platform-deployment/traefik-public-edge.md`
  and the renderer in `deployment/scripts/_render_app_stack.py` /
  `_render_verifier_stack.py`.

---

## DAO Placement Rules (STRICT)

**NEVER define DAOs, Pydantic models, or data classes inside
router/controller files.** Controllers are for routing and response
assembly only — they must not contain data structure definitions.

### Where each DAO type belongs

| DAO Type | Location | Examples |
|---|---|---|
| **Request body params** (input from the client) | Domain `dao.py` file | `CreateConversationParams` → `src/domains/conversation/dao.py`, `QueryRequest` → `src/domains/message/dao.py` |
| **Response wrappers** (API envelope: `data`, `errors`, `api_version`) | `src/routers/base_controller.py` | `SuccessResponseDAO`, `FailureResponseDAO`, `ResponseErrorsDAO` |
| **Domain DAOs** (database-backed entity representations) | Domain `dao.py` file | `ConversationDAO` → `src/domains/conversation/dao.py` |
| **Application service DAOs** (transient data between service layers) | App service file or `src/services/<name>/dao.py` | `ChatMessageResultDAO`, `ConversationContextItemDAO` |

### What controllers MUST do

1. **Import** request body DAOs from the relevant domain `dao.py`.
2. **Import** `success_response` and `failure_response` helpers from
   `src/routers/base_controller.py`.
3. **Import** domain DAOs (e.g., `ConversationDAO`) from domain
   `dao.py` for `model_validate()` and `response_model=`.
4. **Use** `success_response(payload=dao)` and
   `failure_response(error_code=..., errors=[...])` to build responses.

### What controllers MUST NOT do

1. Define `class SomeDAO(BaseModel)` — move it to the appropriate
   domain `dao.py`.
2. Define response wrappers (`ResponseErrorsDAO`, `SuccessResponseDAO`) —
   these live in `base_controller.py`.
3. Build inline response dicts (`{"data": ..., "api_version": "1.0",
   "errors": {...}}`) — use `success_response()` /
   `failure_response()` helpers instead.
4. Contain application logic — no data massaging, no async generators,
   no multi-step orchestration. All of that belongs in an application
   service with `invoke()`.
5. Build or accumulate data across multiple service calls — if a
   controller calls more than one method on a service (or calls multiple
   services in sequence), that orchestration belongs in an application
   service.

### Controller pattern for application services

```python
@router.post("/resource")
async def create_resource(request: Request, params: CreateResourceParams):
    svc: CreateResourceAppService = CreateResourceAppService(
        db_session=request.state.db,
        params=params,
    )
    result = await svc.invoke()
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=success_response(payload=result),
    )
```

The controller instantiates, calls `invoke()`, and returns. Nothing else.

---

## Centralized Exception Handling (routers raise, the app responds)

Routers must never build error JSON responses inline. They should
`raise` a typed exception and let a single, centrally-registered handler
convert it into the standard failure envelope. This is what keeps
controllers down to a few lines and makes the response shape consistent
across every route.

### The principle

| Layer | Responsibility |
|---|---|
| Router / controller | `raise <TypedException>(msg=..., code=..., http_error_code=...)` — nothing else for the error path |
| Domain / application service | Raises the same typed exceptions when it detects an invalid state (precondition failed, not found, conflict, …) |
| `_initialize_exception_handlers(app)` | Catches each typed exception, attaches `error_id` / `request_id`, optionally reports to Sentry, and returns a `JSONResponse` built from `FailureResponseDAO` / `failure_response()` |

If a router contains `try / except` around a service call only to
translate one error to another and build a response dict, the error
handling is in the wrong place. Move the translation to the service
(raise the right typed exception) and let the central handler build the
response.

### The exception hierarchy

Each exception base lives in a single file and carries the three fields
the central handler needs — `msg`, `code`, `http_error_code`:

```python
# coreutils/services/api/exceptions.py
from typing import Optional


class ApiExceptions(Exception):
    def __init__(
        self,
        msg: str,
        code: Optional[str] = None,
        http_error_code: Optional[int] = None,
    ):
        self.msg: Optional[str] = msg
        self.code: Optional[str] = code
        self.http_error_code: Optional[int] = http_error_code
```

Typed subclasses extend the base so the call site reads cleanly and so
specialised handlers can be registered for separate concerns (e.g.
auth):

```python
# coreutils/routers/api/exceptions.py
class ApiAuthExceptions(Exception): ...


class HttpUnauthorizedException(ApiAuthExceptions): pass
class AccountBlockedForbiddenException(ApiAuthExceptions): pass
class ActiveSubscriptionRequiredException(ApiAuthExceptions): pass
```

Every typed exception MUST set `msg`, `code`, and `http_error_code` —
the handler reads them directly into the response envelope without
inventing defaults.

### Registering handlers at app initialization

Handlers are registered **once**, in
`_initialize_exception_handlers(app)`, which is called from
`initialize_web_api(app)` (or `initialize_web_app(app)`). Each handler
is a closure decorated with `@app.exception_handler(ExceptionClass)`:

```python
# coreutils/web_api.py
def _initialize_exception_handlers(web_api: FastAPI) -> FastAPI:

    @web_api.exception_handler(ApiExceptions)
    async def handle_api_exceptions(request: Request, exc: ApiExceptions):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.x_request_id) if request.state.x_request_id else ""
        )
        with sentry_sdk.push_scope() as scope:
            scope.set_context("request", request)
            scope.set_extra(
                "context",
                {
                    "headers": dict(request.headers),
                    "error_id": error_id,
                    "request_id": request_id,
                    "code": f"{exc.code}",
                    "error_message": f"{exc.msg}",
                    "context": request.state.ctx,
                },
            )
            capture_exc(error=exc)
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).dict(),
        )

    # ... additional handlers for ApiAuthExceptions, ValidationError,
    # RequestValidationError, StarletteHTTPException, Exception ...

    return web_api
```

The wiring at app startup is one line in `initialize_web_api`:

```python
def initialize_web_api(web_api: FastAPI) -> FastAPI:
    _initialize_routers(web_api=web_api)
    _initialize_middleware(web_api=web_api)
    _initialize_exception_handlers(web_api=web_api)   # ← all handlers registered here
    return web_api
```

### Hooking Pydantic / FastAPI validation into the same envelope

FastAPI raises `RequestValidationError` for malformed request bodies
and `ValidationError` for direct DAO instantiations inside services.
Without explicit handlers, FastAPI returns its own JSON shape — which
breaks the `data` / `errors` / `api_version` contract clients depend
on.

Register both against the shared `validation_error_failure_response()`
helper from `base_controller.py`:

```python
@web_api.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    error_id: str = str(uuid4())
    request_id: str = (
        str(request.state.x_request_id) if request.state.x_request_id else ""
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=validation_error_failure_response(
            exc,
            error_id=error_id,
            request_id=request_id,
            error_code="bad_request",
        ),
    )


# Override RequestValidationErrors to follow the same envelope shape
@web_api.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError,
):
    error_id: str = str(uuid4())
    request_id: str = (
        str(request.state.x_request_id) if request.state.x_request_id else ""
    )
    with sentry_sdk.push_scope() as scope:
        scope.set_context("request", request)
        scope.set_extra(
            "context",
            {
                "error_id": error_id,
                "request_id": request_id,
                "code": "unprocessable_entity",
                "error_message": f"{exc}",
                "context": request.state.ctx,
            },
        )
        capture_exc(error=exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=validation_error_failure_response(
            exc, error_id=error_id, request_id=request_id,
        ),
    )
```

`validation_error_failure_response()` walks Pydantic's `raw_errors`,
produces `[<field>: <reason>, ...]`-formatted messages, and funnels
them through `failure_response(...)` so the envelope is byte-for-byte
identical to every other failure response in the API.

### A typical handler registration order

Inside `_initialize_exception_handlers` the handlers are registered in
this order:

1. `ApiExceptions` — domain/business errors raised from services.
2. `ApiAuthExceptions` — auth-specific errors (kept separate so auth
   can be logged / reported with different context).
3. `ValidationError` — programmatic Pydantic validation triggered by
   `Model(**bad_data)` inside services → 400.
4. `RequestValidationError` — FastAPI's body/query/path validation on
   incoming requests → 422.
5. `StarletteHTTPException` — fallback for explicit `HTTPException`
   raises from FastAPI internals.
6. `Exception` — catch-all that returns a sanitized 500 with
   `error_id` / `request_id`, logs the exception, and reports to Sentry.

**Order matters when subclasses share a registered base.** Register the
more specific subclass handler first so it wins over a base-class
handler that would otherwise shadow it.

### What this means for routers

A router writes the success path and **only** the success path. Errors
are surfaced by `raise <TypedException>(...)` from a service (or, in
the rare in-router case where a guard belongs in the controller, from
the controller itself) and then forgotten — the central handler
converts them.

❌ **Bad** — router does its own error handling:

```python
@router.get("/users/{id}")
async def get_user(request: Request, id: int):
    user = await UserService.get(id=id, db_session=request.state.db)
    if not user:
        return JSONResponse(
            status_code=404,
            content={
                "data": {"request_id": str(uuid4())},
                "api_version": "v1.0",
                "errors": {"msg": [f"User {id} not found"], "code": "user_not_found"},
            },
        )
    try:
        profile = UserProfileDAO.model_validate(user)
    except ValidationError as e:
        return JSONResponse(
            status_code=400,
            content={"errors": {"msg": [str(e)], "code": "bad_request"}},
        )
    return JSONResponse(status_code=200, content={"data": profile.model_dump()})
```

This is unreadable, duplicates envelope construction, and drifts away
from the standard response shape every time a contributor copies the
snippet.

✅ **Good** — router raises, central handler responds:

```python
@router.get("/users/{id}", name="get_user", response_model=UserProfileDAO)
async def get_user(request: Request, id: int):
    user: User = await UserService.get(id=id, db_session=request.state.db)
    if not user:
        raise NotFoundException(
            msg=f"User with id: {id} not found",
            code="user_not_found",
            http_error_code=404,
        )
    user_profile_dao: UserProfileDAO = UserProfileDAO.model_validate(user)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_response(payload=user_profile_dao),
    )
```

The router is back to two responsibilities: route the call, return the
success envelope. The `NotFoundException` becomes a 404 with the
standard `data` / `errors` / `api_version` shape automatically —
because its handler is registered once at app initialization. The body
that handles a `ValidationError` from
`UserProfileDAO.model_validate(user)` is gone too, because the
centrally-registered `ValidationError` handler covers it.

### Adding a new exception type

When a workflow needs a new failure mode that doesn't fit an existing
typed exception:

1. Add the subclass under the right base (`ApiExceptions` for business
   errors, `ApiAuthExceptions` for auth errors). Keep the
   `msg` / `code` / `http_error_code` triple.
2. If it should reuse an existing handler (the common case): **do
   nothing else**. The base-class handler picks it up automatically via
   `@app.exception_handler(ApiExceptions)`.
3. If it needs a different status code, message shape, or side effect
   (custom Sentry tagging, alternate logging): add a dedicated handler
   in `_initialize_exception_handlers`, registered **before** the
   base-class handler so the subclass wins.

**Never register handlers inside a router file.** All handler
registration lives in the single `_initialize_exception_handlers`
function so the full set of error responses can be reviewed in one
place.

---

## App initialization — `main.py`

Here is a sample of the `main.py` present in `src/main.py`. It also
sets up FastAPI's OpenAPI hooks for documentation.

> **Note:** the outer fence below uses **four** backticks
> (`` ```` ``) so the nested triple-backtick `json` blocks inside the
> Python `api_description` string render correctly.

````python
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from fastapi import FastAPI
from src.web_app import initialize_web_app
from fastapi.openapi.utils import get_openapi

api_description: str = """# Axis Tube API V 1.0.0
## API Base URL

```
https://api.aidolabs.com/
```

A sample endpoint would look like

```
GET https://api.aidolabs.com/api/v1/documents/22
```

Click the API URL under each section to view the full URL required.


## Response Object

The API response payloads below show only the primary resource object
in consideration. The resource is wrapped in a response wrapper as
described below.

```json
{
  "data": {},
  "api_version": "v1.0",
  "errors": {
    "code": null,
    "msg": []
  }
}
```

So for example a successful response with status `200 OK` will look
like this:

```json
{
    "data": {
        "id": 22,
        "user_id": 1,
        "slug": "9MMwnLDlPCKyyhET7owKs",
        "document_type": "sector",
        "document_subtype": "update",
        "title": "Real Estate Sector Update - March 08, 2024",
        "status": "categorized",
        "upload_path": "development/2024/11/16/AxisCap_Real Estate - SU - gray box, need 3-4 cover page paras Sample 1.pdf",
        "audio_path": null,
        "audio_generated_at": null,
        "created_at": "2024-11-16T03:07:26.997849+00:00",
        "updated_at": "2024-11-16T03:08:29.301097+00:00"
    },
    "api_version": "1.0",
    "errors": {
        "msg": [],
        "code": null
    }
}
```

A request that returns `401 Unauthorized` would look like this:

```json
{
    "data": {
        "request_id": "aaf1cc29-2068-4539-b677-3a1617668e21",
        "error_id": "c9255b21-37cb-4a5c-a7fb-c03f66702559"
    },
    "api_version": "v1.0",
    "errors": {
        "msg": ["Error unauthorized"],
        "code": "error_unauthorized"
    }
}
```

Notice the primary response schema remains consistent: `data` is
populated when the resource exists, and `errors.msg` / `errors.code`
carry a human-readable message and machine-readable code on failure.
"""


app = FastAPI(
    title="axis",
    swagger_ui_parameters={"syntaxHighlight.theme": "obsidian"},
    redoc_url="/ac/_redoc",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Axis Tube",
        version="1.0.0",
        description=api_description,
        routes=app.routes,
    )
    openapi_schema["info"]["x-logo"] = {
        # "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
app = initialize_web_app(app=app)
````

---

## App wiring — `web_app.py`

We define a `web_app.py` file under `src/web_app.py` that loads
routers, middleware, and exception handlers — the central place where
the patterns from the previous section are wired in.

```python
from typing import Dict, Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from src.middleware.db import DbMiddleware
from src.middleware.request_id import RequestCtxMiddleware

from src.routers import (
    health_controller,
    users_controller,
    documents_controller,
    signup_verifications_controller,
    summaries_controller,
    forgot_password_controller,
    classifications_controller,
    audios_controller,
    sessions_controller,
    reviews_controller,
)
from src.routers.v2 import documents_controller_v2
from src.routers.base_controller import (
    FailureResponseDAO,
    ResponseErrorsDAO,
    failure_response,
)
from src.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
    PreconditionFailedException,
    UnauthorizedException,
    ValueErrorException,
)
from config.cfg import cfg
from config.logger import log_error

INTERNAL_ERROR: str = "Internal Error"


def _initialize_routers(app: FastAPI) -> FastAPI:
    app.include_router(health_controller)
    app.include_router(users_controller)
    app.include_router(documents_controller)
    app.include_router(signup_verifications_controller)
    app.include_router(summaries_controller)
    app.include_router(forgot_password_controller)
    app.include_router(classifications_controller)
    app.include_router(audios_controller)
    app.include_router(sessions_controller)
    app.include_router(reviews_controller)
    app.include_router(documents_controller_v2)
    return app


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


def _initialize_exception_handlers(app: FastAPI) -> FastAPI:
    @app.exception_handler(ApiException)
    async def handle_api_exceptions(request: Request, exc: ApiException):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(msg=f"error_id={error_id} rid={request_id} ApiException: {exc}", e=exc)
        error_msg: str = exc.msg if cfg("ENV") == "development" else INTERNAL_ERROR
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[error_msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(NotFoundException)
    async def handle_not_found_exceptions(request: Request, exc: NotFoundException):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state and request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(msg=f"error_id={error_id} rid={request_id} NotFoundException: {exc}")
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(BadRequestException)
    async def handle_bad_request_exceptions(request: Request, exc: BadRequestException):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state and request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(msg=f"error_id={error_id} rid={request_id} BadRequestException: {exc}")
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(PreconditionFailedException)
    async def handle_precondition_failed_exceptions(
        request: Request, exc: PreconditionFailedException,
    ):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state and request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(
            msg=f"error_id={error_id} rid={request_id} PreconditionFailedException: {exc}"
        )
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(ValueErrorException)
    async def handle_value_error_exceptions(request: Request, exc: ValueErrorException):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state and request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(msg=f"error_id={error_id} rid={request_id} ValueErrorException: {exc}")
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(UnauthorizedException)
    async def handle_unauthorized_exceptions(request: Request, exc: UnauthorizedException):
        error_id: str = str(uuid4())
        request_id: str = (
            str(request.state.ctx.request_id)
            if request.state and request.state.ctx and request.state.ctx.request_id
            else ""
        )
        log_error(msg=f"error_id={error_id} rid={request_id} UnauthorizedException: {exc}")
        return JSONResponse(
            status_code=exc.http_error_code,
            content=FailureResponseDAO(
                data={"request_id": request_id, "error_id": error_id},
                api_version="v1.0",
                errors=ResponseErrorsDAO(msg=[exc.msg], code=exc.code),
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_errors(
        request: Request, exc: RequestValidationError,
    ):
        error_id: str = str(uuid4())
        request_id: str = str(request.state.ctx.request_id) if request.state.ctx else ""
        log_error(
            msg=f"error_id={error_id} rid={request_id} RequestValidationError: {exc}",
            e=exc,
        )
        error_message: str = exc.errors()[0].get("msg") or "Validation Error"
        failure_dao: Dict[str, Any] = failure_response(
            error_code="bad_request",
            errors=[f"{error_message}"],
            payload={"error_id": error_id, "request_id": request_id},
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=jsonable_encoder(failure_dao),
        )

    return app


def initialize_web_app(app: FastAPI) -> FastAPI:
    app = _initialize_routers(app=app)
    app = _initialize_middleware(app=app)
    app = _initialize_exception_handlers(app=app)
    return app
```

This contains all the wiring: router inclusion, middleware stack, and
the central exception handlers described in
`Centralized Exception Handling`.

---

## Base controller — `base_controller.py`

Under `src/routers/base_controller.py` we define the response envelope
DAOs (`SuccessResponseDAO`, `FailureResponseDAO`, `ResponseErrorsDAO`)
and the helpers (`success_response`, `failure_response`,
`validation_error_failure_response`) that controllers and the central
exception handlers share.

```python
from typing import Optional, Any, TypeVar, Generic, List, Dict
from uuid import UUID, uuid4
from json.decoder import JSONDecodeError

from pydantic import BaseModel, ConfigDict
from fastapi import Request, Header, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError

from config.logger import log_debug, log_error
from utils.datetime_support import date_to_datetime, date, datetime
from src.exceptions import UnauthorizedException
from src.domains.user.service import UserDAO
from src.domains.auth.service import AuthService

T = TypeVar("T")

API_VERSION: str = "1.0"


class ResponseErrorsDAO(BaseModel, Generic[T]):
    msg: List[str] = []
    code: Optional[str] = None
    model_config = ConfigDict(
        title="errors",
        arbitrary_types_allowed=True,
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            date: lambda v: date_to_datetime(dt=v).isoformat(timespec="microseconds"),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )


class SuccessResponseDAO(BaseModel, Generic[T]):
    data: Optional[T | Dict] = {}
    api_version: str = API_VERSION
    errors: ResponseErrorsDAO = ResponseErrorsDAO()
    model_config = ConfigDict(
        title="success_response",
        arbitrary_types_allowed=True,
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            date: lambda v: date_to_datetime(dt=v).isoformat(timespec="microseconds"),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )


class FailureResponseDAO(BaseModel, Generic[T]):
    data: Optional[T | Dict] = {}
    api_version: str = API_VERSION
    errors: ResponseErrorsDAO
    model_config = ConfigDict(
        title="failure_response",
        arbitrary_types_allowed=True,
        extra="ignore",
        from_attributes=True,
        json_encoders={
            date: lambda v: date_to_datetime(dt=v).isoformat(timespec="microseconds"),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )


def success_response(
    payload: T,
    api_version: str = API_VERSION,
    errors: Optional[ResponseErrorsDAO] = None,
) -> dict[str, Any]:
    if not errors:
        errors = ResponseErrorsDAO()

    success_response_dao = SuccessResponseDAO(
        api_version=api_version, data=payload, errors=errors,
    )
    return jsonable_encoder(success_response_dao)


def failure_response(
    error_code: str,
    errors: list[str] = [],
    payload: Optional[T] = {},
    api_version: str = API_VERSION,
) -> dict[str, Any]:
    failure_response_dao = FailureResponseDAO(
        api_version=api_version,
        data=payload,
        errors=ResponseErrorsDAO(msg=errors, code=error_code),
    )
    return jsonable_encoder(failure_response_dao)


def validation_error_failure_response(
    exc: RequestValidationError,
    error_id: Optional[str] = None,
    request_id: Optional[str] = None,
    error_code: Optional[str] = None,
) -> dict[str, Any]:
    error_messages: list[str] = []
    for err in exc.raw_errors:
        if type(err) == list:
            _msgs: list[str] = []
            for error in err:
                _msg: str = "".join([str(e["msg"]) for e in error.exc.errors()])
                _msgs.append(_msg)
            error_messages = [",".join(_msgs)]
        else:
            errors = err.exc.errors()
            error_messages = []
            for error in errors:
                if error["loc"] and error["loc"][0] == "__root__":
                    error_messages.append(f'{error["msg"]}')
                else:
                    error_messages.append(f'{error["loc"][0]}: {error["msg"]}')

    if not error_code:
        error_code = "unprocessable_entity"

    error_messages = [". ".join(error_messages)]
    log_error(
        msg=f"error_id={error_id} rid={request_id} RequestValidationError: {exc}",
        e=exc,
    )
    return failure_response(
        errors=error_messages,
        error_code=error_code,
        payload={"error_id": error_id, "request_id": request_id},
    )


async def log_request_body(request: Request) -> Request:
    content_type: Optional[str] = request.headers.get("content-type", None)
    path: str = f'"{request.method} {request.url}"'
    if (
        content_type
        and content_type == "application/json"
        and (request.method != "GET" and request.method != "DELETE")
    ):
        _body = await request.json()
        log_debug(msg=f"rid={request.state.x_request_id} path={path} params={_body}")
        request.state.body_params = _body
    return request


async def current_user(request: Request, authorization: str = Header(None)) -> UserDAO:
    if not authorization:
        raise UnauthorizedException(msg="Unauthorized")

    try:
        token: str = authorization.split()[-1]
        user: UserDAO = await AuthService.verify(db_session=request.state.db, jwt=token)
        if not user:
            raise UnauthorizedException(
                msg="Unauthorized", http_error_code=status.HTTP_401_UNAUTHORIZED,
            )
    except ValueError as e:
        log_error(msg=f"Error verifying token: {e}", e=e)
        raise UnauthorizedException(
            msg="Unauthorized", http_error_code=status.HTTP_401_UNAUTHORIZED,
        )
    return user
```

We use the `base_controller.py` helpers in every controller file.

---

## Sample controller

Here is an actual sample controller which routes control to an
application service and — in some exceptionally simple workflows — to
a domain service. This is a user controller defined under
`src/routers/v1`.

```python
from typing import List

from fastapi import Request, APIRouter, status
from fastapi.responses import JSONResponse

from src.routers.base_controller import success_response
from src.exceptions import NotFoundException
from src.services.signup.signup_app_service import SignupDAO, SignupAppService, User
from src.domains.user.dao import UserProfileDAO
from src.domains.user.service import UserService

router = APIRouter(prefix="/api/v1")


@router.post("/users", name="signup", response_model=UserProfileDAO)
async def signup(request: Request, signup_params: SignupDAO):
    svc: SignupAppService = SignupAppService(
        params=signup_params, db_session=request.state.db,
    )
    user: User = await svc.invoke()
    user_profile_dao: UserProfileDAO = UserProfileDAO.model_validate(user)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=success_response(payload=user_profile_dao),
    )


@router.get("/users/{id}", name="get_user", response_model=UserProfileDAO)
async def get_user(request: Request, id: int):
    user: User = await UserService.get(id=id, db_session=request.state.db)
    if not user:
        raise NotFoundException(
            msg=f"User with id: {id} not found",
            code="user_not_found",
            http_error_code=404,
        )
    user_profile_dao: UserProfileDAO = UserProfileDAO.model_validate(user)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_response(payload=user_profile_dao),
    )


@router.get("/users", name="list_users", response_model=List[UserProfileDAO])
async def list_users(request: Request, page: int = 1):
    if page < 1:
        page = 1
    users: List[User] = await UserService.get_many(
        db_session=request.state.db, page=page,
    )
    user_profile_dao: List[UserProfileDAO] = [
        UserProfileDAO.model_validate(user) for user in users
    ]
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_response(payload=user_profile_dao),
    )
```

Note that paths are always namespaced (`/api/v1/...`). Errors use
`raise <TypedException>(...)` — the centrally-registered handler
turns them into the standard envelope.

---

## Testing controllers

> Full controller-test conventions live in
> [`skills/coding/test-controllers/SKILL.md`](../test-controllers/SKILL.md). The example below is a
> reference snippet — read the dedicated test prompt before writing or
> modifying controller tests.

Here is a sample of a controller test:

```python
from unittest.mock import patch
import pytest
from sqlalchemy.orm.session import Session

from bushido.domains.event.live.zoom.dao import ZoomMeetingDAO, ZoomMeetingRegistrantDAO
from tests.db import db_session


class TestFoodLogsController:
    @pytest.mark.asyncio
    async def test_log_foods(self, db_session):
        """When a user logs for lunch
           And When the user passes `logged_at` for the previous date
           And when the `meal_tag` is not `ADHOC`
           And when the food is logged in `custom_gms`
           And when the `consumed_in_gms` attribute is not set to 0
                It should return success
                It should return the logged foods
        """
        from typing import Dict, List
        from decimal import Decimal

        from bushido.tasks.seed.add_foods import invoke as add_foods
        from bushido.services.v2.food_logs.create.service import (
            FoodLogApiParamsV2DAO,
            FoodLogsApiParamsV2DAO,
        )
        from bushido.domains.user.service import UserService
        from bushido.domains.food.service import FoodService
        from bushido.domains.meal_serving_size.service import (
            MEAL_SERVING_CUSTOM_GMS,
            MEAL_SERVING_LARGE,
        )
        from bushido.domains.food_logs.dao import MEAL_TAG_LUNCH
        from bushido.domains.product.product_services import ProductService
        from bushido.domains.product.product_dao import (
            ProductDAO,
            PRODUCT_ID_ALPHACOACH_FIT,
        )
        from bushido.domains.sessions.service import AuthSessionsService
        from bushido.main import app
        from utils.datetime_support import tz_now
        from httpx import AsyncClient
        from tests.db import get_test_app
        from fastapi.encoders import jsonable_encoder

        inserted_food_count = await add_foods(db_session=db_session)
        assert inserted_food_count > 0
        now = tz_now()

        user = await UserService.build_and_create(
            {"phone_number": "9920837799"}, db_session=db_session,
        )
        product: ProductDAO = await ProductService.get_by_name(name="alphacoach_fit")
        food1 = await FoodService.get_by_name(
            food_name="phad thai noodles (chicken)", db_session=db_session,
        )
        food2 = await FoodService.get_by_name(
            food_name="ceaser salad with bacon", db_session=db_session,
        )
        food_log1 = FoodLogApiParamsV2DAO(
            food_id=str(food1.id),
            product_id=str(product.id),
            portion_quantity=1,
            portion_size=MEAL_SERVING_CUSTOM_GMS,
            meal_tag=MEAL_TAG_LUNCH,
            logged_at=now.isoformat(),
            consumed_in_gms=Decimal("123.00"),
        )
        food_log2 = FoodLogApiParamsV2DAO(
            food_id=str(food2.id),
            product_id=str(product.id),
            portion_quantity=1,
            portion_size=MEAL_SERVING_LARGE,
            meal_tag=MEAL_TAG_LUNCH,
            logged_at=now.isoformat(),
        )

        session: Session = await AuthSessionsService.build_and_create(
            user_id=user.id, user_agent="test", db_session=db_session,
        )
        access_token: str = await AuthSessionsService._encode(session_id=session.id)

        app = await get_test_app(app=app, dbsession=db_session)

        params = FoodLogsApiParamsV2DAO(
            food_logs=[food_log1, food_log2], product_id=product.id,
        )

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                f"/bushido/api/v2/foods/log_foods",
                headers={
                    "Content-Type": "application/json",
                    "X-Product-Id": PRODUCT_ID_ALPHACOACH_FIT,
                    "Authorization": f"Bearer {access_token}",
                },
                json=jsonable_encoder(params),
            )

            assert response.status_code == 200
            response_body: Dict = response.json()
            data: Dict = response_body.get("data")
            food_logs: List[Dict] = data.get("food_log", [])
            assert len(food_logs) == 2
            assert float(food_logs[0].get("calories_calculated_for", None)) == float(123.00)

    @pytest.mark.asyncio
    async def test_log_foods_when_consumed_in_gms_is_0(self, db_session):
        """When a user logs for lunch
           And When the user passes `logged_at` for the previous date
           And when the `meal_tag` is not `ADHOC`
           And when the food is logged in `custom_gms`
           And when the `consumed_in_gms` attribute is set to 0
                It should return an error with http status code 422
        """
        from typing import Dict
        from decimal import Decimal

        from bushido.tasks.seed.add_foods import invoke as add_foods
        from bushido.services.v2.food_logs.create.service import (
            FoodLogApiParamsV2DAO,
            FoodLogsApiParamsV2DAO,
        )
        from bushido.domains.user.service import UserService
        from bushido.domains.food.service import FoodService
        from bushido.domains.meal_serving_size.service import (
            MEAL_SERVING_CUSTOM_GMS,
            MEAL_SERVING_LARGE,
        )
        from bushido.domains.food_logs.dao import MEAL_TAG_LUNCH
        from bushido.domains.product.product_services import ProductService
        from bushido.domains.product.product_dao import (
            ProductDAO,
            PRODUCT_ID_ALPHACOACH_FIT,
        )
        from bushido.domains.sessions.service import AuthSessionsService
        from bushido.main import app
        from utils.datetime_support import tz_now
        from httpx import AsyncClient
        from tests.db import get_test_app
        from fastapi.encoders import jsonable_encoder

        inserted_food_count = await add_foods(db_session=db_session)
        assert inserted_food_count > 0
        now = tz_now()

        user = await UserService.build_and_create(
            {"phone_number": "9920837799"}, db_session=db_session,
        )
        product: ProductDAO = await ProductService.get_by_name(name="alphacoach_fit")
        food1 = await FoodService.get_by_name(
            food_name="phad thai noodles (chicken)", db_session=db_session,
        )
        food2 = await FoodService.get_by_name(
            food_name="ceaser salad with bacon", db_session=db_session,
        )
        food_log1 = FoodLogApiParamsV2DAO(
            food_id=str(food1.id),
            product_id=str(product.id),
            portion_quantity=1,
            portion_size=MEAL_SERVING_CUSTOM_GMS,
            meal_tag=MEAL_TAG_LUNCH,
            logged_at=now.isoformat(),
            consumed_in_gms=Decimal("120.0"),
        )
        food_log2 = FoodLogApiParamsV2DAO(
            food_id=str(food2.id),
            product_id=str(product.id),
            portion_quantity=1,
            portion_size=MEAL_SERVING_LARGE,
            meal_tag=MEAL_TAG_LUNCH,
            logged_at=now.isoformat(),
        )

        session: Session = await AuthSessionsService.build_and_create(
            user_id=user.id, user_agent="test", db_session=db_session,
        )
        access_token: str = await AuthSessionsService._encode(session_id=session.id)

        app = await get_test_app(app=app, dbsession=db_session)

        params = FoodLogsApiParamsV2DAO(
            food_logs=[food_log1, food_log2], product_id=product.id,
        )
        params = jsonable_encoder(params)
        params["food_logs"][0]["consumed_in_gms"] = 0.0

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                f"/bushido/api/v2/foods/log_foods",
                headers={
                    "Content-Type": "application/json",
                    "X-Product-Id": PRODUCT_ID_ALPHACOACH_FIT,
                    "Authorization": f"Bearer {access_token}",
                },
                json=params,
            )

            assert response.status_code == 422
            response_body: Dict = response.json()
            errors: Dict = response_body.get("errors", {})
            code: str = errors.get("code", None)
            assert code == "unprocessable_entity"
```

### The `get_test_app` helper

`get_test_app` returns a FastAPI app modified for testing — it
replaces the production DB middleware with one that injects the
test-scoped session:

```python
from typing import Callable, Dict, List

from fastapi import FastAPI, Request
from fastapi.middleware import Middleware
from sqlalchemy.orm.session import Session
from starlette.middleware.base import BaseHTTPMiddleware


async def get_test_app(app: FastAPI, dbsession: Session) -> FastAPI:
    """Removes the existing `db_session_middleware` from the app
    middlewares and adds a db_session middleware bound to the test
    session.

    Args:
        app (FastAPI): The default app object.
        dbsession (Session): The database connection object.

    Returns:
        FastAPI: A FastAPI app suitable for in-process httpx tests.
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
                Middleware(BaseHTTPMiddleware, dispatch=test_db_session_middleware),
            )
        else:
            middlewares.append(middleware)
    app.user_middleware = middlewares
    app.middleware_stack = app.build_middleware_stack()
    return app
```

The snippet above is the synchronous-session variant. For async-session
controller tests (the canonical pattern in current projects), see
[`skills/coding/test-controllers/SKILL.md`](../test-controllers/SKILL.md).
