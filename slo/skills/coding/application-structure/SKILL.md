---
name: application-structure
description: Standard folder layout, env config, DB setup, app architecture.
when_to_use: Read when laying out a new module or service.
group: coding
kind: skill
source_prompt: application-structure.md
---

# Application Structure

## Skill summary

- **Name:** `application-structure`
- **Description:** Standard folder layout, env config, DB setup, app architecture.
- **When to use:** Read when laying out a new module or service.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `application-structure.md`

## Examples

- The user asks for help with: Standard folder layout, env config, DB setup, app architecture.
- Read when laying out a new module or service.

## Guidance

> **Companion rule for new long-lived services:** every new FastAPI
> app, A2A agent, or DBOS worker shipped under `orders_service/` MUST land
> with paired VSCode launch configurations in both
> `orders-platform/.vscode/launch.json` and
> `orders-platform/orders_service/.vscode/launch.json`. See
> [`skills/coding/build-vscode-launch-configurations/SKILL.md`](../build-vscode-launch-configurations/SKILL.md).

`orders_service` is a project within the orders-platform monorepo. `orders_service` is the core backend that accepts customer orders in various formats and persists them into storage. It also enriches these orders (validation, line-item resolution, downstream fan-out) using the appropriate processing pipeline.

## Service Namespace Prefix (MANDATORY)

Every service in the orders-platform monorepo serves its routes under a short
**service-name-derived URL namespace prefix**, with `/api/v1` preserved
underneath. The namespace identifies the *service*; `/api/v1`
identifies the *API revision*.

| Service                | Namespace | Full prefix      |
|------------------------|-----------|------------------|
| `orders_service` API      | `/o`      | `/o/api/v1`      |
| `orders_service` A2A agent| `/oa`     | `/oa/api/v1`     |
| `admin_ui`                | `/au`     | `/au/api/v1`     |
| `payments_service`        | `/p`      | `/p/api/v1`      |

Every `app.include_router(...)` call must use the form
`prefix="<service-namespace>/api/v1[/<group>]"`. A bare `/api/v1`
prefix is a violation. The authoritative section with rationale,
examples, and the Traefik routing implication is in
[`skills/coding/build-routers/SKILL.md`](../build-routers/SKILL.md) → **Service Namespace Prefix
(MANDATORY)**.

When you introduce a new long-lived service, pick its namespace at the
same time you pick its directory name, add the row to that registry,
and add the corresponding KB entry under
`<knowledge-base>/orders-platform-conventions/service-namespace-prefixes.md`.

## orders_service Application Schema

`orders_service` is a FastAPI application running a PostgreSQL database and asyncio Python 3.14.2. It uses DBOS for task processing and workflow orchestration. 



## Application Structure Documentation  
  
This document describes the standardized folder structure and coding patterns used across the `orders_service` and sibling services for backend development.  
  
### 1. Config Folder  
  
#### cfg.py   
The configuration module follows a consistent pattern with environment-based loading:  
  
```python  
# Environment detection  
env = os.environ.get("ORDERS_ENV", "development")  # per-service prefix, e.g. PAYMENTS_ENV for payments_service  
  
# Helper functions  
def is_dev():  
    return env == "development"  
  
def is_test():  
    return env == "test"  
  
def is_staging():  
    return env == "staging"  
  
# Configuration dictionary  
__cfg__: dict[str, str | None] = {  
    "ENV": env,  
    "APP_NAME": APP_NAME,  
    # ... other config keys  
}  
  
# Lookup function  
def cfg(key: str):  
    return __cfg__.get(key) or os.getenv(key)  
```

  
#### Key Configuration Keys  
- Database URLs: `DB_URL`, `DB_URL_ASYNC`  
- Redis: `REDIS_URL`  
- JWT/Session secrets  
- Azure services: OpenAI, Speech, Blob Storage  
- Email service configuration  
  
### 2. Connectors  
  
#### Async Postgres Integration  
Uses SQLAlchemy with async support:  
  
```python  
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction  
from connectors.async_postgres import get_async_session  
```

 
  
### Async Redis Integration  
Redis client for caching and Celery queue:  
  
```python  
from connectors.async_redis import AsyncRedisClient  
from redis import Redis  
```

  
### 3. Docker Configuration  
  
#### Docker Compose Structure  
Multiple environment variants:  
- `docker-compose.dev.yml` - Development environment  
- `docker-compose-stack.yml` - Production Swarm deployment  
- `docker-compose-staging-stack.env.yml` - Staging environment  
  
#### Service Pattern  
Each service follows consistent structure:  
```yaml  
service_name:  
  build:  
    context: ./..  
    dockerfile: docker/Dockerfile  
  env_file: ./../../files/data/stack.env  
  command: ["./launch.sh"]  # or "./launch_worker.sh"  
  networks:  
    - dokploy-network  
```

  
### 4. Middleware  
  
#### Middleware Pipeline  
Three core middleware in execution order:  
  
1. **CORSMiddleware** - Cross-origin handling  
2. **DbMiddleware** - Database session management  
3. **RequestCtxMiddleware** - Request context and ID generation  
  
```python  
def _initialize_middleware(app: FastAPI) -> FastAPI:  
    app.add_middleware(CORSMiddleware, ...)  
    app.add_middleware(DbMiddleware)  
    app.add_middleware(RequestCtxMiddleware)  
    return app  
```

  
### 5. src/domains Pattern  
  
#### Three-File Structure per Domain  
Each domain entity follows strict pattern:  
  
##### model.py - SQLAlchemy Model  
```python  
from sqlalchemy import Column, Integer, String, Text, TIMESTAMP  
from src.models.model import Base  
  
class DomainEntity(Base):  
    __tablename__ = "domain_entities"  
      
    id = Column(Integer, primary_key=True)  
    # ... other columns  
```  
  
##### dao.py - Data Access Object  
```python  
from pydantic import BaseModel  
  
class DomainEntityDAO(BaseModel):  
    id: int  
    # ... other fields  
      
    model_config = ConfigDict(  
        from_attributes=True,  
        arbitrary_types_allowed=True  
    )  
```  
  
#### service.py - Business Logic  
```python  
class DomainEntityService:  
    @staticmethod  
    async def get(id: int, db_session: AsyncSession) -> DomainEntity:  
        # Database operations  
          
    @staticmethod  
    async def create(data: DomainEntityDAO, db_session: AsyncSession) -> DomainEntity:  
        # Creation logic  
```  
  
### 6. src/models - SQLAlchemy Integration  
  
#### Model Base Configuration  

```python  
from src.domains.user.model import User  
from src.domains.document.model import Document  
from src.domains.summary.model import Summary  
# ... import all domain models  
```

  
#### Async Session Pattern  
All database operations use async sessions:  
```python  
async with get_async_session() as db_session:  
    # Database operations  
```  
  
### 7. src/services - Application Services  
  
#### Consistent invoke() Pattern  
All application services follow this structure:  
  
```python  
class AppService:  
    def __init__(self, ...):  
        # Dependency injection  
          
    async def invoke(self) -> ReturnType:  
        # Main orchestration logic  
        await self.step1()  
        await self.step2()  
        return self.result  
```

  
### 8. Main Application Files  
  
#### web_app.py Structure  
```python  
def initialize_web_app(app: FastAPI) -> FastAPI:  
    app = _initialize_routers(app=app)  
    app = _initialize_middleware(app=app)  
    app = _initialize_exception_handlers(app=app)  
    return app  
```

  
### Exception Handling Pattern  
Standardized error responses with unique IDs:  
```python  
@app.exception_handler(ApiException)  
async def handle_api_exceptions(request: Request, exc: ApiException):  
    error_id = str(uuid4())  
    request_id = str(request.state.ctx.request_id)  
    # Log and return standardized response  
```

  
### 9. src/workers - Celery Workers  
  
#### Worker Structure  
```python  
# worker.py - Celery configuration  
celery = Celery(  
    __name__,  
    broker=cfg("REDIS_URL"),  
    include=["workers.task1", "workers.task2"]  
)  
  
# task_worker.py - Individual tasks  
@celery.task(name="task_worker", bind=True)  
def task_worker(task_type: Task, param1: str, param2: UUID):  
    loop.run_until_complete(task_worker_async(...))  
```

  
#### Async Worker Pattern  

```python  
async def task_worker_async(task_type: Task, param: UUID):  
    async with get_async_sessionmaker() as async_session:  
        # Business logic  
        return result  
```  
  
### 10. Scripts Folder  
  
Contains SQL scripts and one-time execution scripts for database setup and maintenance.  
  
### 11. src/utils  
  
Generic utility functions used across the application:  
- Date/time helpers  
- File operations  
- Validation helpers  
- Common transformations  
  
### 12. src/agents - Langchain Pattern  
  
#### Agent Structure  
```python  
class AgentName:  
    def __init__(self, model_name: str = cfg("MODEL_NAME")):  
        self.llm = create_agent(  
            model_name=model_name,  
            temperature=0.1,  
            max_retries=3  
        )  
      
    async def invoke(self, input_data) -> OutputModel:  
        # Prepare messages  
        # Call LLM  
        # Validate and return response  
```

 
  
#### Base Agent Factory  
```python  
def create_agent(  
    model_name: str,  
    temperature: float,  
    streaming: Optional[bool] = True,  
    max_retries: Optional[int] = 3,  
    max_tokens: Optional[int] = 1000  
) -> AzureChatOpenAI | ChatOpenAI:  
```  
  
### 13. Templates and Layouts  
  
#### Template Structure  
- `src/templates/` - Jinja2 templates  
- `src/templates/layouts/` - Base layout templates  
- Methods added to `base_controller.py` for view rendering  
  
### Controller Pattern  
```python  
# In base_controller.py  
def render_template(template_name: str, context: dict):  
    # Template rendering logic  
      
# Usage in controllers  
return render_template("page.html", {"data": data})  
```  
  
### Conventions and Patterns  
  
#### Async/Await Usage  
All I/O operations use async/await pattern:  
- Database operations  
- External API calls  
- File operations  
- Network requests  
  
#### Error Handling  
- Custom exception classes in `exceptions.py`  
- Standardized error response format  
- Unique error and request IDs for tracing  
  
#### Dependency Injection  
Services accept dependencies via constructor parameters with default values for testability.  
  
#### Environment Configuration  
- Centralized configuration through `cfg.py`  
- Environment detection helpers  
  
#### Database Transactions  
- Use of `AsyncSessionTransaction` for complex operations  
- Automatic commit/rollback via middleware
