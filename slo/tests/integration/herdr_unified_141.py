"""Assertions for the same mounted prompt/configuration/both-viewer continuation."""

import json
from pathlib import Path

from textual.pilot import Pilot

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.state_isolation import FakeHerdrFixture
from tests.tui.test_herdr_activation_composed import commands, eventually


class UnifiedMountedJourney:
    """Continue the original mounted app without replacing its session or viewer gateway."""

    def __init__(self, *, root: Path, fake: FakeHerdrFixture, uncertain: bool) -> None:
        """Bind test-owned file authority and retain revision bytes across transitions."""
        self.root = root.resolve(strict=True)
        self.fake = fake
        self.uncertain = uncertain
        self.records: dict[Path, bytes] = {}

    async def invoke(self, app: SloTUI, pilot: Pilot[None]) -> None:
        """Run both public viewer routes and configuration actions after real prompt completion."""
        session = app._session
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        await eventually(predicate=lambda: reporter._saved is not None)
        await self.assert_advertised(session=session)
        await self.open_both(app=app, session=session)
        await self.submit(app=app, pilot=pilot, text="/rename unified-141")
        await eventually(predicate=lambda: session.session_name == "unified-141")
        await self.assert_advertised(session=session)
        await self.submit(app=app, pilot=pilot, text="/model gpt-4.1")
        await eventually(
            predicate=lambda: reporter._saved is not None
            and reporter._saved.capture.config.model_name == "gpt-4.1"
            and reporter._saved.capture.config.model_pool_dao is None
        )
        await self.assert_advertised(session=session)
        assert session.usage_snapshot().session_totals.total_tokens == 8
        assert session._history_store is not None
        before = await session._history_store.load_events(session_id=session.session_id)
        assert [event.payload.content for event in before if event.kind == "user_message"] == [
            "Run the clock then finish"
        ]
        assert sum(event.kind == "run_completed" for event in before) == 1
        assert [event.payload.tool_name for event in before if event.kind == "tool_result"] == ["now"]
        await self.submit(app=app, pilot=pilot, text="/new")
        await eventually(predicate=lambda: app._session is not session)
        successor = app._session
        successor_reporter = successor._herdr_reporter
        assert isinstance(successor_reporter, HerdrReporter)
        await eventually(predicate=lambda: successor_reporter._saved is not None)
        await self.assert_advertised(session=successor)
        assert successor.usage_snapshot().session_totals.total_tokens is None
        assert session.usage_snapshot().session_totals.total_tokens == 8
        assert await session._history_store.load_events(session_id=session.session_id) == before
        assert successor._history_store is not None
        fresh = await successor._history_store.load_events(session_id=successor.session_id)
        assert not any(event.kind in {"user_message", "tool_result", "run_completed"} for event in fresh)
        await eventually(predicate=lambda: any(successor.session_id in row for row in commands(self.fake)))
        rows = commands(self.fake)
        claim = next(index for index, row in enumerate(rows) if successor.session_id in row)
        assert any(row[1] == "release-agent" for row in rows[:claim])
        assert not any(session.session_id in row for row in rows[claim:])
        assert not reporter.retains_external_resources
        assert not app._visualizer_launch_tasks
        self.assert_immutable()

    @staticmethod
    async def submit(*, app: SloTUI, pilot: Pilot[None], text: str) -> None:
        """Use the actual PromptInput key handler rather than invoking a slash handler."""
        await pilot.pause()
        assert app._input is not None
        app._input.focus()
        app._input.load_text(text)
        await pilot.press("enter")

    async def assert_advertised(self, *, session: SloAgentSession) -> None:
        """Wait for exact durable revision argv at the real registered CLI boundary."""
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        saved = reporter._saved
        assert saved is not None
        expected = [
            "slo",
            "--resume",
            session.session_id,
            "--herdr-restore",
            saved.reference.restore_reference,
        ]
        await eventually(
            predicate=lambda: any(
                "--" in row and row[row.index("--") + 1 :] == expected for row in commands(self.fake)
            )
        )
        self.assert_saved(session=session)

    def assert_saved(self, *, session: SloAgentSession) -> None:
        """Compare every private policy field, generation and advertised plain argv."""
        reporter = session._herdr_reporter
        assert isinstance(reporter, HerdrReporter)
        saved = reporter._saved
        assert saved is not None
        capture = session._herdr_capture
        assert capture is not None
        assert saved.capture == capture
        config = saved.capture.config
        assert config.session_id == session.session_id
        assert config.workdir == self.root
        assert config.workspace_file is None
        assert config.plugin_paths == ()
        assert session._config is not None
        assert config.model_name == session._config.model_name
        assert config.reasoning_level == session.active_reasoning_level
        assert saved.configuration_generation == session._herdr_configuration_generation
        expected_pool = session.model_pool_dao
        assert (config.model_pool_dao.model_dump(mode="json") if config.model_pool_dao else None) == (
            expected_pool.model_dump(mode="json") if expected_pool else None
        )
        reference = saved.reference.restore_reference
        path = reporter._config.state_root / "restore-v1" / f"{reference}.json"
        assert path.resolve().is_relative_to(self.root)
        record = json.loads(path.read_bytes())
        assert record == {
            "schema_version": 1,
            "restore_reference": reference,
            "config": config.model_dump(mode="json"),
        }
        self.assert_immutable()
        self.records[path] = path.read_bytes()

    def assert_immutable(self) -> None:
        """Prior revisions remain byte-identical through later publication and replacement."""
        assert all(path.read_bytes() == content for path, content in self.records.items())

    async def open_both(self, *, app: SloTUI, session: SloAgentSession) -> None:
        """Deliver attached and detached public events with distinct valid persisted parents."""
        detached = SloAgentSession.build(config=SessionConfigDAO(workdir=self.root, model_name="gpt-5.4"))
        await detached.rename_session(session_name="detached-141")
        for parent in (session, detached):
            assert parent.history_root is not None
            context = parent.history_root / parent.session_id / "orchestrator_context.json"
            assert context.resolve().is_relative_to(self.root)
            assert not context.is_symlink()
            context.write_text(
                OrchestratorContextDAO.build(
                    system_prompt="offline", user_prompt="offline", model=None
                ).model_dump_json(),
                encoding="utf-8",
            )
        events = [
            AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child-141", task_id="task-141"),
            AgentStreamEventDAO(
                kind="tool_result",
                tool_name="launch_workflow",
                tool_call_id="launch-141",
                content=json.dumps({"workflow_id": "wf-141", "orchestrator_session_id": detached.session_id}),
            ),
        ]
        expected: list[list[str]] = []
        for parent, event in zip((session, detached), events, strict=True):
            await session.event_relay(event)
            await eventually(predicate=lambda: not app._visualizer_launch_tasks)
            expected.append(
                ["pane", "split", "--pane", "synthetic-pane", "--direction", "right", "--no-focus"]
            )
            uncertain_parent = self.uncertain and parent is detached
            if not uncertain_parent:
                expected.extend(
                    [
                        ["pane", "rename", "unified-viewer", f"Slo workflow {parent.session_id[:8]}"],
                        [
                            "pane",
                            "run",
                            "unified-viewer",
                            f"slo visualize --session {parent.session_id} --follow",
                        ],
                    ]
                )
            rows = [
                row
                for row in commands(self.fake)
                if row[:2] in [["pane", op] for op in ("split", "rename", "run")]
            ]
            assert rows == expected
            outcome = await session.open_workflow_visualizer(parent_session_id=parent.session_id)
            assert outcome.status == ("failed" if uncertain_parent else "reused")
            await session.event_relay(event)
            await eventually(predicate=lambda: not app._visualizer_launch_tasks)
            assert [
                row
                for row in commands(self.fake)
                if row[:2] in [["pane", op] for op in ("split", "rename", "run")]
            ] == expected
        assert app._adapter is not None
        assert sum("Submitted workflow viewer command" in str(line) for line in app._adapter.lines) == (
            1 if self.uncertain else 2
        )
        assert not any(
            row[:2] in [["pane", op] for op in ("focus", "get", "close")] for row in commands(self.fake)
        )
