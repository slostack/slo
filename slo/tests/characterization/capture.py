"""Shared sensitive-free serialization helpers for b.2 characterization tests."""

from __future__ import annotations

import json

__all__ = ["baseline_case", "canonical_json_bytes", "loaded_baseline_ledger"]

from tests.characterization.baseline_contract import BaselineCaseDAO, BaselineComparator, BaselineLedgerDAO

_BASELINE_ROOT: str = "tests/fixtures/79_tui_v2/baseline"


def baseline_case(*, case_id: str, artifact_relative_path: str) -> BaselineCaseDAO:
    """Build one exact v1 fixture contract.

    WHAT: Couples a named behavior capture to its one committed fixture path.
    WHO: Every b.2 exercise test creates its comparator input through this helper.
    WHEN: Immediately before it directly normalizes and compares a capture.

    Args:
        case_id (str): Stable baseline capture identifier.
        artifact_relative_path (str): Path below the b.2 baseline fixture root.

    Returns:
        BaselineCaseDAO: Exact immutable case metadata.
    """
    return BaselineCaseDAO(
        case_id=case_id,
        artifact_path=f"{_BASELINE_ROOT}/{artifact_relative_path}",
        normalizer_version="v1",
    )


def canonical_json_bytes(*, value: object) -> bytes:
    """Serialize JSON-compatible capture data into stable fixture bytes.

    WHAT: Uses sorted, indented, newline-terminated JSON without changing any
        captured field or value.
    WHO: b.2 JSON fixture exercises use this immediately before normalizing.
    WHEN: After a real or deterministic-fake boundary returns its capture.

    Args:
        value (object): JSON-compatible captured behavior.

    Returns:
        bytes: Deterministically encoded UTF-8 JSON.
    """
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def loaded_baseline_ledger() -> BaselineLedgerDAO:
    """Load the exact b.2 baseline ledger fixture.

    WHAT: Centralizes only ledger location, not capture normalization or comparison.
    WHO: Each b.2 test supplies the result to BaselineComparator.compare.
    WHEN: After the test directly calls normalize_baseline_capture.

    Returns:
        BaselineLedgerDAO: Validated committed deviation ledger.
    """
    from pathlib import Path

    return BaselineComparator.load_ledger(ledger_path=Path(_BASELINE_ROOT) / "baseline-ledger.json")
