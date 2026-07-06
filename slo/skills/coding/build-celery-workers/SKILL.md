---
name: build-celery-workers
description: Creating Celery background tasks — naming, registration, routes, beat.
when_to_use: Use when adding async background work via Celery.
group: coding
kind: skill
source_prompt: build-celery-workers.md
---

# Building Celery Workers

## Skill summary

- **Name:** `build-celery-workers`
- **Description:** Creating Celery background tasks — naming, registration, routes, beat.
- **When to use:** Use when adding async background work via Celery.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-celery-workers.md`

## Examples

- The user asks: "Add or revise the celery workers for this feature."
- You want the canonical build pattern before touching celery workers.

## Guidance

## Conventions

Workers are placed under `src/tasks`. The primary file that contains the Celery app initialization, queue routing, and beat schedules is `src/tasks/worker.py`.

### Naming Conventions

1. Worker files are suffixed with `_worker.py`. For example `src/tasks/placement_file_preprocessor_worker.py`
2. The Celery task name matches the function name, which matches the file name. For example `placement_file_preprocessor_worker`
3. Each worker gets its own dedicated Redis-backed queue. The queue name follows the pattern `{task_name}_queue`. For example `placement_file_preprocessor_worker_queue`

### File Location

- Standard workers live directly under `src/tasks/`
- App-specific workers live under their app's tasks folder, e.g. `src/apps/sms_manager/tasks/`

---

## Worker Registration

Every new worker must be registered in three places within `src/tasks/worker.py`:

### 1. Include List

Add the worker's module path to the `include` list of the Celery app so it is auto-discovered:

```python
celery = Celery(
    __name__,
    broker=redis_broker_url,
    include=[
        # ... existing workers
        "src.tasks.my_new_worker",
    ],
)
```

### 2. Task Routes

Add a routing entry mapping the task name to its dedicated queue:

```python
celery.conf.task_routes = {
    # ... existing routes
    "my_new_worker": {"queue": "my_new_worker_queue"},
}
```

### 3. Beat Schedule (Optional)

If the worker should run on a recurring schedule, add it to `beat_schedule`:

```python
celery.conf.beat_schedule = {
    # ... existing schedules
    "my_new_worker": {
        "task": "my_new_worker",
        "schedule": crontab(
            minute=cfg("MY_NEW_WORKER_CRON_MINUTES"),
            hour="*",
            day_of_week="*",
            day_of_month="*",
        ),
        "options": {"queue": "my_new_worker_queue"},
    },
}
```

---

## Worker File Structure

Every worker file follows a two-function pattern: an async function that contains the business logic and a sync Celery task function that bridges async to sync.

### Complete Worker Template

```python
# src/tasks/my_new_worker.py

import asyncio
from asyncio import AbstractEventLoop
from typing import Optional

from config import logger
from config.logger import set_request_id_context, set_segment_id_context
from connectors.async_pg import get_async_db_session
from src.services.my_feature.my_app_service import MyAppService
from src.tasks.decorators import log_execution
from src.tasks.worker import celery


async def my_new_worker_async(
    task_type,
    account_id: int,
    vendor_id: int,
):
    """Async implementation containing the actual business logic.

    This function:
    1. Opens a database session
    2. Delegates to an application service
    3. Logs success or failure
    """
    metadata = {
        "account_id": account_id,
        "vendor_id": vendor_id,
    }

    try:
        async with get_async_db_session() as db_session:
            service = MyAppService(
                db_session=db_session,
                account_id=account_id,
                vendor_id=vendor_id,
            )
            await service.invoke()

        logger.info(
            message="my_new_worker completed successfully",
            metadata=metadata,
        )

    except Exception as e:
        logger.error(
            message=f"my_new_worker failed: {e}",
            metadata=metadata,
            exc_info=e,
        )
        raise


@celery.task(name="my_new_worker", bind=True)
@log_execution("my_new_worker", log_type="statistics")
def my_new_worker(
    task_type,
    account_id: int,
    vendor_id: int,
    trace_id: Optional[str] = None,
):
    """Celery task entry point. Bridges sync Celery to async business logic."""
    set_request_id_context(trace_id)
    set_segment_id_context()

    loop: AbstractEventLoop = asyncio.get_event_loop()
    loop.run_until_complete(
        my_new_worker_async(
            task_type=task_type,
            account_id=account_id,
            vendor_id=vendor_id,
        )
    )
    return True
```

---

## Key Patterns

### 1. Async/Sync Bridge

Celery tasks are synchronous. All business logic uses async/await. The bridge pattern is:

```python
@celery.task(name="worker_name", bind=True)
def worker_name(task_type, ...):
    loop: AbstractEventLoop = asyncio.get_event_loop()
    loop.run_until_complete(worker_name_async(task_type=task_type, ...))
    return True
```

- The sync function is the Celery entry point decorated with `@celery.task`
- The async function contains the actual logic with database sessions and service calls
- `bind=True` provides access to the task instance as `task_type` (first parameter)

### 2. Context Propagation

Every worker must set request and segment context for structured logging:

```python
set_request_id_context(trace_id)
set_segment_id_context()
```

The `trace_id` parameter is passed when the task is enqueued and carries through to all downstream logs.

### 3. Database Sessions

Workers run outside the web request lifecycle. Use the `get_async_db_session()` context manager:

```python
async with get_async_db_session() as db_session:
    # All database operations within this block
    await service.invoke()
```

### 4. Logging Decorator

Apply `@log_execution` after `@celery.task` to get automatic execution metrics:

```python
@celery.task(name="worker_name", bind=True)
@log_execution("worker_name", log_type="statistics")
def worker_name(...):
```

- `log_type="all"` — logs every start/end with args and kwargs
- `log_type="statistics"` — periodic summary stats (every 60 seconds): total calls, success rate, avg execution time

### 5. Delegation to Application Services

Workers should never contain business logic directly. They delegate to application services:

```python
async with get_async_db_session() as db_session:
    service = MyAppService(db_session=db_session, ...)
    await service.invoke()
```

---

## Retry Configuration

For workers that need automatic retries on transient failures:

```python
@celery.task(
    name="my_worker",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(
        TimeoutError,
        ConnectionError,
        OSError,
    ),
    retry_backoff=True,      # Exponential backoff
    retry_jitter=True,       # Random jitter to avoid thundering herd
)
@log_execution("my_worker", log_type="statistics")
def my_worker(self, ...):
    ...
```

- `max_retries` — maximum number of retry attempts
- `default_retry_delay` — base delay in seconds between retries
- `autoretry_for` — tuple of exception types that trigger automatic retry
- `retry_backoff=True` — enables exponential backoff (delay doubles each retry)
- `retry_jitter=True` — adds randomness to retry delay

---

## Enqueuing Tasks

Tasks are enqueued from application services or controllers using `.apply_async()` with keyword arguments:

### Basic Enqueue

```python
from src.tasks.my_new_worker import my_new_worker

my_new_worker.apply_async(
    kwargs={
        "account_id": account.id,
        "vendor_id": vendor_id,
        "trace_id": get_request_id_context(account.id),
    }
)
```

### Enqueue with Priority

```python
my_new_worker.apply_async(
    kwargs={
        "account_id": account.id,
        "trace_id": get_request_id_context(account.id),
        "priority": priority,
    },
    priority=priority,
)
```

### Enqueue with Delay (Countdown)

```python
my_new_worker.apply_async(
    kwargs={
        "account_id": account.id,
        "trace_id": get_request_id_context(account.id),
    },
    countdown=60,  # Run after 60 seconds
)
```

### Important Notes on Enqueuing

1. Always use `kwargs={}` (not positional args) when calling `.apply_async()`
2. Always pass `trace_id` using `get_request_id_context()` for log correlation
3. Import the worker function inside the method that enqueues (lazy import) to avoid circular imports:

```python
async def _enqueue_my_worker(self):
    from src.tasks.my_new_worker import my_new_worker

    my_new_worker.apply_async(
        kwargs={
            "account_id": self.account.id,
            "trace_id": get_request_id_context(self.account.id),
        }
    )
```

---

## Complete Example: Adding a New Worker

Here is the full checklist for adding a new Celery worker called `my_feature_worker`:

### Step 1: Create the worker file

Create `src/tasks/my_feature_worker.py` following the `Worker File Structure` template above.

### Step 2: Register in `src/tasks/worker.py`

```python
# Add to include list
celery = Celery(
    __name__,
    broker=redis_broker_url,
    include=[
        # ... existing
        "src.tasks.my_feature_worker",
    ],
)

# Add to task_routes
celery.conf.task_routes = {
    # ... existing
    "my_feature_worker": {"queue": "my_feature_worker_queue"},
}
```

### Step 3: Enqueue from your service

```python
# In your application service or controller
from config.logger import get_request_id_context


async def _enqueue_my_feature(self):
    from src.tasks.my_feature_worker import my_feature_worker

    my_feature_worker.apply_async(
        kwargs={
            "account_id": self.account.id,
            "vendor_id": self.vendor_id,
            "trace_id": get_request_id_context(self.account.id),
        }
    )
```

---

## Reference Files

| File | Purpose |
|------|---------|
| `src/tasks/worker.py` | Celery app initialization, queue routing, beat schedules |
| `src/tasks/decorators.py` | `@log_execution` decorator for task metrics |
| `src/tasks/placement_file_preprocessor_worker.py` | Example worker with retry configuration |
| `src/tasks/process_concierge_request_worker.py` | Simple worker delegating to application service |
| `connectors/async_pg.py` | `get_async_db_session()` context manager |
| `config/logger.py` | `set_request_id_context()`, `set_segment_id_context()`, `get_request_id_context()` |
| `utils/celery/signal.py` | `async_signal_handler` for Celery signals |
| `utils/celery/cron.py` | `parse_cron_string()` for beat schedules |
