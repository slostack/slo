#!/usr/bin/env python
"""validate_recovery.py — end-to-end smoke test for the Feature 50 LLM recovery path.

What this script validates
--------------------------
Feature 50 introduced an LLM-level recovery layer in ``SloAgent._react_loop``.
The layer catches exceptions that escape ``_execute_iteration_with_retry``,
classifies them via ``RecoveryPolicy``, and demotes ``LLM_RECOVERABLE`` errors
into a synthetic observation that the model can act on.

**Critical design note:** the recovery path is triggered by the LLM-provider
call itself failing (rate-limit, transient server error, credit exhaustion,
context-overflow after compaction), NOT by tool calls returning errors.

Why sub-agent timeouts do NOT trigger recovery
----------------------------------------------
When a spawned sub-agent goes silent for ``CHILD_INACTIVITY_TIMEOUT_SECONDS``
(default 3600 s), the following chain runs:

    _pump_stdout                     → raises TimeoutError
    SubAgentProcess.run()            → *catches* it → returns SubAgentResultDAO(status="failed")
    spawn_sub_agents tool            → returns JSON, never raises
    ToolExecutor._invoke_one()       → also catches tool exceptions → ToolMessage(status="error")

So sub-agent timeouts surface as failed tool results the LLM reasons about
normally. The Feature 50 recovery events (``recovery_started``,
``recovery_succeeded``, ``recovery_exhausted``) are never emitted.

What actually triggers recovery
--------------------------------
The LangGraph *agent node* raising — i.e. ``llm.ainvoke / astream`` raising.
This happens for:
  - Provider rate limits (429)
  - Transient provider failures (500/502/503/529)
  - Credit exhaustion (402 / billing errors)
  - Context overflow on initial attempt (before compaction)

This script simulates a transient provider failure by subclassing
``FauxChatModel`` so the first ``_astream`` call raises ``RuntimeError``,
then the second one succeeds.  ``RecoveryPolicy.classify`` sees a plain
``RuntimeError`` as ``LLM_RECOVERABLE`` and the loop proceeds.

Usage
-----
    cd /Users/siddharth/Code/slo/slo
    python scripts/validate_recovery.py

Expected output (trimmed)::

    [run_started]
    [recovery_started]     ← recovery triggered
    [recovery_succeeded]   ← model produced an answer after the observation
    [run_completed]
    ✓ Recovery validated: recovery_started + recovery_succeeded both emitted.

To exercise budget exhaustion (recovery_exhausted), pass --exhaust::

    python scripts/validate_recovery.py --exhaust
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path
from typing import AsyncIterator, Optional

# ── path bootstrap ────────────────────────────────────────────────────────────
# Run from the repo root: ``python scripts/validate_recovery.py``
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.messages import AIMessageChunk

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.recovery.service import RecoveryPolicy
from src.auth.credential_dao import ProviderName


# ── ANSI colours ──────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _colour(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}"


# ── custom failing faux models ────────────────────────────────────────────────


def _make_fail_once_llm(
    *,
    final_answer: str,
    failure: Exception,
) -> FauxChatModel:
    """Return a FauxChatModel that raises once then answers.

    Args:
        final_answer (str): Text the model returns on the second call.
        failure (Exception): Exception raised on the first call.

    Returns:
        FauxChatModel: The one-failure mock.
    """
    base = FauxChatModel(
        responses=[FauxChatModel.assistant_message(content=final_answer)]
    )
    call_count: list[int] = [0]

    class _FailOnceFaux(FauxChatModel):
        async def _astream(
            self,
            messages,
            stop=None,
            run_manager=None,
            **kwargs,
        ) -> AsyncIterator[ChatGenerationChunk]:
            call_count[0] += 1
            if call_count[0] == 1:
                raise failure
            async for chunk in base._astream(
                messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    return _FailOnceFaux(responses=[])


def _make_always_fail_llm(*, failure: Exception) -> FauxChatModel:
    """Return a FauxChatModel that always raises.

    Args:
        failure (Exception): Exception raised on every call.

    Returns:
        FauxChatModel: Always-failing mock.
    """

    class _AlwaysFailFaux(FauxChatModel):
        async def _astream(
            self,
            messages,
            stop=None,
            run_manager=None,
            **kwargs,
        ) -> AsyncIterator[ChatGenerationChunk]:
            raise failure
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))  # type: ignore[misc]  # pragma: no cover

    return _AlwaysFailFaux(responses=[])


# ── recovery policy ───────────────────────────────────────────────────────────


def _policy(exc: BaseException, recoveries_used: int):
    """Real RecoveryPolicy with no provider hint — for the validation.

    Args:
        exc (BaseException): Escaped exception.
        recoveries_used (int): Recoveries already spent.
    """
    return RecoveryPolicy.classify(exc=exc, provider=None)


# ── event printer ─────────────────────────────────────────────────────────────


def _print_event(event: AgentStreamEventDAO) -> None:
    """Print one event with colour-coding for recovery kinds.

    Args:
        event (AgentStreamEventDAO): Event to display.
    """
    kind = event.kind
    if kind in {"recovery_started", "recovery_succeeded", "recovery_exhausted"}:
        colour = _GREEN if kind == "recovery_succeeded" else (
            _YELLOW if kind == "recovery_started" else _RED
        )
        tag = _colour(f"[{kind}]", colour)
        extra = ""
        if event.content:
            extra = f"  {_DIM}{event.content[:80]}{_RESET}"
        print(f"  {tag}{extra}")
    elif kind in {"run_failed", "run_completed", "run_started"}:
        colour = _RED if kind == "run_failed" else (
            _GREEN if kind == "run_completed" else _CYAN
        )
        print(f"  {_colour(f'[{kind}]', colour)}")
    elif kind in {"text_delta", "thinking_delta", "assistant_delta"}:
        pass  # omit noisy deltas
    else:
        print(f"  {_DIM}[{kind}]{_RESET}")


# ── scenario A: single recovery ───────────────────────────────────────────────


async def run_scenario_single_recovery() -> bool:
    """Scenario A: LLM raises once → recovery fires → answer produced.

    Simulates a transient provider failure (e.g. a 500 from Anthropic or
    OpenAI) that the recovery layer demotes into an observation and retries.

    Returns:
        bool: True when the expected recovery events are present.
    """
    print(_colour("\n── Scenario A: single transient provider failure ──", _CYAN))
    print(
        _DIM
        + textwrap.dedent("""\
        LLM raises RuntimeError('transient provider failure') on the first call.
        RecoveryPolicy classifies it as LLM_RECOVERABLE.
        The recovery loop injects an observation and re-enters the iteration.
        The second LLM call returns the final answer.
        """)
        + _RESET
    )

    agent = SloAgent(
        llm=_make_fail_once_llm(
            final_answer="The answer is 42.",
            failure=RuntimeError("transient provider failure — simulated"),
        ),
        tools=[],
    )

    events: list[AgentStreamEventDAO] = []
    try:
        async for event in agent.invoke(
            query="What is the answer to life?",
            iteration_recovery_policy=_policy,
        ):
            _print_event(event)
            events.append(event)
    except Exception as exc:
        print(_colour(f"  ✗ unexpected exception: {exc}", _RED))
        return False

    kinds = {e.kind for e in events}
    ok = "recovery_started" in kinds and "recovery_succeeded" in kinds and "run_completed" in kinds
    if ok:
        print(_colour("  ✓ recovery_started + recovery_succeeded + run_completed — PASS", _GREEN))
    else:
        missing = {"recovery_started", "recovery_succeeded", "run_completed"} - kinds
        print(_colour(f"  ✗ missing events: {missing}", _RED))
    return ok


# ── scenario B: budget exhaustion ────────────────────────────────────────────


async def run_scenario_budget_exhaustion() -> bool:
    """Scenario B: LLM keeps raising → budget exhausted after 2 recoveries.

    Simulates a provider that never recovers (e.g. a permanent 500 or a
    persistent rate-limit that outlasts the retry budget).  With the default
    budget of 2, two recoveries are attempted; on the third failure the loop
    emits ``recovery_exhausted`` + ``run_failed`` and re-raises.

    Returns:
        bool: True when the expected exhaustion events are present.
    """
    print(_colour("\n── Scenario B: budget exhaustion (all calls fail) ──", _CYAN))
    print(
        _DIM
        + textwrap.dedent("""\
        LLM always raises RuntimeError('persistent failure').
        RecoveryPolicy classifies it as LLM_RECOVERABLE.
        The default budget is 2, so two recoveries are attempted.
        On the third failure recovery_exhausted + run_failed are emitted.
        """)
        + _RESET
    )

    agent = SloAgent(
        llm=_make_always_fail_llm(
            failure=RuntimeError("persistent provider failure — simulated"),
        ),
        tools=[],
    )

    events: list[AgentStreamEventDAO] = []
    raised: list[Exception] = []
    try:
        async for event in agent.invoke(
            query="What is 2 + 2?",
            iteration_recovery_policy=_policy,
        ):
            _print_event(event)
            events.append(event)
    except Exception as exc:
        raised.append(exc)
        print(f"  {_DIM}(exception re-raised: {type(exc).__name__}: {exc}){_RESET}")

    kinds = [e.kind for e in events]
    recovery_started_count = sum(1 for k in kinds if k == "recovery_started")
    ok = (
        recovery_started_count == 2  # budget=2 → two attempts
        and "recovery_exhausted" in kinds
        and "run_failed" in kinds
        and len(raised) == 1
    )
    if ok:
        print(
            _colour(
                f"  ✓ {recovery_started_count}× recovery_started + recovery_exhausted + run_failed — PASS",
                _GREEN,
            )
        )
    else:
        print(
            _colour(
                f"  ✗ got: {recovery_started_count}× recovery_started, "
                f"exhausted={'recovery_exhausted' in kinds}, "
                f"failed={'run_failed' in kinds}, "
                f"raised={len(raised)}",
                _RED,
            )
        )
    return ok


# ── scenario C: no policy (legacy) ───────────────────────────────────────────


async def run_scenario_no_policy() -> bool:
    """Scenario C: no recovery policy — legacy fail-fast behavior preserved.

    Without ``iteration_recovery_policy``, the first exception produces
    ``run_failed`` and re-raises immediately, with no recovery events.

    Returns:
        bool: True when the expected legacy behavior is observed.
    """
    print(_colour("\n── Scenario C: no recovery policy (legacy fail-fast) ──", _CYAN))
    print(
        _DIM
        + textwrap.dedent("""\
        No iteration_recovery_policy injected.
        LLM raises RuntimeError on the first call.
        Expected: run_failed + re-raise, NO recovery_started.
        """)
        + _RESET
    )

    agent = SloAgent(
        llm=_make_always_fail_llm(
            failure=RuntimeError("provider error — simulated"),
        ),
        tools=[],
    )

    events: list[AgentStreamEventDAO] = []
    raised: list[Exception] = []
    try:
        async for event in agent.invoke(query="Hello?"):  # no policy
            _print_event(event)
            events.append(event)
    except Exception as exc:
        raised.append(exc)
        print(f"  {_DIM}(exception re-raised: {type(exc).__name__}: {exc}){_RESET}")

    kinds = {e.kind for e in events}
    ok = (
        "recovery_started" not in kinds
        and "run_failed" in kinds
        and len(raised) == 1
    )
    if ok:
        print(_colour("  ✓ no recovery_started, run_failed + re-raise — PASS", _GREEN))
    else:
        print(
            _colour(
                f"  ✗ unexpected: recovery_started={'recovery_started' in kinds}, "
                f"run_failed={'run_failed' in kinds}, raised={len(raised)}",
                _RED,
            )
        )
    return ok


# ── sub-agent note ────────────────────────────────────────────────────────────


def _print_sub_agent_note() -> None:
    """Print an explanation of why sub-agent timeouts do not trigger recovery."""
    print(
        _colour("\n── Why sub-agent timeouts do NOT trigger Feature 50 recovery ──", _YELLOW)
    )
    print(
        textwrap.dedent("""\

        When a spawned sub-agent is silent for CHILD_INACTIVITY_TIMEOUT_SECONDS
        (currently 3600 s), this chain runs:

          _pump_stdout                  → raises TimeoutError
          SubAgentProcess.run()         → CATCHES it → SubAgentResultDAO(status="failed")
          spawn_sub_agents tool         → returns JSON {"failed_task_ids": [...]}
          ToolExecutor._invoke_one()    → also catches all tool exceptions
                                          → ToolMessage(status="error")

        The timeout is absorbed as a FAILED TOOL RESULT, not an exception.
        The parent LLM sees the failed result and reasons about it normally.
        Feature 50 recovery_started is never emitted.

        To trigger recovery you need the LLM PROVIDER CALL itself to raise:
          • 429 rate-limit from Anthropic/OpenAI
          • 500/502/503/529 transient server error
          • 402 credit exhaustion
          • Context overflow on the initial attempt

        To simulate the real inactivity-timeout code path without waiting 3600 seconds:
          1. Set SLO_SUBAGENT_INACTIVITY_TIMEOUT=5 (or any short value)
          2. Spawn sub-agents that run: bash("sleep 10")
          3. Sub-agents will be killed after 5 s and return failed results
          4. The PARENT LLM will handle the failures via normal reasoning
          5. Feature 50 recovery_started is still NOT emitted (correct behavior)
        """)
    )


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> int:
    """Run all validation scenarios and print a summary.

    Returns:
        int: Exit code — 0 on all pass, 1 on any failure.
    """
    exhaust_mode: bool = "--exhaust" in sys.argv

    print(_colour("Feature 50 — LLM Recovery Validation", _CYAN))
    print(_colour("=" * 50, _DIM))

    results: list[bool] = []

    results.append(await run_scenario_single_recovery())

    if exhaust_mode:
        results.append(await run_scenario_budget_exhaustion())
    else:
        print(
            _DIM
            + "\n  (skip budget-exhaustion scenario; pass --exhaust to run it)"
            + _RESET
        )

    results.append(await run_scenario_no_policy())

    _print_sub_agent_note()

    passed = sum(results)
    total = len(results)
    print(_colour(f"\n{'─' * 50}", _DIM))
    if passed == total:
        print(_colour(f"✓ All {total} scenarios passed.", _GREEN))
    else:
        print(_colour(f"✗ {total - passed}/{total} scenarios FAILED.", _RED))

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
