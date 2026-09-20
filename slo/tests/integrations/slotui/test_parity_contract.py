"""Tests for the explicit non-rich Slotui parity scaffolding contract."""

from __future__ import annotations

from src.integrations.slotui.parity import SlotuiParityMatrix


def test_build_matrix_declares_every_characterized_baseline_surface() -> None:
    """Map b.2 baseline areas to adapters or intentional non-claims without rich parity."""
    matrix = SlotuiParityMatrix.build()

    assert matrix.baseline_cases == (
        "bare_cli_workdir_resume",
        "headless_separation",
        "editor_queue_copy",
        "auth_diff_tree_fleet_workflow_overlays",
        "session_history_replay_slash",
        "literal_raw_fallback_images_latex_mermaid",
    )
    assert matrix.rich_parity_claimed is False
    assert matrix.allows_literal_raw_fallback is True


def test_build_matrix_expressly_marks_overlay_and_rich_content_as_future_adapter_work() -> None:
    """Keep fixtures honest: b.2 characterization is an input contract, not delivery evidence."""
    matrix = SlotuiParityMatrix.build()
    by_case = {entry.baseline_case: entry for entry in matrix.entries}

    assert by_case["auth_diff_tree_fleet_workflow_overlays"].status == "scaffolded"
    assert by_case["auth_diff_tree_fleet_workflow_overlays"].rich_parity_claimed is False
    assert by_case["literal_raw_fallback_images_latex_mermaid"].status == "literal_fallback_only"
    assert by_case["literal_raw_fallback_images_latex_mermaid"].rich_parity_claimed is False
    assert "Mermaid rendering" in by_case["literal_raw_fallback_images_latex_mermaid"].non_goals
