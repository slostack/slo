"""Tests for local rate-limit policy helpers."""

from __future__ import annotations

from src.agents.slo_agent.rate_limit.service import (
    estimate_request_tokens,
    policy_for_model,
    retry_plan_from_error,
)


class TestRateLimitPolicy:
    """Policy lookup, token estimation, and retry-plan parsing."""

    def test_policy_for_model_reads_configured_limits(self) -> None:
        """Configured model defaults surface as a local rate policy."""
        policy = policy_for_model(model_name="gpt-5.4")

        assert policy.requests_per_minute == 30
        assert policy.tokens_per_minute == 500_000
        assert policy.automatic_retry_attempts == 2

    def test_estimate_request_tokens_adds_prompt_output_and_reasoning_budget(self) -> None:
        """The local estimate includes prompt, output, and reasoning budgets."""
        estimated_tokens: int = estimate_request_tokens(
            prompt_text="abcd" * 20,
            output_cap_tokens=100,
            reasoning_budget_tokens=50,
        )

        assert estimated_tokens == 170

    def test_retry_plan_parses_wait_seconds_from_error_text(self) -> None:
        """Provider retry-after copy becomes a bounded retry plan."""
        plan = retry_plan_from_error(
            model_name="gpt-5.4",
            exc=RuntimeError("Rate limit reached. Please try again in 19.145s."),
            attempt_number=1,
            max_attempts=3,
        )

        assert plan.retryable is True
        assert plan.wait_seconds == 19
        assert "retrying in 19s" in plan.message


# ---------------------------------------------------------------------------
# History-aware estimate (37.a.5)
# ---------------------------------------------------------------------------

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402


class TestEstimateRequestTokensHistoryAware:
    def test_counts_replayed_history(self) -> None:
        """Replayed history materially raises the estimate above the prompt-only value."""
        big = [HumanMessage(content="x" * 4000), AIMessage(content="y" * 4000)]
        prompt_only = estimate_request_tokens(
            prompt_text="hi", output_cap_tokens=8192, reasoning_budget_tokens=None
        )
        est = estimate_request_tokens(
            prompt_text="hi",
            message_history=big,
            output_cap_tokens=8192,
            reasoning_budget_tokens=None,
        )
        assert est > prompt_only
        assert est - prompt_only >= 1900  # ~2000 tokens of replayed history (8000 chars / 4)

    def test_empty_history_matches_prompt_only(self) -> None:
        """An empty tuple and an empty list both equal the prompt-only estimate."""
        a = estimate_request_tokens(
            prompt_text="hello", message_history=(), output_cap_tokens=8192, reasoning_budget_tokens=None
        )
        b = estimate_request_tokens(
            prompt_text="hello", message_history=[], output_cap_tokens=8192, reasoning_budget_tokens=None
        )
        c = estimate_request_tokens(prompt_text="hello", output_cap_tokens=8192, reasoning_budget_tokens=None)
        assert a == b == c

    def test_counts_tool_message_outputs(self) -> None:
        """Tool outputs in history are counted, not skipped."""
        hist = [ToolMessage(content="z" * 8000, name="bash", tool_call_id="t1")]
        est = estimate_request_tokens(
            prompt_text="hi", message_history=hist, output_cap_tokens=0, reasoning_budget_tokens=None
        )
        assert est >= 2000  # ~8000 chars / 4
