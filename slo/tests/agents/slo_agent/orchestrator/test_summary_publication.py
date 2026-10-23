"""Real pool publication and chain substitution without child processes."""

import json
from pathlib import Path
from typing import Optional
from uuid import uuid4

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber


class FiniteChildProcess(SubAgentProcess):
    """Use real wrapper construction and registry arbitration, never transport."""

    bound_task: SubAgentTaskDAO
    bound_registry: ProcessRegistry

    async def run(self) -> SubAgentResultDAO:
        """Finish the bound task through the real terminal winner."""
        return self.bound_registry.commit_terminal(
            terminal_reason="completed",
            terminated_by="natural",
            result=SubAgentResultDAO(
                task_id=self.bound_task.task_id,
                session_id=self.session_id,
                status="completed",
                exit_code=0,
                execution_id=self.execution_id,
                answer="Task: Competing previous output",
            ),
        )


async def test_summary_survives_chain_publication(tmp_path: Path) -> None:
    """Actual tool → pool → saved fleet preserves authored labels across substitution."""
    events: list[AgentStreamEventDAO] = []
    processes: list[FiniteChildProcess] = []

    async def relay(event: AgentStreamEventDAO) -> None:
        """Record emitted lifecycle content."""
        events.append(event)

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
        """Bind fixture-owned public data alongside the real constructor."""
        process = FiniteChildProcess(
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
        process.bound_registry = registry
        process.bound_task = task
        processes.append(process)
        return process

    pool = SubAgentPool(
        orchestrator_session_id="parent",
        default_model=None,
        relay=relay,
        owner_session_id="parent",
        run_id=str(uuid4()),
        history_root=tmp_path,
        process_factory=factory,
    )
    tool = SpawnSubAgentsTool.build(pool=pool)
    await tool.ainvoke(
        {
            "mode": "chain",
            "tasks": [
                {
                    "task_id": "first",
                    "prompt": "Summarize the supplied text; no approval gate is involved.",
                    "task_summary": "Summarize the supplied text",
                },
                {
                    "task_id": "second",
                    "prompt": "Shorten this summary without changing its meaning: {previous}",
                    "task_summary": "Shorten the supplied summary without changing meaning",
                },
            ],
        }
    )
    assert len(processes) == 2
    assert (
        processes[1].bound_task.prompt
        == "Shorten this summary without changing its meaning: Task: Competing previous output"
    )
    labels = ["Summarize the supplied text", "Shorten the supplied summary without changing meaning"]
    assert [p.bound_task.task_summary for p in processes] == labels
    assert [e.content for e in events if e.kind == "sub_agent_spawned"] == [
        "Task summary v1: " + label for label in labels
    ]

    fleet = json.loads((tmp_path / "parent" / "fleet.json").read_text())
    assert "task_summary" not in json.dumps(fleet)
    assert all("Task summary v1: " + label in json.dumps(fleet) for label in labels)
