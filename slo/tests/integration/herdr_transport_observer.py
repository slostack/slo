"""Test-only terminal accounting at the real Herdr transport boundary."""

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Optional

from src.agents.slo_agent.herdr.dao import HerdrCommandAdmission, HerdrCommandResultDAO
from src.agents.slo_agent.herdr.service import HerdrCliTransport


@dataclass
class TransportObservation:
    """One invocation, with fixed diagnostics and separately retained task evidence."""

    task_id: int
    operation: str
    status: Literal["pending", "returned", "cancelled", "error"] = "pending"
    terminals: int = 0
    admitted: bool = False
    completions: int = 0
    completion_status: Optional[str] = None
    child: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    task: Optional[asyncio.Task[object]] = field(default=None, repr=False)
    drained: bool = False

    def finish(self, *, transport: HerdrCliTransport) -> None:
        """Record terminal evidence only after invoke has unwound its real cleanup."""
        self.terminals += 1
        self.drained = not self.admitted or (
            transport._active is None and transport._spawn_task is None and transport._cleanup_task is None
        )

    def assert_terminal(self) -> None:
        """Require exactly one terminal, completed owner accounting and reaped child."""
        assert self.status in ("returned", "cancelled"), self
        assert self.terminals == 1 and self.drained, self
        assert self.completions == int(self.admitted), self
        if self.child is not None:
            assert self.child.returncode is not None, self
        assert self.task is not None and self.task.done(), self


class ObservedAdmission:
    """Observe, without replacing, synchronous owner admission and completion."""

    def __init__(
        self,
        *,
        delegate: HerdrCommandAdmission,
        observation: TransportObservation,
        transport: HerdrCliTransport,
    ) -> None:
        """Bind one invocation's real owner and resource evidence."""
        self._delegate = delegate
        self._observation = observation
        self._transport = transport

    def try_admit(self) -> bool:
        """Preserve the real owner's decision under the acquired command lock."""
        self._observation.admitted = self._delegate.try_admit()
        return self._observation.admitted

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Prove reap precedes exactly-once delegation, retaining no private output."""
        observation = self._observation
        observation.completions += 1
        observation.completion_status = result.outcome.status
        observation.child = self._transport._active
        assert observation.child is None or observation.child.returncode is not None
        self._delegate.complete(result=result)
