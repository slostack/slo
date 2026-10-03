---
name: build-schedulers-tasks-with-dbos
description: 'Python: DBOS init, DB pool config, and scheduled tasks.'
when_to_use: For Python projects only. Use when adding a scheduled (cron-style) background task on DBOS.
group: languages
kind: skill
source_prompt: build-schedulers-tasks-with-dbos.md
---

# Building Schedulers And Task Processors With DBOS

## Skill summary

- **Name:** `build-schedulers-tasks-with-dbos`
- **Description:** DBOS init, DB pool config, and scheduled tasks.
- **When to use:** Use when adding a scheduled (cron-style) background task on DBOS.
- **Group:** `languages`
- **Kind:** `skill`
- **Source prompt:** `build-schedulers-tasks-with-dbos.md`

## Examples

- The user asks: "Add or revise the schedulers tasks with dbos for this feature."
- You want the canonical build pattern before touching schedulers tasks with dbos.

## Guidance

**Applicability:** Python only; framework-specific sections apply only when that stack is in the project. Load `skills/languages/python/python-conventions/SKILL.md` and `skills/engineering/engineering-testing/SKILL.md` for shared obligations and test-category selection.

> **Companion rule:** every new DBOS worker MUST also ship with paired
> VSCode launch configurations in both `orders-platform/.vscode/launch.json`
> and `orders-platform/orders_service/.vscode/launch.json`. See
> [`skills/languages/python/build-vscode-launch-configurations/SKILL.md`](../build-vscode-launch-configurations/SKILL.md).
> The launcher script under `orders_service/scripts/launch_*.sh` and the
> VSCode entries are paired artefacts — operators use the script in
> production, developers use the VSCode entries locally.

## Conventions

We usually setup our workers in a folder under `src/tasks`. The primary file that contains most of the initialization logic is

1. `worker.py` under `src/tasks/worker.py`
2. Each worker file (e.g. `document_persist_worker.py`, `message_persist_worker.py`) defines its own Queue inline

The `worker.py` initialize our DBOS application and contains a simple class described below

```python
import uuid
from typing import Optional, Dict, Any
from config.cfg import cfg
from dbos import DBOSConfig
from sqlalchemy import create_engine, Engine
from sqlalchemy.pool import QueuePool

DBOS_SYSTEM_DATABASE_URL: str = cfg("DBOS_SYSTEM_DATABASE_URL") # type: ignore

DB_POOL_ARGS: Dict[str, Any] = {
    "pool_size": 5,
    "echo": False,
    "echo_pool": True,
    "max_overflow": 0,
    "pool_use_lifo": False,
    "pool_recycle": 300,
    "pool_pre_ping": False,
    "pool_timeout": 60,
}


class WorkerInitializer:
    def __init__(
        self,
        app_name: str = cfg("DBOS_APP_NAME"),  # type: ignore
        worker_executor_id: Optional[str] = None,
        conductor_key: Optional[
            str
        ] = cfg("DBOS_CONDUCTOR_KEY"),  # type: ignore
    ):
        self.dbos_system_database_url: str = DBOS_SYSTEM_DATABASE_URL
        self.worker_executor_id: str = worker_executor_id or str(uuid.uuid4())
        self.config: DBOSConfig = {
            "name": app_name or "testapp",
            "system_database_url": DBOS_SYSTEM_DATABASE_URL,
            "executor_id": self.worker_executor_id,
            "conductor_key": conductor_key,
            "sys_db_pool_size": 3,
            "run_admin_server": True,
            "db_engine_kwargs": DB_POOL_ARGS,
            "application_version": cfg("DBOS_APP_VERSION")
        }
```

### Queue Isolation — CRITICAL

**Each worker MUST define its own Queue inline. Never share Queue definitions across worker files via a common module (e.g. `dbos_queues.py`).**

When multiple `Queue()` objects are instantiated in a shared module, importing ANY queue causes Python to instantiate ALL queues at module load time. Each queue registers with the shared DBOS system database, and the worker process then attempts to consume tasks from ALL registered queues — but only has its own workflow function registered. This causes:

```
DBOS Error 4: <other_workflow> is not a registered workflow function
```

The `src/tasks/dbos_queues.py` file exists only as a commented reference listing all queue definitions and their locations. It contains no executable code.

Here is a sample task worker implemented as a job queue processor. Note that the Queue is defined **inline** in the worker file:

```python
# first_task_worker.py

from typing import Optional
import asyncio
from uuid import uuid4
from random import randint
import logging
from src.worker import WorkerInitializer
from dbos import Queue, DBOSClient, DBOS, EnqueueOptions, WorkflowHandleAsync, Debouncer, SetEnqueueOptions
from src.worker import DBOS_SYSTEM_DATABASE_URL
from dbos import DBOS as _DBOS
from contextvars import ContextVar

# Define queues INLINE — never import from a shared module
master_queue: Queue = Queue(
    name="master_queue",
    concurrency=50,
)

partitioning_queue: Queue = Queue(
    name="partitioning_queue",
    concurrency=1,
    priority_enabled=False,
    worker_concurrency=1,
    partition_queue=True,
)

runner_queue: Queue = Queue(
    name="runner_queue",
    priority_enabled=False,
    worker_concurrency=1,
    partition_queue=False,
)

default_logger: logging.Logger = logging.getLogger("dbos_first_task_worker")
default_logger.setLevel(logging.INFO)
default_logger.addHandler(logging.StreamHandler())


executor_id: ContextVar[str] = ContextVar("executor_id", default=str(uuid4()))
worker: WorkerInitializer = WorkerInitializer(
    worker_executor_id=executor_id.get() or str(uuid4()), app_name="testapp1"
)
dbos: _DBOS = _DBOS(config=worker.config)


@_DBOS.workflow(name="runner_queue_handler")
async def runner_queue_handler(
    task_index: str, delay: int = 0, vendor_id: int = None
) -> str:
    try:
        task_id: str = task_index        
        default_logger.info(
            f"[{executor_id.get()}] [Task-ID]: {task_id} executed"
        )
        return f"{task_id} completed"
    except Exception as e:
        default_logger.error(
            f"[{executor_id.get()}] Error in first_task_queue_instant_handler: {e}"
        )
        raise e


@_DBOS.workflow(name="partitioning_workflow_handler")
async def partitioning_workflow_handler(
    task_index: str,
    vendor_id: int,
    queue_partition_key: str ,
    deduplication_id: str,
) -> str:
    try:
        task_id: str = task_index
        default_logger.info(
            f"Task-Index: {task_id} partitioning"
        )
        # Invoke a workflow directly
        handle = await runner_queue.enqueue_async(
            runner_queue_handler,
            task_index=task_index,
            vendor_id=vendor_id,
        )
        return await handle.get_result()
    except Exception as e:
        default_logger.error(
            f"[{executor_id.get()}] Error in first_task_queue_instant_handler: {e}"
        )
        raise e


@_DBOS.workflow(name="master_queue_handler")
async def master_queue_handler(
    task_index: str,
    vendor_id: int,
    delay: Optional[int] = None,    
    deduplication_id: Optional[str] = None,
    queue_partition_key: Optional[str] = None,
) -> str:
    try:
        if delay is not None and float(delay) > float(0.0):
            default_logger.info(
                f"Task-Index: {task_index} sleeping"
            )
            await DBOS.sleep_async(seconds=float(delay))
            default_logger.info(
                f"Task-Index: {task_index} Woke up"
            )

        with SetEnqueueOptions(queue_partition_key=queue_partition_key):          
            handle = await partitioning_queue.enqueue_async(
                partitioning_workflow_handler,
                task_index=task_index,
                vendor_id=vendor_id,
                queue_partition_key=queue_partition_key,
                deduplication_id=deduplication_id,
            )
            result = await handle.get_result()
            default_logger.info(
                f"Task-Index: {task_index} finished."
            )       
        return result
    except Exception as e:
        default_logger.error(
            f"[{executor_id.get()}] Error in first_task_queue_handler: {e}"
        )
        raise e


async def launch():
    try:
        DBOS.logger.info(f"[{executor_id.get()}] Worker starting...")
        if not dbos._launched:
            dbos.launch()

        while True:
            await asyncio.sleep(0.005)
    except KeyboardInterrupt:
        default_logger.info(f"[{executor_id.get()}] Worker shutting down.")


if __name__ == "__main__":
    from multiprocessing import Process
    from typing import List
    import os
    from asyncio import AbstractEventLoop

    async def main():
        """
        Launch the worker with the event loop.
        """
        await launch()

    asyncio.run(main())
    # launch_workers()
```

### Important Patterns

1. **Each worker defines its own queues inline.** Never import queues from a shared module — this causes cross-registration with the DBOS system database and `DBOS Error 4` failures. See "Queue Isolation" above.

2. Use pattern of an unbounded queue with a high queue `concurrency` value and a standarded partitioned and runner_queue with concurrency threshold to model scenarios that need a delay without blocking the workflows.

3. This pattern may not be always needed.

4. The examples are simplistic but in actual application the workflow or step should invoke an application service and never include application logic directly.

5. Scheduled workflows are similar and can be found on the DBOS documentation.

#### Enqueuing Tasks

In most cases a separate process or part of the application enqueues a task in a tradition job queue paradigm. We expect to implement such a solution as below

```python
# enqueuer.py
#
# Note: Enqueuers use string-based queue_name in EnqueueOptions.
# They do NOT need to import Queue objects — only workers do.
import asyncio
import logging
from uuid import uuid4
from src.tasks.worker import (
    DBOS_SYSTEM_DATABASE_URL,
)
from itertools import cycle
from dbos import DBOSClient, WorkflowHandleAsync, DBOS
from dbos import DBOSClient, EnqueueOptions, Debouncer
from datetime import datetime
from random import randint

from sqlalchemy import create_engine, Engine, QueuePool
default_logger: logging.Logger = logging.getLogger("dbos")
default_logger.setLevel(logging.INFO)
default_logger.addHandler(logging.StreamHandler())


engine: Engine = create_engine(
    DBOS_SYSTEM_DATABASE_URL,
    pool_size=2,
    poolclass=QueuePool,
    max_overflow=0,
    pool_timeout=30,
    pool_recycle=300,
    pool_pre_ping=False,
    pool_use_lifo=False,
    echo=False,
    echo_pool=True,
)

client: DBOSClient = DBOSClient(system_database_url=DBOS_SYSTEM_DATABASE_URL, system_database_engine=engine)

async def task_trigger() -> None:
    # create an infinite loop
    vendor_id_cycler: cycle[int] = cycle([1])
    index: int = randint(1000, 5000000)
    for i in range(1000):
        index += 1
        vendor_id: int = next(vendor_id_cycler)
        await enqueue_task(task_index=index, vendor_id=vendor_id)
        await asyncio.sleep(0.7)


async def enqueue_task(task_index: int, vendor_id: int) -> None:
    try:
        queue_name: str = (
            "master_queue"  
        )
        workflow_name: str = (
            "master_queue_handler"
        )
        deduplication_id: str = str(int(datetime.now().timestamp()))
        delay: int = 20
        options: EnqueueOptions = {
            "queue_name": queue_name,  # must match Queue name in worker_app.py
            "workflow_name": workflow_name,  # must match the workflow function name
        }
        options["deduplication_id"] = deduplication_id
        options["queue_partition_key"] = str(vendor_id)

        enqueue_task: WorkflowHandleAsync = await client.enqueue_async(
            options,
            task_index=task_index,
            vendor_id=vendor_id,
            delay=delay,
            deduplication_id=deduplication_id,
            queue_partition_key=str(vendor_id),
        )
        default_logger.info(
            f"[{queue_name}]: {task_index}: Enqueued"
        )
    except Exception as e:
        default_logger.error(f"Error duplicate task: {e}")
        return


if __name__ == "__main__":
    import asyncio

    asyncio.run(task_trigger())
```

Note the use of EnqueueOptions and explicitly specifying of the queue_name and workflow name. 

### Scheduled Workflows

Scheduled workflows are created using the following pattern

```python
@DBOS.scheduled('* * * * *') # crontab syntax to run once every minute
@DBOS.workflow()
def example_scheduled_workflow(scheduled_time: datetime, actual_time: datetime):
    DBOS.logger.info("I am a workflow scheduled to run once a minute. ")
```

For more examples and details refer to the DBOS Python Tutorials pages

1. https://docs.dbos.dev/python/programming-guide
2. https://docs.dbos.dev/python/tutorials/workflow-tutorial
3. https://docs.dbos.dev/python/tutorials/step-tutorial
4. https://docs.dbos.dev/python/tutorials/queue-tutorial
5. https://docs.dbos.dev/python/tutorials/workflow-management
6. https://docs.dbos.dev/python/tutorials/scheduled-workflows
7. https://docs.dbos.dev/python/tutorials/database-connection
