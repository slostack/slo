---
name: bootstrap-project-scaffolding
description: 'Python: Creating a brand-new project/service in the workspace.'
when_to_use: For Python projects only. Use when scaffolding a new repo from scratch (folders, Makefile,
  launch scripts, env files).
group: languages
kind: skill
source_prompt: bootstrap-project-scaffolding.md
---

# Bootstrap Project Scaffolding

## Skill summary

- **Name:** `bootstrap-project-scaffolding`
- **Description:** Creating a brand-new project/service in the workspace.
- **When to use:** Use when scaffolding a new repo from scratch (folders, Makefile, launch scripts, env files).
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `bootstrap-project-scaffolding.md`

## Examples

- The user asks for help with: Creating a brand-new project/service in the workspace.
- Use when scaffolding a new repo from scratch (folders, Makefile, launch scripts, env files).

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

When asked to scaffold or bootstrap a new project within the orders-platform monorepo, generate the full directory structure and setup files following the patterns described below. The new project should be a sibling of the `orders_service/` folder inside the workspace root.

---

## 1. Directory Structure

Create this exact folder layout, substituting `<project>` with the actual project name:

```
<project>/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── RESEARCH.md
├── Makefile
├── alembic.ini
├── pyproject.toml
├── launch_dev.sh
│
├── config/
│   ├── __init__.py
│   ├── cfg.py
│   ├── ai_model_config.py
│   └── logger.py
│
├── connectors/
│   └── async_pg.py
│
├── db/
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── (empty — migrations generated via alembic)
│
├── docker/
│   ├── docker-compose.dev.yml
│   └── postgres/
│       ├── Dockerfile
│       └── init.sh
│
├── environments/
│   ├── local.env
│   └── test.env
│
├── scripts/
│   └── local_tests/
│       ├── setup.sh
│       ├── setup_test_db.sql
│       └── template_setup.sql
│
├── src/
│   ├── main.py
│   ├── agents/
│   │   ├── __init__.py
│   │   └── base.py
│   ├── domains/
│   │   └── (one sub-package per domain entity)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── model_base.py
│   ├── services/
│   │   └── (application-level orchestration services)
│   ├── tasks/
│   │   └── __init__.py
│   └── utils/
│       ├── __init__.py
│       └── datetime_support.py
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── agents/
    │   └── __init__.py
    ├── domains/
    │   └── __init__.py
    └── services/
        └── __init__.py
```

---

## 2. Config Layer (`config/`)

### cfg.py

Environment-aware configuration loader. All env vars use a project-specific prefix (e.g. `ORDERS_`). Replace `ORDERS` with the new project's uppercase name.

```python
import os

__all__ = ["cfg", "__cfg__"]

env = os.environ.get("<PREFIX>_ENV", "development")


def is_dev():
    return env == "development"


def is_test():
    return env == "test"


def is_staging():
    return env == "staging"


APP_NAME = os.environ.get("<PREFIX>_APP_NAME", "<PROJECT>")
DB_URL = os.environ.get("<PREFIX>_DB_URL", None)
DB_URL_ASYNC = os.environ.get("<PREFIX>_DB_URL_ASYNC", None)
APP_DIR = os.environ.get("<PREFIX>_APP_DIR", None)
REDIS_URL = os.environ.get("<PREFIX>_REDIS_URL", None)
BASE_URL = os.environ.get("<PREFIX>_BASE_URL", "http://localhost:7777/<project>")
DOMAIN = os.environ.get("<PREFIX>_DOMAIN", "localhost:7777")
LOG_FORMAT = os.environ.get("<PREFIX>_LOG_FORMAT", "json")

# Add additional config keys as needed (API keys, DBOS, Minio, etc.)

__cfg__: dict[str, str | None] = {
    "ENV": env,
    "APP_NAME": APP_NAME,
    "APP_DIR": APP_DIR,
    "BASE_URL": BASE_URL,
    "DB_URL": DB_URL,
    "DB_URL_ASYNC": DB_URL_ASYNC,
    "REDIS_URL": REDIS_URL,
    "LOG_FORMAT": LOG_FORMAT,
}


def cfg(key: str):
    return __cfg__.get(key) or os.getenv(key)
```

### logger.py

Structured logging with JSON (production) and text (dev) formatters. Uses `pythonjsonlogger` for JSON output.

```python
import logging
import logging.config
from logging import Logger, getLogger

from config.cfg import is_test, is_dev, cfg

_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_TEXT_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(funcName)s:%(lineno)d | %(message)s"
_JSON_FMT = "%(asctime)s %(levelname)s %(name)s %(filename)s %(funcName)s %(lineno)d %(message)s"


def _formatter_config() -> dict:
    if cfg("LOG_FORMAT") == "text":
        return {
            "format": _TEXT_FMT,
            "datefmt": _LOG_DATEFMT,
        }
    return {
        "()": "pythonjsonlogger.json.JsonFormatter",
        "fmt": _JSON_FMT,
        "datefmt": _LOG_DATEFMT,
        "json_default": str,
    }


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": _formatter_config(),
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "standard",
        },
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["console"],
    },
    "loggers": {
        "<project>": {"level": "DEBUG", "propagate": True},
        "uvicorn": {"level": "DEBUG", "propagate": True},
        "uvicorn.error": {"level": "INFO", "propagate": True},
        "uvicorn.access": {"level": "INFO", "propagate": True},
        "httpx": {"level": "INFO", "propagate": True},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

log: Logger = getLogger("<project>")


def capture_exc(error: Exception) -> None:
    if is_dev() or is_test():
        return None
    return None


def log_debug(msg: str, **kwargs):
    if cfg("ENV") != "prod":
        log.debug(msg, stacklevel=2, extra=kwargs)


def log_info(msg: str, **kwargs):
    log.info(msg, stacklevel=2, extra=kwargs)


def log_error(
    msg: str,
    e: Exception = None,
    stack_trace: bool = True,
    **kwargs,
):
    if not stack_trace:
        log.error(msg, stacklevel=2, extra=kwargs)
    else:
        log.error(msg, exc_info=True, stack_info=True, stacklevel=2, extra=kwargs)

    if e and (not is_test() or not is_dev()):
        capture_exc(error=e)
```

---

## 3. Database Connector (`connectors/async_pg.py`)

Async PostgreSQL connector using SQLAlchemy's async engine. Provides both a direct session getter and a context-manager session factory.

```python
import sqlalchemy
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.orm import sessionmaker
from config.cfg import cfg
from contextlib import asynccontextmanager


metadata = sqlalchemy.MetaData()

pool_size: int = 8 if cfg("ENV") == "staging" else 10
max_overflow: int = 2 if cfg("ENV") == "staging" else 10

async_engine: AsyncEngine = create_async_engine(
    cfg("DB_URL_ASYNC"),
    pool_size=pool_size,
    echo=False,
    max_overflow=max_overflow,
    pool_use_lifo=True,
    pool_recycle=1300,
    echo_pool=True,
)
AsyncSessionLocal: AsyncSession = sessionmaker(
    async_engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession,
)  # type: ignore


async def get_async_session() -> AsyncSession:
    session: AsyncSession = AsyncSessionLocal()  # type: ignore
    return session


@asynccontextmanager
async def get_async_sessionmaker():
    session: AsyncSession = AsyncSessionLocal()  # type: ignore
    try:
        yield session
    finally:
        if session.is_active:
            await session.close()
```

---

## 4. SQLAlchemy Model Base (`src/models/`)

### model_base.py

Declarative base class with automatic table name resolution (CamelCase to snake_case), a `.dict()` helper, and `__repr__` support.

```python
import typing
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.orm import as_declarative, declared_attr
import re


def resolve_table_name(name):
    names = re.split("(?=[A-Z])", name)
    return "_".join([x.lower() for x in names if x])


class CustomBase:
    __repr_attrs__: list = []
    __repr_max_length__ = 15

    @declared_attr
    def __tablename__(self):
        return resolve_table_name(self.__name__)

    def dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class_registry: typing.Dict = {}


@as_declarative(class_registry=class_registry)
class Base(CustomBase):
    id: typing.Any
    __name__: str
```

### base.py

Re-export for clean imports:

```python
from src.models.model_base import Base  # noqa: F401
```

---

## 5. Domain Entity Pattern (`src/domains/<entity>/`)

Every domain entity is a sub-package with three files:

### model.py — SQLAlchemy ORM model

```python
import sqlalchemy
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from src.models.base import Base


class Entity(Base):
    __tablename__ = "entities"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
        unique=True,
        server_default=sqlalchemy.text("uuid_generate_v4()"),
    )
    # ... domain-specific columns
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sqlalchemy.text("now()"),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        server_default=sqlalchemy.text("now()"),
        onupdate=sqlalchemy.text("now()"),
    )
```

### dao.py — Pydantic data access object

```python
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from uuid import UUID


class EntityDAO(BaseModel):
    model_config = ConfigDict(
        title="entities",
        extra="ignore",
        from_attributes=True,
        json_encoders={
            UUID: lambda o: str(o),
            datetime: lambda v: v.isoformat(timespec="microseconds"),
        },
    )

    id: Optional[UUID] = None
    # ... domain-specific fields
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### service.py — Static async methods for CRUD

```python
from typing import Optional
from uuid import UUID
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from src.domains.<entity>.dao import EntityDAO
from src.domains.<entity>.model import Entity


class EntityService:
    @staticmethod
    async def create(
        entity_dao: EntityDAO,
        db_session: AsyncSession,
        autocommit: bool = True,
    ) -> Optional[Entity]:
        dump = entity_dao.model_dump(mode="python", exclude_none=True, exclude={"id"})
        entity = Entity(**dump)
        db_session.add(entity)
        if autocommit:
            await db_session.commit()
        else:
            await db_session.flush()
        return entity

    @staticmethod
    async def get(
        entity_id: UUID,
        db_session: AsyncSession,
    ) -> Optional[Entity]:
        stmt = sa.select(Entity).where(Entity.id == entity_id)
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()
```

---

## 6. Pytest Framework (`tests/`)

### conftest.py

Transactional test fixture that rolls back after every test. Uses SQLAlchemy nested transactions with savepoint listeners.

```python
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from config.cfg import cfg


@pytest_asyncio.fixture(scope="function")
async def async_db_session():
    async_engine = create_async_engine(
        cfg("DB_URL_ASYNC"),
        pool_size=10,
        echo=False,
        max_overflow=10,
        pool_use_lifo=True,
        pool_recycle=100,
    )
    TestingAsyncSessionLocal = sessionmaker(
        async_engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        class_=AsyncSession,
    )  # type: ignore

    async with async_engine.connect() as connection:
        trans = await connection.begin()
        async_session = TestingAsyncSessionLocal(bind=connection)
        nested = await connection.begin_nested()

        @event.listens_for(async_session.sync_session, "after_transaction_end")
        def end_savepoint(session, transaction):
            nonlocal nested
            if connection.closed:
                return
            if not connection.in_nested_transaction():
                nested = connection.sync_connection.begin_nested()

        yield async_session
        await trans.rollback()
        await async_session.close()
        await connection.close()
```

### Test file convention

- Mirror the `src/` directory structure under `tests/`
- Every test directory has an `__init__.py`
- Test files are named `test_<module>.py`
- All DB tests accept the `async_db_session` fixture

```python
import pytest

@pytest.mark.asyncio
async def test_entity_create(async_db_session):
    # Arrange, Act, Assert using async_db_session
    pass
```

---

## 7. Docker Setup (`docker/`)

### docker-compose.dev.yml

Development services — Postgres (with pgvector), Redis, and optionally Minio.

```yaml
version: "3"
services:
  postgres:
    image: <project>_postgres
    build:
      context: .
      dockerfile: postgres/Dockerfile
    env_file:
      - ./../environments/development.env
    expose:
      - 5437
    ports:
      - "5437:5432"
    volumes:
      - ./../data/postgres/db_data/:/var/lib/postgresql/data/
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 5s
      retries: 3

  redis:
    image: redis:7.4
    env_file:
      - ./../environments/development.env
    volumes:
      - ./../data/redis/dump.rdb/:/var/lib/redis/dump.rdb/
    expose:
      - 6379
    ports:
      - "6379:6379"
```

### postgres/Dockerfile

Based on `pgvector/pgvector:pg16` with development tools installed.

```dockerfile
ARG PG_MAJOR=16
FROM pgvector/pgvector:pg${PG_MAJOR}

RUN apt-get update -y && apt-get install -y \
    curl \
    build-essential \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    procps \
    git \
    telnet \
    net-tools

ADD ./postgres/init.sh /docker-entrypoint-initdb.d/init.sh
RUN chown postgres:postgres /docker-entrypoint-initdb.d/init.sh

EXPOSE 5432
```

### postgres/init.sh

Creates the application user, database, and enables required extensions (`uuid-ossp`, `vector`).

```bash
#!/bin/bash
set -e

until psql -c '\l'; do
  echo "Postgres is unavailable - sleeping"
  sleep 1
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER $<PREFIX>_APP_DB_USER WITH PASSWORD '$<PREFIX>_APP_DB_PASS';
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE $<PREFIX>_APP_DB_NAME;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    GRANT ALL PRIVILEGES ON SCHEMA public TO $<PREFIX>_APP_DB_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    GRANT CREATE ON DATABASE $<PREFIX>_APP_DB_NAME TO $<PREFIX>_APP_DB_USER;
    ALTER DATABASE $<PREFIX>_APP_DB_NAME OWNER TO $<PREFIX>_APP_DB_USER;
    GRANT USAGE ON SCHEMA public TO $<PREFIX>_APP_DB_USER;
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO $<PREFIX>_APP_DB_USER;
    GRANT USAGE, CREATE ON SCHEMA public TO $<PREFIX>_APP_DB_USER;
    GRANT CONNECT ON DATABASE $<PREFIX>_APP_DB_NAME TO $<PREFIX>_APP_DB_USER;
    GRANT ALL PRIVILEGES ON DATABASE $<PREFIX>_APP_DB_NAME TO $<PREFIX>_APP_DB_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    \c $<PREFIX>_APP_DB_NAME
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "vector";
EOSQL
```

---

## 8. Alembic Migrations (`alembic.ini` + `db/`)

### alembic.ini

Standard config with `script_location = %(here)s/db` and `prepend_sys_path = .` so project imports resolve correctly.

The `sqlalchemy.url` in alembic.ini is a placeholder — `db/env.py` overrides it at runtime from the environment variable.

### db/env.py

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from src.models.base import Base

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", os.environ.get("<PREFIX>_DB_URL"))
```

### First migration

Always create a `create_extensions` migration as the first revision:

```python
def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
```

---

## 9. Environment Files (`environments/`)

### local.env

```env
PYTHONPATH=<absolute-path-to-project>
<PREFIX>_ENV=test
<PREFIX>_ROOT_DIR=<absolute-path-to-project>
<PREFIX>_APP_DIR=<absolute-path-to-project>
<PREFIX>_DOMAIN=localhost:7777
<PREFIX>_DB_URL_ASYNC=postgresql+asyncpg://<user>:<pass>@localhost:5437/<db_name>
<PREFIX>_DB_URL=postgresql+psycopg2://<user>:<pass>@localhost:5437/<db_name>
<PREFIX>_REDIS_URL=redis://localhost:6379/0
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
<PREFIX>_APP_DB_USER=<user>
<PREFIX>_APP_DB_PASS=<pass>
<PREFIX>_APP_DB_NAME=<db_name>
```

### test.env

Same structure as local.env but with test-specific database name and any additional test service config (DBOS, Minio, etc.).

---

## 10. Scripts (`scripts/local_tests/`)

### template_setup.sql

Templated SQL for creating the test database. Uses `envsubst` placeholders.

```sql
CREATE DATABASE ${<PREFIX>_APP_DB_NAME};
GRANT ALL PRIVILEGES ON DATABASE ${<PREFIX>_APP_DB_NAME} TO ${<PREFIX>_APP_DB_USER};
GRANT CREATE ON DATABASE ${<PREFIX>_APP_DB_NAME} TO ${<PREFIX>_APP_DB_USER};
ALTER DATABASE ${<PREFIX>_APP_DB_NAME} OWNER TO ${<PREFIX>_APP_DB_USER};
\c ${<PREFIX>_APP_DB_NAME}
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

### setup.sh

```bash
#!/bin/bash
echo "Setting up the setup.sql file for database configurations"
export PGPASSWORD=$POSTGRES_PASSWORD
envsubst < ./scripts/local_tests/template_setup.sql > ./scripts/local_tests/setup.sql
psql -U $POSTGRES_USER -h localhost -p 5437 -d $POSTGRES_DB -f ./scripts/local_tests/setup.sql
```

---

## 11. Makefile & Launch Scripts

### launch_dev.sh

```bash
#!/bin/bash
set -e

echo "Starting dev environment via docker-compose..."

docker compose --env-file environments/development.env -f docker/docker-compose.dev.yml up --build
```

### Makefile

```makefile
.PHONY: dev-environment

dev-environment:
	bash launch_dev.sh
```

Every new independently launchable process needs:
1. A `launch_<name>.sh` script in the project root
2. A corresponding Makefile target
3. Registration in `.PHONY`

---

## 12. pyproject.toml

Uses Poetry as the build backend. Key dependencies for the standard stack:

```toml
[project]
name = "<project>"
version = "0.1.0"
description = ""
authors = [{name = "...", email = "..."}]
requires-python = ">=3.11,<4.0"
dependencies = [
    "asyncpg (>=0.31.0,<0.32.0)",
    "psycopg2 (>=2.9.11,<3.0.0)",
    "fastapi (>=0.128.0,<0.129.0)",
    "pydantic (>=2.12.5,<3.0.0)",
    "alembic (>=1.18.1,<2.0.0)",
    "python-json-logger (>=4.0.0,<5.0.0)",
    "uvicorn (>=0.41.0,<0.42.0)",
    "httpx (>=0.28.1,<0.29.0)",
    "tenacity (>=9.1.4,<10.0.0)",
    "pgvector (>=0.4.0,<1.0.0)",
]

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"

[dependency-groups]
dev = [
    "pytest (>=9.0.2,<10.0.0)",
    "pytest-asyncio (>=1.3.0,<2.0.0)",
    "black (>=26.1.0,<27.0.0)",
    "autoflake (>=2.3.1,<3.0.0)",
]
```

Add domain-specific dependencies (LangChain, DBOS, scrapy, etc.) only when needed.

---

## 13. CLAUDE.md

```markdown
When asked to write, modify, or reason about code in this repository, read `AGENTS.md` first. Skip this for general questions about syntax, language semantics, or topics that don't require project context.
```

---

## 14. Frontend App Variant (HTMX + Jinja2 + FastAPI)

If the project is a **server-rendered frontend application** (admin portal, dashboard, etc.) rather than a backend API service, apply these modifications to the scaffold above. For full conventions and code patterns, see [`skills/languages/python/create-frontend-htmx-jinja2-fastapi-app/SKILL.md`](../create-frontend-htmx-jinja2-fastapi-app/SKILL.md).

### Additional Directory Structure

```
<project>/
├── src/
│   ├── <app_name>_app.py           # App initialization (replaces simple main.py setup)
│   ├── clients/
│   │   └── api_client_service.py   # HTTP client for backend API (aiohttp)
│   ├── connectors/
│   │   ├── async_redis.py          # Async Redis (sessions/cache)
│   │   └── sync_redis.py           # Sync Redis (Celery)
│   ├── context/
│   │   └── request_context.py      # Request ID, session ID context vars
│   ├── errors/
│   │   └── base.py                 # ApiException
│   ├── middlewares/
│   │   ├── user_info_middleware.py  # Auth check via Redis session
│   │   ├── request_ctx.py          # Request/span ID propagation
│   │   ├── logging.py              # Request/response logging
│   │   └── transport_security_headers.py
│   ├── public/assets/              # Static files (CSS, JS, vendor libs)
│   ├── routers/
│   │   ├── base_controller.py      # Shared: Jinja2Templates, filters, pagination
│   │   └── <entity>_controller.py  # One controller per domain
│   └── templates/
│       ├── layouts/                # base_layout.html, _header, _footer, _navbar
│       ├── shared/                 # pagination.html, form_errors.html
│       ├── errors/                 # 401, 404, api_error templates
│       └── <entity>/              # list.html, _list.html, _new.html, _detail.html
└── utils/
    └── api/
        ├── auth.py                 # HMAC request signing
        └── authorization.py        # Permission helpers
```

### Key Differences from Backend API Scaffold

| Aspect | Backend API | Frontend App |
| --- | --- | --- |
| **Database** | Direct SQLAlchemy access | No DB — calls backend API via `ApiClientService` |
| **Alembic** | Yes (migrations) | No |
| **Domain service** | SQLAlchemy queries | `ApiClientService.get/post/put/delete` |
| **Response format** | JSON (`JSONResponse`) | HTML (`templates.TemplateResponse`) |
| **Forms** | Pydantic models | WTForms + starlette-wtf (CSRF) |
| **Static files** | None | `src/public/assets/` mounted at `/` |
| **Session** | JWT/API keys | Cookie + Redis (`SessionMiddleware`) |
| **HTMX** | N/A | Dual routes (full page + partial) for every view |

### Additional Dependencies

```toml
# Add these to pyproject.toml for frontend apps
"jinja2",
"starlette-wtf",
"wtforms",
"email-validator",
"aiohttp",
"aiohttp-client-cache",
"redis",
"aiofiles",
```

### Frontend Checklist (in addition to base checklist)

- [ ] `src/public/assets/` contains Bootstrap 5 CSS/JS and HTMX
- [ ] `base_layout.html` renders with navigation, HTMX script, and Bootstrap
- [ ] At least one domain has the dual-route pattern (full page + HTMX partial)
- [ ] CSRF protection is active (`CSRFProtectMiddleware` + `csrf_token()` in forms)
- [ ] Static files are mounted as the **last** route in `initialize_app()`
- [ ] Redis is running and session middleware is configured
- [ ] `UserInfoMiddleware` correctly gates authenticated routes

---

## 15. Checklist

When scaffolding is complete, verify:

- [ ] `poetry install` succeeds
- [ ] `docker compose --env-file environments/development.env -f docker/docker-compose.dev.yml up --build` starts Postgres and Redis
- [ ] Test database can be created via `scripts/local_tests/setup.sh`
- [ ] `alembic upgrade head` runs the extensions migration
- [ ] `pytest` discovers and runs against the test database (using `conftest.py` fixtures)
- [ ] `PYTHONPATH` is set to the project root in env files so `config.cfg` and `src.*` imports resolve
- [ ] All `__init__.py` files are in place for proper package resolution
