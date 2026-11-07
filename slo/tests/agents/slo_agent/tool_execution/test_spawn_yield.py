"""Original spawn/pool aggregate defers with injected children, never real processes."""

import asyncio
from pathlib import Path
from typing import Optional
from uuid import uuid4

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.pool import MAX_CONCURRENCY, SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber
from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)
from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl
from tests.agents.slo_agent.tool_execution.test_yield_control import RecordingMessageSource, _delivery


async def test_original_spawn_retains_children_permits_and_aggregate_on_urgency(tmp_path: Path) -> None:
    """Urgency neither releases held slots nor redispatches/replaces the original spawn."""
    release, full, deferred = asyncio.Event(), asyncio.Event(), asyncio.Event()
    started: list[str] = []
    instances: list[SubAgentProcess] = []

    class HeldChild(SubAgentProcess):
        bound_task: SubAgentTaskDAO
        bound_registry: ProcessRegistry

        async def run(self) -> SubAgentResultDAO:
            """Publish the real registry winner only after controlled child completion."""
            started.append(self.bound_task.task_id)
            if len(started) == MAX_CONCURRENCY:
                full.set()
            await release.wait()
            return self.bound_registry.commit_terminal(
                terminal_reason="completed",
                terminated_by="natural",
                result=SubAgentResultDAO(
                    task_id=self.bound_task.task_id,
                    session_id=self.session_id,
                    execution_id=self.execution_id,
                    status="completed",
                    answer="actual child",
                    exit_code=0,
                ),
            )

    async def relay(event: AgentStreamEventDAO) -> None:
        """Keep pool lifecycle observation separate from execution policy."""

    def factory(
        *,
        task: SubAgentTaskDAO,
        session_id: str,
        model: Optional[str],
        relay: AgentEventSubscriber,
        registry: ProcessRegistry,
        execution_id: str,
        system_prompt: str,
        parent_session_id: str,
        history_root: Path,
    ) -> SubAgentProcess:
        """Inject child timing at the authorized launcher seam, never execute a child."""
        child = HeldChild(
            task=task,
            session_id=session_id,
            model=model,
            relay=relay,
            registry=registry,
            execution_id=execution_id,
            system_prompt=system_prompt,
            parent_session_id=parent_session_id,
            history_root=history_root,
        )
        child.bound_task, child.bound_registry = task, registry
        instances.append(child)
        return child

    pool = SubAgentPool(
        orchestrator_session_id="parent",
        default_model=None,
        relay=relay,
        owner_session_id="parent",
        run_id=str(uuid4()),
        history_root=tmp_path,
        process_factory=factory,
    )
    spawn = SpawnSubAgentsTool.build(pool=pool)
    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda _: deferred.set())
    control.enter_provider(delivery=_delivery(), attempt_turn_id=str(uuid4()), iteration=0)
    control.enter_tools(tool_call_ids=("spawn",))
    tasks = [
        {
            "task_id": f"child-{index}",
            "task_summary": "Verify held child aggregate",
            "prompt": "Synthetic fixture only",
        }
        for index in range(MAX_CONCURRENCY + 1)
    ]
    plan = ToolExecutionPlanDAO(
        run_concurrently=False,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "spawn", "name": spawn.name, "args": {"mode": "parallel", "tasks": tasks}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            )
        ],
    )
    executor = SequentialToolExecutor(tools_by_name={spawn.name: spawn})
    owner = asyncio.create_task(coro=executor.execute(plan=plan, control=control))
    try:
        async with asyncio.timeout(delay=5):
            await full.wait()
        source.publish_newer_urgency(sequence=1)
        async with asyncio.timeout(delay=5):
            await deferred.wait()
        assert not owner.done() and len(started) == MAX_CONCURRENCY
        assert len(instances) == MAX_CONCURRENCY + 1
        release.set()
        result = await owner
        assert len(started) == MAX_CONCURRENCY + 1 and len(set(started)) == len(started)
        assert len(result) == 1 and result[0].tool_call_id == "spawn" and result[0].status == "success"
        assert all(row.status == "completed" for row in pool.registry.snapshot())
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
        await pool.abort_and_drain()
