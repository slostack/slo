"""Explicit b.2 parity adapter scaffold; it intentionally makes no rich-parity claim."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["SlotuiParityMatrix", "SlotuiParityMatrixEntryDAO"]


class SlotuiParityMatrixEntryDAO(BaseModel):
    """Map one characterized Slo surface to a future narrow integration adapter boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_case: str
    adapter_boundary: str
    status: Literal["scaffolded", "literal_fallback_only"]
    rich_parity_claimed: bool
    non_goals: tuple[str, ...]


class SlotuiParityMatrix(BaseModel):
    """Declare b.2 preservation inputs without claiming a Slotui replacement is complete."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[SlotuiParityMatrixEntryDAO, ...]
    rich_parity_claimed: Literal[False]
    allows_literal_raw_fallback: Literal[True]

    @property
    def baseline_cases(self) -> tuple[str, ...]:
        """Return b.2 baseline case identifiers in migration-planning order.

        Returns:
            tuple[str, ...]: Characterized surfaces a future opt-in adapter must preserve.
        """
        return tuple(entry.baseline_case for entry in self.entries)

    @classmethod
    def build(cls) -> "SlotuiParityMatrix":
        """Build Slo's explicit non-rich parity planning contract.

        Returns:
            SlotuiParityMatrix: Immutable baseline-to-adapter map for later independently verified work.
        """
        return cls(
            entries=(
                SlotuiParityMatrixEntryDAO(
                    baseline_case="bare_cli_workdir_resume",
                    adapter_boundary="interactive selector preserves current workdir and resume facts",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("default switch", "Textual removal"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="headless_separation",
                    adapter_boundary="headless runner remains outside interactive selector",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("headless renderer", "implicit presentation switch"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="editor_queue_copy",
                    adapter_boundary="future editor, latest-wins queue, and Slo clipboard relay ports",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("copy UX parity", "terminal frame parity"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="auth_diff_tree_fleet_workflow_overlays",
                    adapter_boundary="future Slo-owned overlay adapters preserve existing policy owners",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("rich overlay parity", "auth policy migration", "workflow policy migration"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="session_history_replay_slash",
                    adapter_boundary="future session/history/replay/slash relays use verified core capability exports",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("history ownership transfer", "slash policy replacement"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="literal_raw_fallback_images_latex_mermaid",
                    adapter_boundary="literal/raw fallback boundary for unsupported rich content",
                    status="literal_fallback_only",
                    rich_parity_claimed=False,
                    non_goals=(
                        "image rendering",
                        "LaTex rendering",
                        "Mermaid rendering",
                        "rich-content parity",
                    ),
                ),
            ),
            rich_parity_claimed=False,
            allows_literal_raw_fallback=True,
        )
