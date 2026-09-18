"""Characterize HeadlessRunner JSONL ordering, preflight audit, and abort semantics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.cli.headless import HeadlessRunner
from tests.characterization.baseline_contract import BaselineCaseDAO, BaselineComparator
from tests.characterization.normalizers import normalize_baseline_capture
from tests.fakes.tui_v2_79.session import BaselineSession

_BASELINE_ROOT: Path = Path("tests/fixtures/79_tui_v2/baseline")
_FIXTURE_PATH: Path = _BASELINE_ROOT / "headless/jsonl_abort_preflight_bypassed.jsonl"
_LEDGER_PATH: Path = _BASELINE_ROOT / "baseline-ledger.json"


async def test_jsonl_abort_and_preflight_bypassed_match_baseline(tmp_path: Path, capsys) -> None:
    """Freeze JSONL order and cooperative-abort behavior at the headless boundary.

    WHAT: Drives the production HeadlessRunner with a deterministic session and
        watchdog seam. The seam requests the runner's real cooperative abort
        path; it does not claim unpatched provider or session behavior.
    WHO: Future session or CLI replacements compare their headless contract here.
    WHEN: Before Slotui-related integration changes touch the headless path.
    """
    events: list[AgentStreamEventDAO] = [
        AgentStreamEventDAO(
            kind="preflight_bypassed",
            content="Local token preflight could not provide a useful wait; sending the request to the provider.",
            metadata={"estimated_tokens": 4097, "tokens_per_minute": 4096},
        ),
        AgentStreamEventDAO(kind="text_start", block_id="answer-1"),
        AgentStreamEventDAO(kind="text_delta", block_id="answer-1", delta="partial answer"),
        AgentStreamEventDAO(kind="run_aborted", content="<aborted>"),
    ]
    session: BaselineSession = BaselineSession(
        events=events,
        session_id="baseline-headless-session",
        wait_for_abort_before_terminal=True,
    )
    config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path, model_name="faux", enable_history=False)
    runner: HeadlessRunner = HeadlessRunner(config=config)

    with (
        patch("src.cli.headless.SloAgentSession.build", return_value=session),
        patch("src.cli.headless.HeadlessWatchdog", _AbortRequestingWatchdog),
    ):
        exit_code: int = await runner.invoke(prompt="baseline prompt")

    raw_stdout: bytes = capsys.readouterr().out.encode("utf-8")
    expected: bytes = _FIXTURE_PATH.read_bytes()
    observed: bytes = normalize_baseline_capture(
        capture=raw_stdout,
        case_id="headless-jsonl-abort-preflight-bypassed",
    )
    case: BaselineCaseDAO = BaselineCaseDAO(
        case_id="headless-jsonl-abort-preflight-bypassed",
        artifact_path="tests/fixtures/79_tui_v2/baseline/headless/jsonl_abort_preflight_bypassed.jsonl",
        normalizer_version="v1",
    )
    ledger = BaselineComparator.load_ledger(ledger_path=_LEDGER_PATH)
    BaselineComparator.compare(case=case, observed=observed, expected=expected, ledger=ledger)
    assert exit_code == 2
    assert session.abort_calls == 1


class _AbortRequestingWatchdog:
    """Deterministically request the production runner's cooperative abort path."""

    def __init__(self, **kwargs: object) -> None:
        """Store the runner-owned cooperative-abort callback.

        Args:
            **kwargs (object): HeadlessWatchdog construction values; only the
                callback is relevant to this deterministic test seam.
        """
        callback: object = kwargs["on_abort"]
        if not callable(callback):
            raise TypeError("on_abort must be callable")
        self._on_abort: object = callback

    def start(self) -> None:
        """Request cooperative abort through HeadlessRunner's registered callback."""
        callback = self._on_abort
        assert callable(callback)
        callback("baseline_abort")

    def stop(self) -> None:
        """Match the production watchdog cleanup surface without background work."""
