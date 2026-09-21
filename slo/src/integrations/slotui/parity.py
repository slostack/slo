"""Honest Slotui parity planning matrix; no candidate implementation evidence is implied."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["SlotuiParityMatrix", "SlotuiParityMatrixEntryDAO"]


class SlotuiParityMatrixEntryDAO(BaseModel):
    """Map a characterized surface to a future adapter boundary or explicit limitation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_case: str
    adapter_boundary: str
    status: Literal["candidate_gated", "scaffolded", "literal_fallback_only"]
    rich_parity_claimed: bool
    non_goals: tuple[str, ...]


class SlotuiParityMatrix(BaseModel):
    """Declare preservation inputs without claiming Slotui behavior is delivered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[SlotuiParityMatrixEntryDAO, ...]
    rich_parity_claimed: Literal[False]
    allows_literal_raw_fallback: Literal[True]

    @property
    def baseline_cases(self) -> tuple[str, ...]:
        """Return b.2 baseline case identifiers in planning order.

        Returns:
            tuple[str, ...]: Surface identifiers retained for future candidate proof.
        """
        return tuple(entry.baseline_case for entry in self.entries)

    @classmethod
    def build(cls) -> "SlotuiParityMatrix":
        """Build the explicit non-parity matrix.

        Returns:
            SlotuiParityMatrix: Candidate-gated integration boundaries and non-goals.
        """
        return cls(
            entries=(
                SlotuiParityMatrixEntryDAO(
                    baseline_case="bare_cli_workdir_resume",
                    adapter_boundary="v2 control launch carries resolved workdir/resume facts to candidate adapter",
                    status="candidate_gated",
                    rich_parity_claimed=False,
                    non_goals=("default switch", "Textual removal", "resume parity proof"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="headless_separation",
                    adapter_boundary="headless runner remains outside interactive selection",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("headless renderer", "implicit presentation switch"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="editor_queue_copy",
                    adapter_boundary="candidate adapter receives editor events over v2 control socket",
                    status="candidate_gated",
                    rich_parity_claimed=False,
                    non_goals=("editor queue", "latest-wins policy", "copy UX parity"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="auth_diff_tree_fleet_workflow_overlays",
                    adapter_boundary="future Slo-owned overlays only after separate candidate proof",
                    status="scaffolded",
                    rich_parity_claimed=False,
                    non_goals=("rich overlays", "auth", "diff", "fleet", "workflow parity"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="session_history_replay_slash",
                    adapter_boundary="parent event mapping preserves metadata on candidate control protocol",
                    status="candidate_gated",
                    rich_parity_claimed=False,
                    non_goals=("history", "replay", "slash", "session parity"),
                ),
                SlotuiParityMatrixEntryDAO(
                    baseline_case="literal_raw_fallback_images_latex_mermaid",
                    adapter_boundary="literal/raw fallback status only",
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
