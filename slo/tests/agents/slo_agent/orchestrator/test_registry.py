"""Tests for ``ProcessRegistry`` (sub-spec 01-sub-agents 01.c)."""

from __future__ import annotations

from src.agents.slo_agent.orchestrator.dao import SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry


def _task(
    task_id: str = "t1",
    prompt: str = "Do something.",
) -> SubAgentTaskDAO:
    """Build a minimal ``SubAgentTaskDAO`` for test convenience.

    Args:
        task_id (str): Task identifier.
        prompt (str): Task prompt text.

    Returns:
        SubAgentTaskDAO: Minimal task for use in registry tests.
    """
    return SubAgentTaskDAO(task_id=task_id, prompt=prompt)


class TestProcessRegistryRegister:
    """``register()`` creates entries in ``pending`` state."""

    def test_register_creates_pending_entry(self) -> None:
        """A registered task is immediately visible with ``status='pending'``."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert entry.status == "pending"
        assert entry.task_id == "t1"
        assert entry.session_id == "s1"

    def test_prompt_preview_truncates_at_120_chars(self) -> None:
        """``prompt_preview`` is capped to the first 120 characters."""
        long_prompt: str = "x" * 200
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(
            task_id="t1",
            session_id="s1",
            task=_task(prompt=long_prompt),
        )

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert len(entry.prompt_preview) == 120

    def test_prompt_preview_short_prompt_kept_intact(self) -> None:
        """A prompt shorter than 120 characters is stored in full."""
        short_prompt: str = "Short task."
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(
            task_id="t1",
            session_id="s1",
            task=_task(prompt=short_prompt),
        )

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert entry.prompt_preview == short_prompt


class TestProcessRegistryTransitions:
    """Lifecycle transition methods update state correctly."""

    def test_mark_running_transitions_to_running(self) -> None:
        """``mark_running`` transitions status from ``pending`` to ``running``."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())

        reg.mark_running(session_id="s1")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "running"

    def test_update_last_text_sets_last_text(self) -> None:
        """``update_last_text`` updates ``last_text`` without changing status."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())
        reg.mark_running(session_id="s1")

        reg.update_last_text(session_id="s1", text="Processing…")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.last_text == "Processing…"
        assert entry.status == "running"

    def test_mark_terminal_completed_sets_status_and_answer(self) -> None:
        """``mark_terminal`` with ``completed`` stores answer in ``last_text``."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())

        reg.mark_terminal(session_id="s1", status="completed", answer="Done!")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "completed"
        assert entry.last_text == "Done!"

    def test_mark_terminal_failed_sets_status(self) -> None:
        """``mark_terminal`` with ``failed`` sets status correctly."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())

        reg.mark_terminal(session_id="s1", status="failed", answer="Error: crash")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "failed"

    def test_unknown_session_id_is_a_noop_for_all_write_methods(self) -> None:
        """All write methods silently no-op for unregistered session ids."""
        reg: ProcessRegistry = ProcessRegistry()

        # None of these should raise:
        reg.mark_running(session_id="nonexistent")
        reg.update_last_text(session_id="nonexistent", text="x")
        reg.mark_terminal(
            session_id="nonexistent",
            status="failed",
            answer="",
        )

        assert reg.get(session_id="nonexistent") is None


class TestProcessRegistrySnapshot:
    """``snapshot()`` and ``get()`` read API behaviour."""

    def test_snapshot_returns_all_entries_in_insertion_order(self) -> None:
        """Snapshot preserves insertion order across two registered tasks."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task("t1"))
        reg.register(task_id="t2", session_id="s2", task=_task("t2"))

        snap = reg.snapshot()

        assert len(snap) == 2
        assert snap[0].task_id == "t1"
        assert snap[1].task_id == "t2"

    def test_snapshot_returns_a_copy_not_the_internal_list(self) -> None:
        """Mutating the returned snapshot list does not affect the registry."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())

        snap = reg.snapshot()
        snap.clear()

        assert reg.count == 1

    def test_get_returns_none_for_unknown_session_id(self) -> None:
        """``get()`` returns ``None`` when the session id is not registered."""
        reg: ProcessRegistry = ProcessRegistry()

        assert reg.get(session_id="unknown") is None


class TestProcessRegistryCounts:
    """``count`` and ``running_count`` property behaviour."""

    def test_count_reflects_total_registered_entries(self) -> None:
        """``count`` returns the total number of registered sub-agents."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task("t1"))
        reg.register(task_id="t2", session_id="s2", task=_task("t2"))

        assert reg.count == 2

    def test_running_count_reflects_only_running_entries(self) -> None:
        """``running_count`` counts only sub-agents in ``running`` state."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task("t1"))
        reg.register(task_id="t2", session_id="s2", task=_task("t2"))
        reg.mark_running(session_id="s1")

        assert reg.running_count == 1

    def test_running_count_zero_when_all_terminal(self) -> None:
        """``running_count`` returns 0 after all sub-agents reach terminal state."""
        reg: ProcessRegistry = ProcessRegistry()
        reg.register(task_id="t1", session_id="s1", task=_task())
        reg.mark_running(session_id="s1")
        reg.mark_terminal(session_id="s1", status="completed", answer="ok")

        assert reg.running_count == 0
