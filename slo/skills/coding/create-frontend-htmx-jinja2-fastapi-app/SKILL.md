---
name: create-frontend-htmx-jinja2-fastapi-app
description: Conventions for building server-rendered FastAPI + Jinja2 + HTMX frontends.
when_to_use: Use when creating or extending an HTMX/Jinja2 admin or operator surface
  backed by FastAPI.
group: coding
kind: skill
source_prompt: create-frontend-htmx-jinja2-fastapi-app.md
---

# Create Frontend HTMX + Jinja2 + FastAPI App

## Skill summary

- **Name:** `create-frontend-htmx-jinja2-fastapi-app`
- **Description:** Conventions for building server-rendered FastAPI + Jinja2 + HTMX frontends.
- **When to use:** Use when creating or extending an HTMX/Jinja2 admin or operator surface backed by FastAPI.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `create-frontend-htmx-jinja2-fastapi-app.md`

## Examples

- The user asks: "Build a server-rendered admin screen with HTMX interactions."
- You need the canonical folder and template structure for a FastAPI + Jinja2 + HTMX app.

## Guidance

This prompt documents every convention used in the **admin_ui** project — a server-rendered admin portal built with FastAPI, Jinja2 templates, and HTMX for interactivity. Follow these patterns exactly when building new pages, features, or an entirely new frontend application.

Reference implementation: `admin_ui/`

---

## Table of Contents

1. `Project Structure`
2. `Application Entry Point`
3. `App Initialization`
4. `Configuration`
5. `Router / Controller Pattern`
6. `Domain Layer (DAO + Service + Forms)`
7. `API Client Service`
8. `Template System`
9. `HTMX Conventions`
10. `Form Handling with WTForms`
11. `Middleware Stack`
12. `Session & Authentication`
13. `Custom Jinja2 Filters & Globals`
14. `Static Assets`
15. `Error Handling`
16. `Pagination`
17. `Flash Messages`
18. `File Operations`
19. `Celery Workers`
20. `Testing`
21. `Docker & Deployment`

---

## 1. Project Structure

```
<project>/
├── config/
│   ├── __init__.py
│   ├── cfg.py                    # Environment-based configuration loader
│   └── logger.py                 # Structured logging (JSON prod, text dev)
│
├── docker/
│   ├── app.Dockerfile            # Multi-stage build (builder → dev → release)
│   ├── docker-compose.dev.yml    # Dev services (Redis)
│   └── docker-compose.test.yml   # Test environment
│
├── environments/
│   ├── .env.template             # Template for required env vars
│   ├── .env.development          # Dev config (gitignored except template)
│   └── .env.test                 # Test config
│
├── src/
│   ├── main.py                   # FastAPI entry point (uvicorn startup)
│   ├── <app_name>_app.py         # App initialization (middleware, routes, exceptions)
│   │
│   ├── clients/                  # HTTP clients for backend API communication
│   │   ├── __init__.py
│   │   ├── api_client_service.py # Core HTTP client (aiohttp)
│   │   ├── gcs_client.py         # Google Cloud Storage
│   │   └── s3_client.py          # AWS S3
│   │
│   ├── connectors/               # External service connections
│   │   ├── async_redis.py        # Async Redis client
│   │   └── sync_redis.py         # Sync Redis client (for Celery)
│   │
│   ├── constants/                # Shared constants
│   │   └── common.py
│   │
│   ├── context/                  # Request context (request ID, session ID)
│   │   └── request_context.py
│   │
│   ├── domains/                  # Domain modules (one package per entity)
│   │   ├── base.py               # BaseForm, ApiResponseDAO, shared models
│   │   └── <entity>/
│   │       ├── dao.py            # Pydantic data transfer objects
│   │       ├── service.py        # API call logic (stateless class methods)
│   │       └── forms.py          # WTForms form classes (optional)
│   │
│   ├── errors/                   # Exception classes
│   │   └── base.py               # ApiException
│   │
│   ├── middlewares/              # Request pipeline
│   │   ├── user_info_middleware.py    # Auth check (Redis session cache)
│   │   ├── request_ctx.py            # Request/span ID propagation
│   │   ├── logging.py                # Request/response logging
│   │   └── transport_security_headers.py  # HSTS headers
│   │
│   ├── public/                   # Static files (served at /assets/)
│   │   └── assets/
│   │       ├── css/              # Theme CSS (light/dark modes)
│   │       ├── js/               # Custom JS
│   │       ├── vendor/           # Third-party libs (Bootstrap, HTMX, jQuery, etc.)
│   │       ├── img/              # Images
│   │       └── svg/              # SVG illustrations
│   │
│   ├── routers/                  # FastAPI routers (one per domain)
│   │   ├── base_controller.py    # Shared utilities, Jinja2Templates setup, filters/globals
│   │   └── <entity>_controller.py
│   │
│   ├── services/                 # Application services (orchestration)
│   │   └── <feature>_app_service.py
│   │
│   ├── tasks/                    # Celery workers
│   │   ├── __init__.py
│   │   └── worker.py             # Celery app initialization
│   │
│   └── templates/                # Jinja2 templates
│       ├── layouts/
│       │   ├── base_layout.html          # Main HTML5 skeleton
│       │   ├── _header.html              # Top navigation
│       │   ├── _footer.html              # Page footer
│       │   └── _left_navbar.html         # Sidebar navigation
│       ├── shared/
│       │   ├── pagination.html           # HTMX pagination component
│       │   └── form_errors.html          # Form validation errors
│       ├── errors/
│       │   ├── error_401.html
│       │   ├── error_404.html
│       │   └── api_error.html
│       └── <entity>/
│           ├── list.html                 # Full page (extends base_layout)
│           ├── _list.html                # HTMX partial (no extends)
│           ├── _new.html                 # Create form partial
│           ├── _edit.html                # Edit form partial
│           ├── _detail.html              # Detail view partial
│           └── _modal.html               # Bootstrap modal partial
│
├── tests/                        # Mirrors src/ structure
│   ├── conftest.py
│   ├── factory.py
│   ├── routers/
│   ├── domains/
│   └── services/
│
├── utils/                        # Shared utilities
│   ├── common.py
│   ├── datetime_support.py
│   └── api/
│       ├── auth.py               # HMAC request signing
│       └── authorization.py      # Permission helpers
│
├── Makefile
├── pyproject.toml
├── poetry.lock
├── launch.sh
└── launch-local.sh
```

---

## 2. Application Entry Point

**File:** `src/main.py`

```python
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.logger import logger
from config.cfg import cfg
from src.<app_name>_app import initialize_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(message=f"Started {cfg('APP_NAME')} at {cfg('DOMAIN')}")
    yield
    logger.info(message=f"Stopping {cfg('APP_NAME')}...")


app = FastAPI(
    title=cfg("APP_NAME"),
    docs_url=None,                                              # No Swagger in prod
    openapi_url="/<prefix>/_openapi.json" if not is_prod() else "",
    redoc_url="/<prefix>/_redoc" if not is_prod() else "",
    lifespan=lifespan,
)

app = initialize_app(app=app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        port=int(os.environ.get("PORT", 8083)),
        host=os.environ.get("HOST", "0.0.0.0"),
        forwarded_allow_ips="*",
        proxy_headers=True,
        limit_concurrency=120,
        backlog=20,
        workers=2,
        log_level="critical",
        reload=True,
    )
```

---

## 3. App Initialization

**File:** `src/<app_name>_app.py`

The initialization function registers routes, middleware, exception handlers, and static file serving — in that order.

```python
from fastapi import FastAPI, status
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette_wtf import CSRFProtectMiddleware
from src.routers.base_controller import templates

def initialize_app(app: FastAPI) -> FastAPI:
    _initialize_routes(app=app)
    _initialize_middleware(app=app)
    _initialize_exceptions(app=app)
    # Static files MUST be mounted last (catch-all route)
    app.mount("/", StaticFiles(directory="src/public"))
    return app


def _initialize_routes(app: FastAPI) -> None:
    """Register all routers. One include_router() call per controller."""
    app.include_router(health_controller.router)
    app.include_router(home_controller.router)
    app.include_router(vendors_controller.router)
    # ... all other controllers


def _initialize_middleware(app: FastAPI) -> None:
    """
    Middleware executes in REVERSE order of registration.
    Register outermost middleware LAST.
    """
    app.add_middleware(UserInfoMiddleware)                       # Auth check
    app.add_middleware(TransportSecurityHeadersMiddleware)       # Security headers
    app.add_middleware(SessionMiddleware, secret_key=cfg("SECRET_SESSION_KEY"))
    app.add_middleware(CSRFProtectMiddleware, csrf_secret=cfg("CSRF_SECRET"))
    app.middleware("http")(logging_middleware)                   # Request/response logging
    app.add_middleware(RequestCtxMiddleware)                     # Request ID context


def _initialize_exceptions(app: FastAPI) -> None:
    """Global exception handlers for API errors and validation errors."""

    @app.exception_handler(ApiException)
    async def handle_api_exceptions(request: Request, exc: ApiException):
        if exc.http_error_code == status.HTTP_401_UNAUTHORIZED:
            response = RedirectResponse(
                url=urlfor(request=request, name="login_form"),
                status_code=303,
            )
            response.delete_cookie("session-id")
            return response

        return templates.TemplateResponse(
            request=request,
            name="errors/api_error.html",
            context={"status": exc.http_error_code, "failure": FailureResponseDAO(...)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_errors(request, exc):
        error_msg = "\n".join([f"{err['loc'][1]}: {err['msg']}" for err in exc.errors()])
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=FailureResponseDAO(errors=ResponseErrorsDAO(msg=[error_msg])).dict(),
        )
```

---

## 4. Configuration

**File:** `config/cfg.py`

```python
import os

__cfg__: dict = {
    "ENV": os.environ.get("ENV", "development"),
    "APP_NAME": os.environ.get("APP_NAME", "<app_name>"),
    "DOMAIN": os.environ.get("DOMAIN", "localhost:8083"),
    "ORDERS_API_URL": os.environ.get("ORDERS_API_URL"),           # Backend API base URL
    "ORDERS_API_ACCESS_KEY": os.environ.get("ORDERS_API_ACCESS_KEY"),
    "ORDERS_API_ACCESS_SECRET": os.environ.get("ORDERS_API_ACCESS_SECRET"),
    "REDIS_URL": os.environ.get("REDIS_URL"),
    "SECRET_SESSION_KEY": os.environ.get("SECRET_SESSION_KEY"),
    "CSRF_SECRET": os.environ.get("CSRF_SECRET"),
    "GCS_BUCKET_NAME": os.environ.get("GCS_BUCKET_NAME"),
    # ... additional config keys
}

def cfg(key: str):
    return __cfg__.get(key) or os.getenv(key)

def is_prod():
    return cfg("ENV") == "production"

def is_dev():
    return cfg("ENV") == "development"
```

---

## 5. Router / Controller Pattern

**File pattern:** `src/routers/<entity>_controller.py`

### Rules

1. **Every router uses prefix `/ca`** (or a nested prefix like `/ca/vendors/{vendor_id}/accounts`)
2. **Every list view has TWO routes** — a full-page route and a partial route (for HTMX)
3. **Shared logic lives in a private `_` function** that both routes call with different template names
4. **All routes return `HTMLResponse`** via `templates.TemplateResponse()`
5. **POST routes validate forms, re-render partials on error, redirect on success**
6. **Use `response_class=HTMLResponse`** on every route decorator

### Complete Example

```python
from typing import Optional, List
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from src.routers.base_controller import templates, urlfor, get_pagination_urls, flash
from src.domains.vendors.service import VendorService
from src.domains.vendors.dao import VendorDAO
from src.domains.vendors.forms import VendorCreateForm

router = APIRouter(prefix="/ca")


# ── LIST (full page) ────────────────────────────────────────────────
@router.get("/vendors", name="list_vendors", response_class=HTMLResponse)
async def list_vendors(
    request: Request,
    page: Optional[int] = 0,
    size: Optional[int] = 10,
):
    return await _list_vendors_by_template(
        request=request,
        template_name="vendors/list.html",    # Full page — extends base_layout
        page=page,
        size=size,
    )


# ── LIST (HTMX partial) ────────────────────────────────────────────
@router.get("/vendors/_list", name="list_vendors_partial", response_class=HTMLResponse)
async def list_vendors_partial(
    request: Request,
    page: Optional[int] = 0,
    size: Optional[int] = 10,
):
    return await _list_vendors_by_template(
        request=request,
        template_name="vendors/_list.html",   # Partial — no extends
        page=page,
        size=size,
    )


# ── SHARED LOGIC ───────────────────────────────────────────────────
async def _list_vendors_by_template(
    request: Request,
    template_name: str,
    page: Optional[int] = 0,
    size: Optional[int] = 10,
):
    vendors: List[VendorDAO] = await VendorService.list(page=page + 1, size=size)
    first_url, next_url, previous_url = await get_pagination_urls(
        request=request,
        name="list_vendors_partial",
        page=page,
        size=size,
    )
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "vendors": vendors,
            "page": page,
            "size": size,
            "first_url": first_url,
            "next_url": next_url,
            "previous_url": previous_url,
            "target_replace_url": request.url_for("list_vendors"),
        },
    )


# ── NEW FORM (full page) ──────────────────────────────────────────
@router.get("/vendors/new", name="vendor_new", response_class=HTMLResponse)
async def new(request: Request):
    vendor_create_form: VendorCreateForm = VendorCreateForm(request)
    return templates.TemplateResponse(
        request=request,
        name="vendors/new.html",             # Full page wrapping _new.html
        context={"vendor_create_form": vendor_create_form},
    )


# ── CREATE (POST) ─────────────────────────────────────────────────
@router.post("/vendors", name="vendor_create", response_class=HTMLResponse)
async def create(request: Request):
    vendor_create_form: VendorCreateForm = await VendorCreateForm.from_formdata(
        request=request,
    )
    await vendor_create_form.validate()

    if vendor_create_form.errors:
        return templates.TemplateResponse(
            request=request,
            name="vendors/_new.html",        # Re-render form partial with errors
            context={"vendor_create_form": vendor_create_form},
        )

    try:
        await VendorService.create(vendor_create_form=vendor_create_form)
        return RedirectResponse(
            url=urlfor(request=request, name="list_vendors_partial"),
            status_code=303,
        )
    except Exception as e:
        vendor_create_form.form_errors.append(str(e))
        return templates.TemplateResponse(
            request=request,
            name="vendors/_new.html",
            context={"vendor_create_form": vendor_create_form},
        )


# ── DETAIL ─────────────────────────────────────────────────────────
@router.get(
    "/vendors/{vendor_id}",
    name="vendor_detail",
    response_class=HTMLResponse,
)
async def detail(request: Request, vendor_id: int):
    vendor: VendorDAO = await VendorService.get(vendor_id=vendor_id)
    return templates.TemplateResponse(
        request=request,
        name="vendors/detail.html",
        context={"vendor": vendor},
    )
```

### URL Naming Convention

- List page: `list_<entities>` (e.g., `list_vendors`)
- List partial: `list_<entities>_partial` (e.g., `list_vendors_partial`)
- New form: `<entity>_new` (e.g., `vendor_new`)
- Create action: `<entity>_create` (e.g., `vendor_create`)
- Detail page: `<entity>_detail` (e.g., `vendor_detail`)
- Edit form: `<entity>_edit` (e.g., `vendor_edit`)
- Update action: `<entity>_update` (e.g., `vendor_update`)
- Delete action: `<entity>_delete` (e.g., `vendor_delete`)

---

## 6. Domain Layer (DAO + Service + Forms)

Each domain entity lives in `src/domains/<entity>/` with up to three files.

### DAO — Pydantic Data Transfer Object

**File:** `src/domains/<entity>/dao.py`

```python
from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class VendorDAO(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    status: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        title = "vendor"
        from_attributes = True
        arbitrary_types_allowed = True
        str_strip_whitespace = True
        json_encoders = {
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        }


class VendorCreateDAO(VendorDAO):
    """Fields required for creating a new vendor."""
    type: str = Field(default="primary")
    status: str = Field(default="active")
```

### Service — Backend API Calls

**File:** `src/domains/<entity>/service.py`

Services are **stateless classes with `@classmethod` methods**. They use `ApiClientService` to call the backend API and return Pydantic DAOs.

```python
from typing import Optional, List, Dict, Any
from src.clients import ApiClientService
from src.domains.base import ApiResponseDAO
from src.domains.vendors.dao import VendorDAO, VendorCreateDAO
from config.cfg import cfg


class VendorService:
    BASE_PATH: str = "cc/api/v1/vendors"
    client_svc: ApiClientService = ApiClientService(base_url=cfg("ORDERS_API_URL"))

    @classmethod
    async def get(cls, vendor_id: int) -> VendorDAO:
        path: str = f"{cls.BASE_PATH}/{vendor_id}"
        response: ApiResponseDAO = await cls.client_svc.get(path=path)
        return VendorDAO.model_validate(response.data)

    @classmethod
    async def list(
        cls,
        page: Optional[int] = 1,
        size: Optional[int] = 10,
    ) -> List[VendorDAO]:
        params: Dict[str, Any] = {"page": page, "size": size}
        response: ApiResponseDAO = await cls.client_svc.get(
            path=cls.BASE_PATH,
            headers={"Content-Type": "application/json"},
            params=params,
        )
        return [VendorDAO.model_validate(d) for d in response.data]

    @classmethod
    async def create(cls, vendor_create_form: "VendorCreateForm") -> VendorDAO:
        vendor_dao = VendorCreateDAO(
            name=vendor_create_form.full_name.data,
            phone_number=vendor_create_form.phone_number.data,
            email=vendor_create_form.email.data,
        )
        response: ApiResponseDAO = await cls.client_svc.post(
            path=cls.BASE_PATH,
            json=vendor_dao.model_dump(exclude_none=True),
        )
        return VendorDAO.model_validate(response.data)

    @classmethod
    async def update(cls, vendor_id: int, data: dict) -> VendorDAO:
        path: str = f"{cls.BASE_PATH}/{vendor_id}"
        response: ApiResponseDAO = await cls.client_svc.put(
            path=path,
            json=data,
        )
        return VendorDAO.model_validate(response.data)
```

### Forms — WTForms with CSRF

**File:** `src/domains/<entity>/forms.py`

```python
from wtforms import StringField, EmailField, SelectField
from wtforms.validators import DataRequired, Email, Length
from src.domains.base import BaseForm


class VendorCreateForm(BaseForm):
    full_name: StringField = StringField(
        "Full Name",
        validators=[
            DataRequired("Please enter the vendor name."),
            Length(max=190),
        ],
    )

    email: EmailField = EmailField(
        "Primary Email",
        validators=[
            DataRequired("Please enter a valid email address"),
            Email(),
        ],
    )

    phone_number: StringField = StringField(
        "Phone Number",
        validators=[
            DataRequired("Please enter a valid phone number"),
            Length(max=15),
        ],
    )
```

**Base form (`src/domains/base.py`):**

```python
from starlette_wtf import StarletteForm


class BaseForm(StarletteForm):
    """Base form with CSRF protection via starlette-wtf."""
    form_errors: list = []

    class Meta:
        csrf = True
```

---

## 7. API Client Service

**File:** `src/clients/api_client_service.py`

The core HTTP client that all domain services use to communicate with the backend API.

```python
from aiohttp import ClientSession
from aiohttp_client_cache import CachedSession, CacheBackend


class ApiClientService:
    def __init__(self, base_url: str, cache: CacheBackend | None = None):
        self.base_url = base_url
        self.cache = cache

    def _new_session(self) -> ClientSession:
        return CachedSession(cache=self.cache) if self.cache else ClientSession()

    async def _request(self, method: str, path: str, **kwargs) -> ApiResponseDAO:
        async with self._new_session() as session:
            url = f"{self.base_url}/{path}"

            # Inject tracing headers (X-Request-ID, X-Span-ID)
            kwargs["headers"] = inject_trace_id_header(
                kwargs.get("headers", {}),
                get_request_id_context(),
            )

            async with session.request(method, url, **kwargs) as response:
                response_body = await response.json()
                try:
                    response.raise_for_status()
                    return ApiResponseDAO.model_validate(response_body)
                except Exception:
                    errors = response_body.get("errors", {})
                    raise ApiException(
                        msg=errors.get("msg", ["Unidentified error"])[0],
                        code=errors.get("code", "Unidentified error code"),
                        http_error_code=response.status,
                    )

    async def get(self, path: str, **kwargs) -> ApiResponseDAO:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> ApiResponseDAO:
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> ApiResponseDAO:
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> ApiResponseDAO:
        return await self._request("DELETE", path, **kwargs)

    @staticmethod
    async def get_authorized_headers() -> dict:
        """Generate HMAC signature headers for authenticated API calls."""
        nonce = uuid.uuid4().hex
        timestamp = int(datetime.now().timestamp())
        message = f"{nonce}___{timestamp}"
        signature = await sign_request(message, cfg("ORDERS_API_ACCESS_SECRET"))
        return {
            "X-AccessKey": cfg("ORDERS_API_ACCESS_KEY"),
            "X-Nonce": nonce,
            "X-Timestamp": str(timestamp),
            "X-Signature": signature,
        }
```

---

## 8. Template System

### Template Engine Setup

Templates are configured in `base_controller.py`:

```python
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory="src/templates")

# Register custom filters
templates.env.filters["format_datetime"] = format_datetime
templates.env.filters["format_currency_number"] = format_currency_number
templates.env.filters["format_number"] = format_number
templates.env.filters["format_time_since_now"] = format_time_since_now

# Register globals (accessible in all templates)
templates.env.globals["has_permission"] = has_permission
templates.env.globals["has_permission_with_vendor"] = has_permission_with_vendor
templates.env.globals["has_admin_role"] = has_admin_role
templates.env.globals["has_super_admin_role"] = has_super_admin_role
templates.env.globals["prettyprintjson"] = prettyprintjson
templates.env.globals["trunc"] = trunc
templates.env.globals["today"] = date.today()
```

### Template Inheritance Hierarchy

```
base_layout.html
  └── layouts/_header.html
  └── layouts/_left_navbar.html
  └── {% block body %}
  │     └── <entity>/list.html      (full page)
  │           └── {% include "<entity>/_list.html" %}   (partial)
  └── layouts/_footer.html
  └── {% block style %} / {% block scripts %}
```

### Full Page Template

**File:** `src/templates/<entity>/list.html`

```jinja2
{% extends "layouts/base_layout.html" %}

{% block title %}<Entity> List{% endblock %}

{% block body %}
  {% include "<entity>/_list.html" %}
{% endblock %}
```

### HTMX Partial Template

**File:** `src/templates/<entity>/_list.html`

```jinja2
<!-- Content — no {% extends %}, this is a standalone fragment -->
<div id="listing-<entities>" class="card">
    <!-- Card Header -->
    <div class="card-header card-header-content-md-between">
        <h4 class="card-header-title"><Entity> List</h4>
        <div class="d-flex gap-2">
            <a class="btn btn-primary btn-sm"
               href="{{ request.url_for('<entity>_new') }}">
                <i class="bi bi-plus-circle me-1"></i>New
            </a>
        </div>
    </div>

    <!-- Table -->
    <div class="table-responsive datatable-custom">
        <table class="table table-lg table-borderless table-hover">
            <thead class="thead-light">
                <tr>
                    <th>Name</th>
                    <th style="width: 80px">ID</th>
                    <th style="width: 421px">Action</th>
                </tr>
            </thead>
            <tbody>
                {% for item in items %}
                <tr>
                    <td>
                        <span class="d-block h5 text-inherit mb-0">{{ item.name }}</span>
                    </td>
                    <td>
                        <span class="d-block h5 text-inherit mb-0">{{ item.id }}</span>
                    </td>
                    <td style="text-align: right">
                        {% if has_permission(request, "<entity>", "read") %}
                        <a class="btn btn-white btn-sm"
                           href="{{ request.url_for('<entity>_detail', <entity>_id=item.id) }}">
                            <i class="bi bi-eye me-1"></i>View
                        </a>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- Pagination Footer -->
    <div class="card-footer">
        {% with paginate_items=items, target_element="#listing-<entities>",
                target_replace_url=request.url_for("list_<entities>"), page=page, size=size %}
            {% include "shared/pagination.html" ignore missing %}
        {% endwith %}
    </div>
</div>
```

### Form Template

**File:** `src/templates/<entity>/_new.html`

```jinja2
<div id="new_<entity>_form" class="content container-fluid">
    <!-- Error Display -->
    {% if <entity>_create_form.errors %}
        {% with form=<entity>_create_form, error_title="Please fix the following errors" %}
            {% include "shared/form_errors.html" ignore missing %}
        {% endwith %}
        <script>goTop();</script>
    {% endif %}

    <!-- Form with HTMX -->
    <form
        hx-post="{{ request.url_for('<entity>_create') }}"
        hx-target="#new_<entity>_form"
        hx-swap="outerHTML"
        class="py-md-5"
    >
        {{ <entity>_create_form.csrf_token() }}

        <div class="row justify-content-lg-center">
            <div class="col-lg-8">
                <div class="card card-lg active">
                    <div class="card-body">
                        <!-- Form Field -->
                        <div class="row mb-4">
                            <label for="name" class="col-sm-3 col-form-label form-label">
                                Name
                                <i class="bi-question-circle text-body ms-1"
                                   data-bs-toggle="tooltip"
                                   title="Help text"></i>
                            </label>
                            <div class="col-sm-9">
                                {{ <entity>_create_form.name(
                                    id="name",
                                    autofocus=true,
                                    placeholder="Enter name",
                                    class="form-control",
                                    type="text"
                                ) }}
                            </div>
                        </div>
                        <!-- More fields... -->
                    </div>

                    <div class="card-footer d-flex justify-content-end align-items-center">
                        <button type="button" class="btn btn-outline-danger rounded-pill me-2"
                                onclick="goBack()" title="Go Back">
                            <i class="bi bi-caret-left me-2"></i>Back
                        </button>
                        <button type="submit" class="btn btn-success rounded-pill">
                            <i class="bi bi-check-circle me-2"></i>Create
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </form>
</div>
```

### Detail Template

**File:** `src/templates/<entity>/_detail.html`

```jinja2
<div class="row">
    <div class="col-12">
        <div class="card mb-4">
            <div class="card-header">
                <div class="d-flex justify-content-between align-items-center">
                    <h4 class="mb-0" style="font-size: 14px;">
                        <i class="bi bi-info-circle me-2"></i>
                        {{ entity.name }} #{{ entity.id }}
                    </h4>
                    <div>
                        {% if entity.status == 'active' %}
                        <span class="badge bg-success px-3 py-2 fs-6">
                            <i class="bi bi-check-circle me-2"></i>Active
                        </span>
                        {% else %}
                        <span class="badge bg-danger px-4 py-2 fs-6">
                            <i class="bi bi-x-circle me-2"></i>Inactive
                        </span>
                        {% endif %}
                    </div>
                </div>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-3">
                        <div class="d-flex align-items-center mb-3">
                            <i class="bi bi-calendar-check text-primary me-3"></i>
                            <div>
                                <div class="text-muted small">Created Date</div>
                                <div class="fw-semibold" style="font-size: 13px;">
                                    {{ entity.created_at | format_datetime("medium") }}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
```

### Modal Template

**File:** `src/templates/<entity>/_modal.html`

```jinja2
<div class="modal fade" id="<entity>-{{ item.id }}-modal" tabindex="-1"
     aria-labelledby="<entity>-{{ item.id }}-modal-title" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered modal-lg" role="document">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Modal Title</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <!-- Content -->
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-primary" data-bs-dismiss="modal">
                    Close
                </button>
            </div>
        </div>
    </div>
</div>
```

---

## 9. HTMX Conventions

### Core HTMX Attributes Used

| Attribute | Usage |
| --- | --- |
| `hx-get` | Fetch content via GET (list partials, pagination) |
| `hx-post` | Submit forms via POST |
| `hx-target` | CSS selector of element to update (e.g., `#listing-vendors`) |
| `hx-swap="outerHTML"` | Replace the target element entirely (default for list/form swaps) |
| `hx-swap="innerHTML"` | Replace inner content only (used for detail sections) |
| `hx-replace-url` | Update browser URL bar after swap (for bookmarkable pages) |
| `hx-confirm` | Show confirmation dialog before request |
| `hx-encoding="multipart/form-data"` | Enable file uploads |
| `hx-on::before-request` | JS callback before request fires (e.g., scroll to top) |

### HTMX Redirect Pattern

When a POST succeeds and you need to redirect, use the `HX-Redirect` response header instead of a standard HTTP redirect. This tells HTMX to perform a client-side navigation:

```python
# In the router
response = HTMLResponse(status_code=303)
response.headers["HX-Redirect"] = str(request.url_for("list_vendors"))
return response
```

### HTMX Load Pattern (CDN)

```html
<!-- In base_layout.html <head> -->
<script src="https://unpkg.com/htmx.org"></script>
```

---

## 10. Form Handling with WTForms

### Form Lifecycle

1. **GET** — Create empty form: `form = VendorCreateForm(request)`
2. **POST** — Parse form data: `form = await VendorCreateForm.from_formdata(request=request)`
3. **Validate** — `await form.validate()`
4. **On error** — Re-render the form partial with `form.errors` populated
5. **On success** — Call domain service, then redirect

### CSRF Token

Every form **must** include the CSRF token:

```jinja2
<form hx-post="...">
    {{ form.csrf_token() }}
    <!-- fields -->
</form>
```

### Form Error Display

```jinja2
{% if form.errors %}
    {% with form=form, error_title="Please fix the following errors" %}
        {% include "shared/form_errors.html" ignore missing %}
    {% endwith %}
{% endif %}
```

The `shared/form_errors.html` template:

```jinja2
<div class="alert alert-soft-danger" role="alert">
    <h4>{{ error_title }}</h4>
    <ul class="mb-0 list-py-1">
        {% for (field_name, error) in form.errors.items() %}
            <li>{{ error[0] }}</li>
        {% endfor %}
    </ul>
</div>
```

---

## 11. Middleware Stack

Middleware executes in **reverse registration order**. The stack from outermost to innermost:

### 1. Request Context Middleware

Sets `X-Request-ID` and `X-Span-ID` for distributed tracing.

```python
class RequestCtxMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id")
        set_request_id_context(request_id)
        set_span_id_context()
        set_session_id_context(request.cookies.get("session-id", ""))

        response = await call_next(request)
        response.headers["X-Request-ID"] = get_request_id_context()
        response.headers["X-Span-ID"] = get_span_id_context()
        return response
```

### 2. Logging Middleware

Logs request method, path, params, response time, and status code. Skips `/assets/` and `/favicon.ico`.

### 3. CSRF Middleware

`CSRFProtectMiddleware` from `starlette-wtf` validates CSRF tokens on all POST/PUT/DELETE requests.

### 4. Session Middleware

`SessionMiddleware` from Starlette manages cookie-based sessions with `SECRET_SESSION_KEY`.

### 5. Transport Security Headers

Adds `Strict-Transport-Security: max-age=31536000; includeSubDomains` to all responses.

### 6. User Info Middleware (Auth Gate)

Checks `session-id` cookie against Redis cache. If valid, stores `UserRedisCacheDAO` in `request.state.user_info`. If invalid, returns 401 with `HX-Redirect` to login.

**Skipped paths:** `/favicon.ico`, `/assets/`, `/ca/users/login`, `/ca/users/verify`, `/ca/users/set_password`, `/ca/users/password_reset`, `/public/`, `/ca/health`

---

## 12. Session & Authentication

### Session Flow

1. User logs in → backend API returns user data + session token
2. Session token stored in Redis with user info as `UserRedisCacheDAO`
3. `session-id` cookie set on the browser
4. Every request: `UserInfoMiddleware` reads cookie → checks Redis → injects `request.state.user_info`
5. Templates access user info via `request.state.user_info`

### Accessing User Info in Routes

```python
user_info = request.state.user_info  # UserRedisCacheDAO or None
```

### Permission Checks in Templates

```jinja2
{% if has_permission(request, "account", "read") %}
    <!-- Show accounts link -->
{% endif %}

{% if has_permission_with_vendor(request, "account", "write", vendor.id) %}
    <!-- Show edit button -->
{% endif %}

{% if has_admin_role(request) %}
    <!-- Show admin section -->
{% endif %}
```

---

## 13. Custom Jinja2 Filters & Globals

### Filters

| Filter | Usage | Output |
| --- | --- | --- |
| `format_datetime("medium")` | `{{ dt \| format_datetime("medium") }}` | `25/12/2024` |
| `format_datetime("full")` | `{{ dt \| format_datetime("full") }}` | `10:30:45 25/12/2024` |
| `format_time()` | `{{ dt \| format_time() }}` | `10:30:45` |
| `format_currency_number(locale)` | `{{ amount \| format_currency_number("en_US") }}` | `1,000,000.00 USD` |
| `format_number("short")` | `{{ num \| format_number("short") }}` | `1M` |
| `format_number("long")` | `{{ num \| format_number("long") }}` | `1,000,000` |
| `format_time_since_now` | `{{ dt \| format_time_since_now }}` | `5 days ago` |

### Globals

| Global | Purpose |
| --- | --- |
| `has_permission(request, resource, action)` | Check user permission |
| `has_permission_with_vendor(request, resource, action, vendor_id)` | Check vendor-scoped permission |
| `has_admin_role(request)` | Check admin role |
| `has_super_admin_role(request)` | Check super admin role |
| `prettyprintjson(data)` | Pretty-print JSON for display |
| `trunc(text, length)` | Truncate text with ellipsis |
| `generate()` | Generate nanoid |
| `today` | Current date |

---

## 14. Static Assets

### Mounting

```python
# In app initialization — MUST be last (catch-all route)
app.mount("/", StaticFiles(directory="src/public"))
```

Assets are accessible at `/assets/...` because they live in `src/public/assets/`.

### Required Vendor Libraries

| Library | Purpose | Include |
| --- | --- | --- |
| Bootstrap 5 | UI framework | CSS + JS |
| Bootstrap Icons | Icon font | CSS |
| HTMX | Server-driven interactivity | JS (CDN) |
| jQuery | DOM manipulation | JS |
| Tom Select | Enhanced `<select>` inputs | CSS + JS |
| Flatpickr | Date/time picker | CSS + JS |
| DataTables | Advanced table features | CSS + JS |

### Base Layout Includes

```html
<head>
    <!-- Bootstrap -->
    <link rel="stylesheet" href="/assets/vendor/bootstrap-icons/font/bootstrap-icons.css">
    <link rel="preload" href="/assets/css/theme.min.css" data-hs-appearance="default" as="style">
    <link rel="preload" href="/assets/css/theme-dark.min.css" data-hs-appearance="dark" as="style">

    <!-- Vendor CSS -->
    <link rel="stylesheet" href="/assets/vendor/tom-select/dist/css/tom-select.bootstrap5.min.css">

    <!-- HTMX -->
    <script src="https://unpkg.com/htmx.org"></script>

    {% block style %}{% endblock %}
</head>
<body>
    {% block body %}{% endblock %}

    <!-- Vendor JS -->
    <script src="/assets/vendor/tom-select/dist/js/tom-select.complete.min.js"></script>
    <script src="/assets/js/hs.core.js"></script>

    {% block scripts %}{% endblock %}
</body>
```

---

## 15. Error Handling

### ApiException

All backend API errors are converted to `ApiException` by `ApiClientService`:

```python
class ApiException(Exception):
    def __init__(self, msg: str, code: str, http_error_code: int):
        self.msg = msg
        self.code = code
        self.http_error_code = http_error_code
```

### Global Exception Handler

Registered in `_initialize_exceptions()`:
- **401** → Delete session cookie, redirect to login (with `HX-Redirect` header for HTMX)
- **Other errors** → Render `errors/api_error.html` template

### Form Validation Errors

Handled at the router level — re-render the form partial with `form.errors` populated.

---

## 16. Pagination

### Shared Pagination Template

**File:** `src/templates/shared/pagination.html`

Uses HTMX to swap the list container in-place with URL updates:

```jinja2
<nav aria-label="Pagination">
    <ul class="pagination datatable-custom-pagination">
        <!-- First Page -->
        <li class="page-item {% if page < 1 %}disabled{% endif %}">
            <button class="page-link"
                    hx-get="{{ first_url }}"
                    hx-target="{{ target_element }}"
                    hx-swap="outerHTML"
                    hx-on::before-request="window.scrollTo({top: 0, behavior: 'smooth'})"
                    hx-replace-url="{{ target_replace_url.include_query_params(page=0, size=size) }}">
                First
            </button>
        </li>

        <!-- Previous -->
        <li class="page-item {% if page < 1 %}disabled{% endif %}">
            <button class="page-link"
                    hx-get="{{ previous_url }}"
                    hx-target="{{ target_element }}"
                    hx-swap="outerHTML"
                    hx-replace-url="{{ target_replace_url.include_query_params(page=page-1, size=size) }}">
                Prev
            </button>
        </li>

        <!-- Next -->
        <li class="page-item
            {% if (size is not none and paginate_items|length < size) or paginate_items|length <= 0 %}
            disabled
            {% endif %}">
            <button class="page-link"
                    hx-get="{{ next_url }}"
                    hx-target="{{ target_element }}"
                    hx-swap="outerHTML"
                    hx-replace-url="{{ target_replace_url.include_query_params(page=page+1, size=size) }}">
                Next
            </button>
        </li>
    </ul>
</nav>
```

### Usage in List Templates

```jinja2
{% with paginate_items=items,
        target_element="#listing-<entities>",
        target_replace_url=request.url_for("list_<entities>"),
        page=page,
        size=size %}
    {% include "shared/pagination.html" ignore missing %}
{% endwith %}
```

### Router Pagination Helper

```python
from src.routers.base_controller import get_pagination_urls

first_url, next_url, previous_url = await get_pagination_urls(
    request=request,
    name="list_vendors_partial",   # Route name for the PARTIAL endpoint
    page=page,
    size=size,
)
```

---

## 17. Flash Messages

### Setting Flash Messages

```python
from src.routers.base_controller import flash

await flash(request=request, message="Vendor created successfully", category="success")
await flash(request=request, message="Vendor not found", category="danger")
```

### Displaying in Templates

Flash messages are stored in the session and displayed once:

```jinja2
{% for message in get_flash_messages(request) %}
    <div class="alert alert-{{ message.category }}">{{ message.message }}</div>
{% endfor %}
```

---

## 18. File Operations

### Cloud Storage Clients

Two client implementations for file upload/download:

| Client | Config Key | Purpose |
| --- | --- | --- |
| `gcs_client.py` | `GCS_BUCKET_NAME` | Google Cloud Storage |
| `s3_client.py` | `S3_*` | AWS S3 |

### File Upload Pattern

Templates use HTMX with multipart encoding:

```jinja2
<form hx-post="{{ upload_url }}"
      hx-target="#upload-result"
      hx-swap="outerHTML"
      hx-encoding="multipart/form-data">
    {{ form.csrf_token() }}
    <input type="file" name="file" class="form-control">
    <button type="submit" class="btn btn-primary">Upload</button>
</form>
```

### Streaming Downloads

Use `StreamingResponse` for large file downloads:

```python
from starlette.responses import StreamingResponse

@router.get("/download/{file_id}")
async def download(request: Request, file_id: str):
    stream = await file_service.get_stream(file_id)
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

---

## 19. Celery Workers

### Worker Setup

```python
# src/tasks/worker.py
from celery import Celery
from config.cfg import cfg

celery_app = Celery(
    "admin_tasks",
    broker=cfg("REDIS_URL"),
    backend=cfg("REDIS_URL"),
)
```

### Task Pattern

```python
# src/tasks/<task_name>_task.py
from src.tasks.worker import celery_app

@celery_app.task(name="run_allocation_engine")
def run_allocation_engine(vendor_id: int, rule_id: int):
    # Task implementation
    pass
```

### Running Workers

```bash
make launch-allocation-engine-worker   # Start Celery worker
make launch-flower                     # Celery monitoring dashboard
```

---

## 20. Testing

### Dependencies

```toml
[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "black",
    "freezegun",          # Time mocking
    "memory-profiler",    # Performance testing
]
```

### Test Structure

Mirror `src/` under `tests/`:

```
tests/
├── conftest.py
├── factory.py
├── routers/test_<entity>_controller.py
├── domains/test_<entity>/
├── services/test_<service>.py
└── utils/test_<util>.py
```

### Testing a Router

```python
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient


class TestVendorsController:
    @pytest.mark.asyncio
    @patch("src.domains.vendors.service.VendorService.list", new_callable=AsyncMock)
    async def test_list_vendors(self, mock_list, async_client: AsyncClient):
        mock_list.return_value = [VendorDAO(id=1, name="Test")]
        response = await async_client.get("/ca/vendors")
        assert response.status_code == 200
        assert "Test" in response.text
```

### Testing a Domain Service

```python
class TestVendorService:
    @pytest.mark.asyncio
    @patch("src.clients.ApiClientService.get", new_callable=AsyncMock)
    async def test_get_vendor(self, mock_get):
        mock_get.return_value = ApiResponseDAO(data={"id": 1, "name": "Test"})
        vendor = await VendorService.get(vendor_id=1)
        assert vendor.name == "Test"
```

### Running Tests

```bash
make test-local           # Local without Docker
make test                 # Docker-based CI
make test-coverage        # With coverage report
pytest -sv tests/path/to/test.py::TestClass::test_method  # Single test
```

---

## 21. Docker & Deployment

### Dockerfile (Multi-Stage)

```dockerfile
# ─── Builder ────────────────────
FROM python:3.11-alpine AS builder
WORKDIR /app
RUN pip install poetry
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install --prefix=/install -r requirements.txt

# ─── Dev ────────────────────────
FROM python:3.11-alpine AS dev
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]

# ─── Release ────────────────────
FROM python:3.11-alpine AS release
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
EXPOSE 8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
```

### Docker Compose (Dev)

```yaml
version: "3"
services:
  redis:
    image: redis:7.4
    ports:
      - "6379:6379"
```

### Makefile Targets

```makefile
run-local:
	./launch-local.sh

dev-up:
	docker compose -f docker/docker-compose.dev.yml up -d

dev-down:
	docker compose -f docker/docker-compose.dev.yml down

test-local:
	pytest -sv tests/

test:
	docker compose -f docker/docker-compose.test.yml run --rm test

fmt:
	black src/ tests/ utils/ config/

lint:
	black --check src/ tests/ utils/ config/
```

---

## Key Dependencies (pyproject.toml)

```toml
[project]
dependencies = [
    "fastapi",
    "jinja2",
    "starlette-wtf",        # CSRF + WTForms integration
    "wtforms",               # Form validation
    "email-validator",       # Email field validation
    "aiohttp",               # Async HTTP client for backend API
    "aiohttp-client-cache",  # HTTP response caching
    "redis",                 # Session storage and caching
    "celery[redis]",         # Background task queue
    "celery-redbeat",        # Periodic task scheduler
    "pydantic",              # Data validation (DAOs)
    "aiofiles",              # Async file operations
    "google-cloud-storage",  # GCS file operations
    "boto3",                 # S3 file operations
    "pandas",                # Data processing (executors)
    "anthropic",             # Claude AI integration
    "python-observability",  # OpenTelemetry tracing
    "uvicorn",               # ASGI server
]
```

---

## Appendix A — Applying These Conventions to a NON-BFF App (added 2026-06-01)

> **Nothing above is removed.** This appendix records new information discovered while applying this prompt to `integration_tests/src/apps/reporting_app/` (the `orders-reporting` dashboard) — a FastAPI app that is **not** a stateless BFF. The body of this prompt documents `admin_ui`, which proxies CRUD to a backend orders API. When the target app instead owns its own datastore and serves at root, several sections of this prompt do not map. The **mandatory, always-applicable** parts are the structural ones; the **conditional** parts assume the BFF shape.

### A.1 What is always mandatory (regardless of app shape)

These hold for *every* FastAPI + Jinja2 app in the workspace:

1. **A `routers/` package** with one `APIRouter` per domain (`<entity>_controller.py`) plus a `base_controller.py` that owns the `Jinja2Templates` instance and registered filters/globals. Routes are **never** defined as nested closures inside the app-init function.
2. **A `templates/` tree at the same hierarchy as the app's domains**, organised by router name: `templates/<router_name>/<page>.html`, with a `layouts/base_layout.html` the pages extend. Routes select templates by name via `templates.TemplateResponse(...)`.
3. **HTML is produced by Jinja2 templates — never hand-concatenated as Python f-strings.** Manual `html.escape()` in Python string-building is an anti-pattern; Jinja autoescaping replaces it.
4. **Thin handlers.** No inline SQLAlchemy / business logic in route bodies — delegate to domain/app services. Module-top imports, not in-body imports.

### A.2 What is CONDITIONAL on the BFF shape (skip for a self-contained app)

| Body section | Assumes (BFF) | If the app owns its own DB / serves at root |
| --- | --- | --- |
| §5 prefix `/ca` on every router | Admin-UI URL namespace | Use `APIRouter()` with **no prefix** if the app serves at `/`. URL paths are a public contract (install scripts, systemd, bookmarks) — don't relocate them for convention's sake. |
| §7 `ApiClientService` (aiohttp + HMAC signing) | A backend API to proxy to | **Skip.** Controllers call local domain/app services directly. There is no upstream API to sign requests to. |
| §10–12 WTForms + `starlette-wtf` CSRF + Session + UserInfo middleware | Multi-user browser auth via Redis sessions | **Skip** for a single-operator / localhost / CI tool. Don't add an auth stack that has no threat model. |
| §11 Redis-backed middleware | Redis present | **Skip** if the app has no Redis. |
| §9 HTMX attributes (`hx-get`/`hx-post`/`hx-target`) | HTMX-driven partial swaps | **Conflict, see A.3.** Plain `fetch()` / `EventSource` (SSE) is an acceptable interactivity layer. The router+template split is mandatory; converting existing `fetch`/SSE JS to `hx-*` is optional. |
| §14 Bootstrap / Bootstrap-Icons / jQuery / Tom Select / Flatpickr / DataTables | Admin-UI design system | **Skip** if the app ships its own inline theme and no vendor assets. Centralise that theme in `base_layout.html` instead. |

### A.3 Explicit CONFLICT — "HTMX" in the title vs. `fetch`/SSE apps

The prompt title and §9 imply HTMX is required. It is not, for two cases this prompt did not originally cover:

- **SSE log/stream pages** are better served by `EventSource` than HTMX (`hx-sse` exists but adds no value for a raw text tail).
- **JSON control endpoints** consumed by small inline `fetch()` calls don't benefit from HTMX swaps.

**Resolution adopted:** keep the structural conventions (routers + Jinja templates + thin handlers) as hard requirements; treat the *specific* interactivity mechanism (HTMX vs `fetch`/SSE) as the app author's choice. This prompt should be read as "**server-rendered Jinja2 + FastAPI, with HTMX as the default-but-not-mandatory interactivity layer.**"

### A.4 Packaging for pipx/wheel-distributed apps (verified 2026-06-01, Poetry 2.3.3)

When the app is distributed as a wheel via Poetry (`poetry.core.masonry.api`), the behaviour was **verified empirically** (probe template built + installed into a clean venv):

- **Templates inside the declared `packages` tree ARE shipped by default.** Poetry-core packages all non-gitignored files under `{ include = "src" }`, not just `.py`. A `templates/**/*.html` tree under `src/<app>/` needs **no** explicit `[tool.poetry] include` entry — provided the files are committed (CI builds from a clean checkout, so only tracked files exist).
- **Path resolution holds in the installed wheel.** The package installs to `<site-packages>/src/<app>/`, so `Path(__file__).resolve().parent.parent / "templates"` resolves correctly there, matching the source layout.
- **Caveat:** the above is for templates living *inside* a declared package directory. Assets *outside* the package tree (e.g. `docker/`, top-level config) still require an explicit `include` entry. And remember to add `jinja2` to `dependencies`.

> Earlier guidance here claimed templates are NOT shipped by default and required an explicit `include`. That was **disproven** by the verification above for the in-package-tree case. Still: build the wheel and run it from a clean venv — a source-tree test cannot catch a packaging/path bug.

> Cross-reference: applied in `integration_tests` plan `<feature-specifications-root>/15-reporting-app-routers-templates-refactor/plan.md`.
