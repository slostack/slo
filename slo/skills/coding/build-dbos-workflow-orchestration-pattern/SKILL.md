---
name: build-dbos-workflow-orchestration-pattern
description: Multi-step durable workflows using DBOS queues and recursive watchers.
when_to_use: Use when building long-running idempotent workflows that must survive
  restarts.
group: coding
kind: skill
source_prompt: build-dbos-workflow-orchestration-pattern.md
---

# Building DBOS Workflow Orchestration with Recursive Watchers

## Skill summary

- **Name:** `build-dbos-workflow-orchestration-pattern`
- **Description:** Multi-step durable workflows using DBOS queues and recursive watchers.
- **When to use:** Use when building long-running idempotent workflows that must survive restarts.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-dbos-workflow-orchestration-pattern.md`

## Examples

- The user asks: "Add or revise the dbos workflow orchestration pattern for this feature."
- You want the canonical build pattern before touching dbos workflow orchestration pattern.

## Guidance

## Overview

This document describes the pattern used for orchestrating multi-step workflows using DBOS queues and recursive watchers. This pattern enables composable, event-driven workflows where data flows through multiple transformation steps, with each step's output serving as input to the next.

## Core Concepts

### The Watcher Pattern

The watcher pattern implements a self-sustaining recursive chain where:
1. A **watcher** monitors one or more workflow runs for completion
2. Upon completion, it triggers **next workflow runs** based on success/failure configuration
3. For each new workflow run, it enqueues a **new watcher** to monitor those runs
4. This continues until the final workflow has no success/failure actions configured

This pattern is ideal for:
- Multi-step report generation (e.g., generate data → generate control records → merge files)
- ETL pipelines with dependencies
- Any workflow where steps depend on previous step completion

## File Structure and Naming Conventions

For each queue-based workflow system, you MUST follow this naming pattern:

```
src/tasks/dbos_workers/<workflow_domain>/
├── <queue_name>_enqueuer.py    # Client for enqueueing tasks
└── <queue_name>_worker.py       # DBOS worker that processes the queue
```

### Example: Generic Report Workflow

```
src/tasks/dbos_workers/reports/
├── generic_report_enqueuer.py           # Enqueuer
└── generic_workflow_processor_worker.py  # Worker
```

**Important**: While the worker filename doesn't strictly follow `<queue_name>_worker.py` in this case, the enqueuer MUST follow the `<queue_name>_enqueuer.py` pattern. The worker can have a more descriptive name if it processes multiple workflow types.

## Queue and Workflow Definitions

### Step 1: Define Queue and Workflow Names

Create or update `src/tasks/dbos_workers/dbos_queue.py`:

```python
class DBOSQueues:
    """DBOS queues."""

    GENERIC_REPORT_WORKFLOW_PROCESSOR_QUEUE: str = (
        "generic_report_workflow_processor_queue"
    )

class DBOSWorkflows:
    """DBOS workflows."""

    GENERIC_REPORT_WORKFLOW_PROCESSOR_WORKFLOW: str = (
        "generic_report_workflow_processor_workflow"
    )
    GENERIC_REPORT_WORKFLOW_WATCHER_PROCESSOR_WORKFLOW: str = (
        "generic_report_workflow_watcher_processor_workflow"
    )

    @staticmethod
    def build_generic_report_processor_workflow_id(workflow_run_id: str) -> str:
        """Build a unique workflow ID for deduplication and event tracking."""
        return f"{DBOSWorkflows.GENERIC_REPORT_WORKFLOW_PROCESSOR_WORKFLOW}_{workflow_run_id}"
```

## Implementation Pattern

### Step 2: Create the Enqueuer

File: `src/tasks/dbos_workers/<workflow_domain>/<queue_name>_enqueuer.py`

The enqueuer is responsible for submitting tasks to DBOS queues. It should have:
- Separate methods for enqueueing different workflow types
- Proper workflow ID generation for deduplication
- Trace ID propagation for observability

```python
from typing import Optional
from src.domains.workflow_run.dao import (
    WorkflowRunMetadataDAO,
    WorkflowRunWatcherMetadataDAO,
)
from src.tasks.dbos_workers.client import dbos_client
from dbos import EnqueueOptions, SetWorkflowID
from config import logger
from config.logger import get_request_id_context
from src.tasks.dbos_workers.dbos_queue import DBOSQueues, DBOSWorkflows


class GenericReportEnqueuer:
    """Client for enqueueing generic report workflow tasks to DBOS.

    This class provides two enqueueing methods:
    1. enqueue_workflow_run_processor - For individual workflow runs
    2. enqueue_workflow_run_watcher_processor - For watcher workflows
    """

    @staticmethod
    async def enqueue_workflow_run_processor(
        workflow_run_metadata: WorkflowRunMetadataDAO,
        trace_id: Optional[str] = None,
    ) -> bool:
        """Enqueue workflow run to DBOS for processing.

        Args:
            workflow_run_metadata: The workflow run metadata to process
            trace_id: Optional trace ID for request tracing

        Returns:
            True if successfully enqueued, False otherwise
        """
        queue_name: str = DBOSQueues.GENERIC_REPORT_WORKFLOW_PROCESSOR_QUEUE
        workflow_name: str = DBOSWorkflows.GENERIC_REPORT_WORKFLOW_PROCESSOR_WORKFLOW
        partition_key: str = workflow_run_metadata.partition_key
        dbos_workflow_id: str = (
            DBOSWorkflows.build_generic_report_processor_workflow_id(
                str(workflow_run_metadata.workflow_run_id),
            )
        )

        if trace_id is None:
            trace_id = get_request_id_context(workflow_run_metadata.workflow_run_id)

        enqueue_options: EnqueueOptions = EnqueueOptions(
            queue_name=queue_name,
            workflow_name=workflow_name,
            queue_partition_key=partition_key,
            deduplication_id=dbos_workflow_id,
            workflow_id=dbos_workflow_id,
        )

        with SetWorkflowID(dbos_workflow_id):
            await dbos_client.enqueue_async(
                options=enqueue_options,
                workflow_run_metadata=workflow_run_metadata,
                trace_id=trace_id,
            )

        logger.info(
            message="[GenericWorkflowProcessorClientQueue] Enqueued workflow run to DBOS",
            metadata={
                "workflow_run_id": workflow_run_metadata.workflow_run_id,
                "trace_id": trace_id,
                "queue_name": queue_name,
                "workflow_name": workflow_name,
            },
        )

        return True

    @staticmethod
    async def enqueue_workflow_run_watcher_processor(
        workflow_run_watcher_metadata: WorkflowRunWatcherMetadataDAO,
        trace_id: Optional[str] = None,
    ) -> bool:
        """Enqueue workflow run to DBOS for watcher processing.

        Args:
            workflow_run_watcher_metadata: Watcher metadata for batch runs
            trace_id: Optional trace ID for request tracing

        Returns:
            True if successfully enqueued, False otherwise
        """
        queue_name: str = DBOSQueues.GENERIC_REPORT_WORKFLOW_PROCESSOR_QUEUE
        workflow_name: str = (
            DBOSWorkflows.GENERIC_REPORT_WORKFLOW_WATCHER_PROCESSOR_WORKFLOW
        )

        first_workflow_run_id = workflow_run_watcher_metadata.first_workflow_run_id
        partition_key = workflow_run_watcher_metadata.partition_key

        dbos_workflow_id: str = f"{workflow_name}_{first_workflow_run_id}"

        if trace_id is None:
            trace_id = get_request_id_context(first_workflow_run_id)

        enqueue_options: EnqueueOptions = EnqueueOptions(
            queue_name=queue_name,
            workflow_name=workflow_name,
            queue_partition_key=partition_key,
            deduplication_id=dbos_workflow_id,
        )

        with SetWorkflowID(dbos_workflow_id):
            await dbos_client.enqueue_async(
                options=enqueue_options,
                workflow_run_watcher_metadata=workflow_run_watcher_metadata,
                trace_id=trace_id,
            )

        logger.info(
            message="[GenericWorkflowWatcherProcessorClientQueue] Enqueued workflow run to DBOS",
            metadata={
                "first_workflow_run_id": first_workflow_run_id,
                "trace_id": trace_id,
                "queue_name": queue_name,
                "workflow_name": workflow_name,
                "partition_key": partition_key,
                "dbos_workflow_id": dbos_workflow_id,
            },
        )

        return True
```

### Step 3: Create the Worker

File: `src/tasks/dbos_workers/<workflow_domain>/<queue_name>_worker.py`

The worker defines DBOS workflow functions that process queued tasks:

```python
from typing import Optional
from config.cfg import cfg
from config.logger import set_request_id_context
from connectors.async_pg import get_async_db_session
from src.apps.data_manager.services.workflow_run.workflow_run_execution_app_service import (
    WorkflowRunExecutionAppService,
)
from src.apps.data_manager.services.workflow_run.workflow_run_watcher_service import (
    WorkflowRunWatcherService,
)
from src.domains.workflow_run.dao import (
    WorkflowRunEventDAO,
    WorkflowRunMetadataDAO,
    WorkflowRunWatcherMetadataDAO,
)
from src.tasks.dbos_workers.dbos_event_keys import DBOSEventKeys
from src.tasks.dbos_workers.dbos_queue import DBOSQueues, DBOSWorkflows
from src.tasks.dbos_workers.dbos_wrapper import DBOSWrapper
from src.tasks.dbos_workers.launcher import launch_workers


# Define the queue this worker processes
task_queue: DBOSWrapper.Queue = DBOSWrapper.Queue(
    name=DBOSQueues.GENERIC_REPORT_WORKFLOW_PROCESSOR_QUEUE,
    partition_queue=True,  # Enable partitioning for ordered processing
)


@DBOSWrapper.workflow(name=DBOSWorkflows.GENERIC_REPORT_WORKFLOW_PROCESSOR_WORKFLOW)
async def generic_report_workflow_processor(
    workflow_run_metadata: WorkflowRunMetadataDAO,
    trace_id: Optional[str] = None,
) -> None:
    """Process a single workflow run.

    This workflow:
    1. Executes the workflow run (e.g., runs SQL query, saves to S3)
    2. Sets a completion event that watchers can listen to
    3. Handles both success and failure cases
    """
    set_request_id_context(trace_id)

    async with get_async_db_session() as db_session:
        workflow_run_execution_app_service: WorkflowRunExecutionAppService = (
            WorkflowRunExecutionAppService(
                workflow_run_metadata=workflow_run_metadata,
                db_session=db_session,
            )
        )
        try:
            await workflow_run_execution_app_service.invoke()
            await DBOSWrapper.set_event_async(
                key=DBOSEventKeys.WORKFLOW_RUN_COMPLETED,
                value=WorkflowRunEventDAO(
                    is_successful=True,
                ),
            )
        except Exception as e:
            await DBOSWrapper.set_event_async(
                key=DBOSEventKeys.WORKFLOW_RUN_COMPLETED,
                value=WorkflowRunEventDAO(
                    is_successful=False,
                ),
            )
            raise e


@DBOSWrapper.workflow(
    name=DBOSWorkflows.GENERIC_REPORT_WORKFLOW_WATCHER_PROCESSOR_WORKFLOW
)
async def generic_report_workflow_watcher_processor(
    workflow_run_watcher_metadata: WorkflowRunWatcherMetadataDAO,
    trace_id: Optional[str] = None,
) -> None:
    """Watch workflow runs and orchestrate multi-step workflows.

    This workflow:
    1. Waits for all workflow runs to complete
    2. Based on success/failure, triggers next workflow runs
    3. Enqueues new watchers for those next workflow runs (recursive chain)
    """
    set_request_id_context(trace_id)

    async with get_async_db_session() as db_session:
        workflow_run_watcher_service: WorkflowRunWatcherService = (
            WorkflowRunWatcherService(
                workflow_run_watcher_metadata=workflow_run_watcher_metadata,
                db_session=db_session,
            )
        )
        await workflow_run_watcher_service.invoke()


if __name__ == "__main__":
    launch_workers(cfg("DBOS_NUMBER_OF_WORKERS"))
```

### Step 4: Create the Watcher Service

File: `src/apps/<app_name>/services/<domain>/<domain>_watcher_service.py`

The watcher service orchestrates the recursive chain:

```python
from typing import Awaitable, Callable, Dict, List, Optional, Type
from sqlalchemy.ext.asyncio import AsyncSession
from config import logger
from src.domains.workflow_run.dao import (
    WorkflowRunWatcherMetadataDAO,
    WorkflowRunEventDAO,
)
from src.tasks.dbos_workers.dbos_wrapper import DBOSWrapper


class WorkflowRunWatcherService:
    """Service for watching workflow run completion and orchestrating multi-step workflows.

    This service implements a recursive pattern where each watcher:
    1. Waits for one or more workflow runs to complete
    2. Creates new workflow runs based on success/failure actions
    3. Enqueues new watchers for those newly created workflow runs

    Initial Invocation:
    -------------------
    The watcher is first invoked when a user creates a workflow run via an API endpoint.
    The controller enqueues the initial watcher by calling:
        GenericReportEnqueuer.enqueue_workflow_run_watcher_processor(workflow_run_watcher_metadata)

    Recursive Chain:
    ----------------
    After the initial invocation, the watcher creates a self-sustaining chain:
    - Each watcher waits for its workflow runs to complete (_watch_workflow_run)
    - Based on success/failure, it creates new workflow runs (_trigger_next_workflow_runs)
    - For each new workflow run, it enqueues a new watcher (_enqueue_workflow_watchers)
    - This continues until no more workflows have success/failure actions configured
    """

    def __init__(
        self,
        workflow_run_watcher_metadata: WorkflowRunWatcherMetadataDAO,
        db_session: AsyncSession,
        # ... other dependencies
    ):
        self.workflow_run_watcher_metadata = workflow_run_watcher_metadata
        self.db_session = db_session
        self.is_all_successful = True
        self.workflow_run_watcher_metadatas: List[WorkflowRunWatcherMetadataDAO] = []

    async def invoke(self) -> None:
        """Main entry point orchestrating the three-phase workflow watching process."""
        await self._watch_workflow_run()
        await self._trigger_next_workflow_runs()
        await self._enqueue_workflow_watchers()

    async def _watch_workflow_run(self) -> None:
        """Wait for workflow runs to complete and track overall success."""
        for workflow_run_id in self.workflow_run_watcher_metadata.workflow_run_ids:
            # Wait for workflow completion event
            workflow_run_event: WorkflowRunEventDAO = (
                await DBOSWrapper.get_event_async(
                    workflow_id=f"workflow_{workflow_run_id}",
                    key="WORKFLOW_RUN_COMPLETED",
                    timeout_seconds=3600,
                )
            )

            if not workflow_run_event or not workflow_run_event.is_successful:
                self.is_all_successful = False

    async def _trigger_next_workflow_runs(self) -> None:
        """Create and enqueue next workflows based on run success/failure."""
        for workflow_run_id in self.workflow_run_watcher_metadata.workflow_run_ids:
            # Get next workflow names based on success/failure
            next_workflow_names = await self._get_next_workflow_names(workflow_run_id)

            if not next_workflow_names:
                continue

            new_workflow_run_ids = []
            for workflow_name in next_workflow_names:
                # Create new workflow run
                result = await self._create_next_workflow_run(workflow_name, workflow_run_id)
                new_workflow_run_ids.append(result.workflow_run.id)

            # Store metadata for new watchers
            self.workflow_run_watcher_metadatas.append(
                WorkflowRunWatcherMetadataDAO(
                    first_workflow_run_id=new_workflow_run_ids[0],
                    workflow_run_ids=new_workflow_run_ids,
                    partition_key=self.workflow_run_watcher_metadata.partition_key,
                )
            )

    async def _enqueue_workflow_watchers(self) -> None:
        """Enqueue new watchers for the newly created workflow runs (recursive chain)."""
        for watcher_metadata in self.workflow_run_watcher_metadatas:
            await self.generic_workflow_processor_queue.enqueue_workflow_run_watcher_processor(
                workflow_run_watcher_metadata=watcher_metadata,
            )
```

### Step 5: Initial Trigger from Controller/API

File: `src/apps/<app_name>/routers/<resource>_controller.py`

The API endpoint creates the first workflow run and enqueues the initial watcher:

```python
from fastapi import APIRouter, Depends, status
from src.domains.workflow_run.dao import WorkflowRunCreateDAO, WorkflowRunWatcherMetadataDAO
from src.tasks.dbos_workers.reports.generic_report_enqueuer import GenericReportEnqueuer


@router.post("/workflow-runs")
async def create_workflow_run(
    workflow_run_create_dao: WorkflowRunCreateDAO,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Create a workflow run and start the orchestration chain."""

    # Create the workflow run in database
    service = WorkflowRunCreateAppService(
        create_workflow_run_dao=workflow_run_create_dao,
        db_session=db_session,
    )
    result = await service.invoke()

    # Enqueue the initial watcher
    workflow_run_watcher_metadata = WorkflowRunWatcherMetadataDAO(
        first_workflow_run_id=result.workflow_run.id,
        workflow_run_ids=[result.workflow_run.id],
        partition_key=result.partition_key,
        run_attributes=result.workflow_run.run_attributes,
        workflow_run_ids_by_name=result.workflow_run_ids_by_name,
    )

    await GenericReportEnqueuer.enqueue_workflow_run_watcher_processor(
        workflow_run_watcher_metadata=workflow_run_watcher_metadata,
    )

    return {"status": "success", "workflow_run_id": result.workflow_run.id}
```

## Complete Flow Example: TBI Acknowledgement Report

This example demonstrates a 3-step workflow:

### Database Schema

```python
# workflows table
workflows = [
    {
        "id": 1,
        "name": "generate_aack_records",
        "query_id": 1,  # SQL to generate acknowledgement records
        "success_action_type": "DBOS_WORKFLOW",
        "success_action_names": ["generate_atrl_records"],
    },
    {
        "id": 2,
        "name": "generate_atrl_records",
        "query_id": 2,  # SQL to generate control records
        "success_action_type": "DBOS_WORKFLOW",
        "success_action_names": ["merge_aack_file"],
    },
    {
        "id": 3,
        "name": "merge_aack_file",
        "workflow_type": "MERGE_S3_FILES",
        "success_action_type": None,  # Final step, no next workflow
    }
]
```

### Execution Flow

```
1. User calls POST /workflow-runs with workflow_id=1
   ↓
2. Controller creates workflow_run record (id=101)
   ↓
3. Controller enqueues initial watcher with workflow_run_ids=[101]
   ↓
4. Watcher starts → waits for workflow_run 101 to complete
   |
   ├─→ workflow_run 101 executes → generates AACK records CSV → saves to S3
   |
   ↓
5. Watcher detects success → reads workflow.success_action_names = ["generate_atrl_records"]
   ↓
6. Watcher creates workflow_run 102 for "generate_atrl_records"
   ↓
7. Watcher enqueues NEW watcher with workflow_run_ids=[102]
   ↓
8. New watcher starts → waits for workflow_run 102 to complete
   |
   ├─→ workflow_run 102 executes → generates ATRL records CSV → saves to S3
   |
   ↓
9. Watcher detects success → reads workflow.success_action_names = ["merge_aack_file"]
   ↓
10. Watcher creates workflow_run 103 for "merge_aack_file"
    ↓
11. Watcher enqueues NEW watcher with workflow_run_ids=[103]
    ↓
12. New watcher starts → waits for workflow_run 103 to complete
    |
    ├─→ workflow_run 103 executes → merges files → uploads final AACK file to S3
    |
    ↓
13. Watcher detects success → reads workflow.success_action_names = None
    ↓
14. Chain terminates (no more watchers enqueued)
```

## Best Practices

### 1. Partition Keys

Always use consistent partition keys across a workflow chain to ensure:
- Ordered processing in DBOS
- No race conditions between dependent steps

```python
# First workflow
partition_key = f"workflow_run_{workflow_run_id}"

# All subsequent workflows use the SAME partition key
```

### 2. Workflow ID Generation

Create unique, deterministic workflow IDs for:
- Deduplication (prevent duplicate executions)
- Event tracking (so watchers can find completion events)

```python
@staticmethod
def build_workflow_id(workflow_run_id: str) -> str:
    return f"{workflow_name}_{workflow_run_id}"
```

### 3. Event-Based Communication

Use DBOS events to communicate between workflows:

```python
# Worker sets event after completion
await DBOSWrapper.set_event_async(
    key="WORKFLOW_RUN_COMPLETED",
    value=WorkflowRunEventDAO(is_successful=True),
)

# Watcher listens for event
event = await DBOSWrapper.get_event_async(
    workflow_id=workflow_id,
    key="WORKFLOW_RUN_COMPLETED",
    timeout_seconds=3600,
)
```

### 4. Context Propagation

Propagate important context through the workflow chain:

```python
class WorkflowRunWatcherMetadataDAO(BaseModel):
    workflow_run_ids: List[int]
    partition_key: str
    run_attributes: Dict  # User inputs, variables
    workflow_run_ids_by_name: Dict[str, int]  # For S3 path resolution
```

### 5. Application Service Separation

Never include business logic directly in workers. Always delegate to application services:

```python
# ❌ BAD - Logic in worker
@DBOSWrapper.workflow()
async def process_workflow(data):
    result = execute_sql(data.query)
    save_to_s3(result)

# ✅ GOOD - Delegate to service
@DBOSWrapper.workflow()
async def process_workflow(metadata):
    service = WorkflowRunExecutionAppService(metadata=metadata)
    await service.invoke()
```

### 6. Error Handling

Set failure events and implement failure actions:

```python
try:
    await service.invoke()
    await DBOSWrapper.set_event_async(
        key="WORKFLOW_RUN_COMPLETED",
        value=WorkflowRunEventDAO(is_successful=True),
    )
except Exception as e:
    await DBOSWrapper.set_event_async(
        key="WORKFLOW_RUN_COMPLETED",
        value=WorkflowRunEventDAO(is_successful=False, error=str(e)),
    )
    raise e
```

Configure failure actions in workflow configuration:

```python
workflow = {
    "failure_action_type": "DBOS_WORKFLOW",
    "failure_action_names": ["send_error_notification"],
}
```

### 7. Testing

Test each component independently:

```python
# Test enqueuer
async def test_enqueue_workflow_run():
    metadata = WorkflowRunMetadataDAO(workflow_run_id=1, partition_key="key")
    result = await GenericReportEnqueuer.enqueue_workflow_run_processor(metadata)
    assert result is True

# Test watcher service
async def test_watcher_triggers_next_workflow():
    watcher = WorkflowRunWatcherService(metadata, db_session)
    await watcher.invoke()
    assert len(watcher.workflow_run_watcher_metadatas) == 1

# Test application service
async def test_workflow_execution():
    service = WorkflowRunExecutionAppService(metadata, db_session)
    result = await service.invoke()
    assert result.s3_location is not None
```

## Common Pitfalls

### 1. Missing Partition Keys
**Problem**: Workflows execute out of order, causing data inconsistencies.
**Solution**: Always propagate the same partition key through the entire chain.

### 2. Incorrect Workflow IDs
**Problem**: Watchers can't find completion events, causing timeouts.
**Solution**: Use the same ID generation logic in both worker and watcher.

### 3. Forgetting to Enqueue Watchers
**Problem**: Workflow chain stops after the first step.
**Solution**: Always call `_enqueue_workflow_watchers()` in watcher service.

### 4. Circular Dependencies
**Problem**: Workflow A triggers B, which triggers A, creating an infinite loop.
**Solution**: Carefully design workflow chains with clear terminal nodes.

### 5. Long-Running Workers
**Problem**: DBOS worker timeouts or resource exhaustion.
**Solution**: Keep workflow functions lightweight; delegate heavy work to services.

## References

1. [DBOS Python Workflow Tutorial](https://docs.dbos.dev/python/tutorials/workflow-tutorial)
2. [DBOS Queue Tutorial](https://docs.dbos.dev/python/tutorials/queue-tutorial)
3. [DBOS Workflow Management](https://docs.dbos.dev/python/tutorials/workflow-management)
4. See also: `skills/coding/build-schedulers-tasks-with-dbos/SKILL.md` for basic DBOS patterns
