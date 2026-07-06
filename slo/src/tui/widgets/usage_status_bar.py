"""Persistent usage and limits surface for the Slo TUI."""

from __future__ import annotations

from textual.widgets import Static

from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO

__all__ = ["UsageStatusBar"]


class UsageStatusBar(Static):
    """Render persistent model, usage, and limits state above the footer."""

    DEFAULT_CSS = """
    UsageStatusBar {
        width: 100%;
        height: auto;
        color: $text-muted;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    """

    def update_snapshot(self, *, snapshot: SessionUsageSnapshotDAO) -> None:
        """Render the provided runtime snapshot.

        Args:
            snapshot (SessionUsageSnapshotDAO): Session-owned usage snapshot.
        """
        self.update(self._render_snapshot(snapshot=snapshot))

    @classmethod
    def _render_snapshot(cls, *, snapshot: SessionUsageSnapshotDAO) -> str:
        """Return the visible usage-bar line for one snapshot.

        Args:
            snapshot (SessionUsageSnapshotDAO): Session-owned usage snapshot.

        Returns:
            str: Human-readable usage and limits line.
        """
        return (
            f"{snapshot.active_model_name}"
            f" · reasoning {snapshot.active_reasoning_level}"
            f" · {cls._usage_text(snapshot=snapshot)}"
            f" · {cls._limits_text(snapshot=snapshot)}"
        )

    @classmethod
    def _usage_text(cls, *, snapshot: SessionUsageSnapshotDAO) -> str:
        """Return the usage portion of the status line.

        Args:
            snapshot (SessionUsageSnapshotDAO): Session-owned usage snapshot.

        Returns:
            str: Usage text segment.
        """
        if not snapshot.usage_available:
            return "usage unavailable"
        base: str = (
            f"turn {snapshot.latest_turn.total_tokens or '?'} tok"
            f" · session {snapshot.session_totals.total_tokens or '?'} tok"
        )
        cache_parts: list[str] = cls._cache_text_parts(totals=snapshot.session_totals)
        if not cache_parts:
            return base
        return base + " · " + " · ".join(cache_parts)

    @staticmethod
    def _cache_text_parts(*, totals: TokenUsageTotalsDAO) -> list[str]:
        """Return rendered cache-token segments when present.

        Args:
            totals (TokenUsageTotalsDAO): Session totals DAO carrying optional
                cache counts.

        Returns:
            list[str]: Zero, one, or two cache label strings.
        """
        parts: list[str] = []
        if totals.cache_creation_input_tokens is not None:
            parts.append(f"cache write {totals.cache_creation_input_tokens}")
        if totals.cache_read_input_tokens is not None:
            parts.append(f"cache read {totals.cache_read_input_tokens}")
        return parts

    @classmethod
    def _limits_text(cls, *, snapshot: SessionUsageSnapshotDAO) -> str:
        """Return the model-limit portion of the status line.

        Args:
            snapshot (SessionUsageSnapshotDAO): Session-owned usage snapshot.

        Returns:
            str: Limits text segment.
        """
        limit_bits: list[str] = []
        cls._append_limit_if_known(
            limit_bits=limit_bits,
            value=snapshot.output_cap_tokens,
            label="out",
        )
        cls._append_text_limit_if_known(
            limit_bits=limit_bits,
            value=snapshot.provider_effort,
            label="effort",
        )
        cls._append_limit_if_known(
            limit_bits=limit_bits,
            value=snapshot.provider_budget_tokens,
            label="budget",
        )
        cls._append_limit_if_known(
            limit_bits=limit_bits,
            value=snapshot.tokens_per_minute_limit,
            label="tpm",
        )
        cls._append_limit_if_known(
            limit_bits=limit_bits,
            value=snapshot.requests_per_minute_limit,
            label="rpm",
        )
        cls._append_cooldown_if_known(
            limit_bits=limit_bits,
            cooldown_seconds_remaining=snapshot.cooldown_seconds_remaining,
        )
        return " · ".join(limit_bits) or "limits unknown"

    @staticmethod
    def _append_limit_if_known(*, limit_bits: list[str], value: int | None, label: str) -> None:
        """Append one numeric limit label when a value is known.

        Args:
            limit_bits (list[str]): Mutable list of rendered limit strings.
            value (int | None): Numeric value to append.
            label (str): Display label.
        """
        if value is None:
            return
        limit_bits.append(f"{label} {value}")

    @staticmethod
    def _append_text_limit_if_known(*, limit_bits: list[str], value: str | None, label: str) -> None:
        """Append one text-valued limit label when a value is known.

        Args:
            limit_bits (list[str]): Mutable list of rendered limit strings.
            value (str | None): Text value to append.
            label (str): Display label.
        """
        if value is None:
            return
        limit_bits.append(f"{label} {value}")

    @staticmethod
    def _append_cooldown_if_known(*, limit_bits: list[str], cooldown_seconds_remaining: int | None) -> None:
        """Append cooldown copy when a retry wait is active.

        Args:
            limit_bits (list[str]): Mutable list of rendered limit strings.
            cooldown_seconds_remaining (int | None): Seconds until the next retry.
        """
        if cooldown_seconds_remaining is None:
            return
        limit_bits.append(f"retry in {cooldown_seconds_remaining}s")
