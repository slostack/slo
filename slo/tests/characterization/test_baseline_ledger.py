"""Approval-policy characterization for the immutable Slo baseline ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.characterization.baseline_contract import (
    BaselineCaseDAO,
    BaselineComparator,
    BaselineLedgerDAO,
)
from tests.characterization.normalizers import normalize_baseline_capture

_BASELINE_ROOT: Path = Path("tests/fixtures/79_tui_v2/baseline")
_LEDGER_PATH: Path = _BASELINE_ROOT / "baseline-ledger.json"


def test_only_release_documentation_maintainer_can_approve_deviation() -> None:
    """Reject ledger deviations without the sole editor role and a removal condition.

    WHAT: Loads the committed no-deviation ledger and proves malformed approval
        records fail before they could authorize a fixture change.
    WHO: b.2's baseline gate and future fixture editors rely on this policy test.
    WHEN: Runs whenever the baseline characterization module is verified.
    """
    expected: bytes = _LEDGER_PATH.read_bytes()
    observed: bytes = normalize_baseline_capture(
        capture=expected,
        case_id="baseline-ledger-policy",
    )
    case: BaselineCaseDAO = BaselineCaseDAO(
        case_id="baseline-ledger-policy",
        artifact_path="tests/fixtures/79_tui_v2/baseline/baseline-ledger.json",
        normalizer_version="v1",
    )
    ledger: BaselineLedgerDAO = BaselineComparator.load_ledger(ledger_path=_LEDGER_PATH)
    BaselineComparator.compare(case=case, observed=observed, expected=expected, ledger=ledger)

    invalid_role: dict[str, object] = {
        "entries": [
            {
                "case_id": "cli-bare-workdir-resume-subcommand",
                "artifact_path": "tests/fixtures/79_tui_v2/baseline/cli/bare_workdir_resume_subcommand.json",
                "normalizer_version": "v1",
                "approved_by_role": "test automation",
                "approved_at": "2026-09-16",
                "rationale": "not permitted",
                "allowed_json_pointer_differences": ["/result"],
                "removal_condition": "replace after review",
            }
        ]
    }
    missing_removal_condition: dict[str, object] = {
        "entries": [
            {
                "case_id": "cli-bare-workdir-resume-subcommand",
                "artifact_path": "tests/fixtures/79_tui_v2/baseline/cli/bare_workdir_resume_subcommand.json",
                "normalizer_version": "v1",
                "approved_by_role": "Slo release/documentation maintainer",
                "approved_at": "2026-09-16",
                "rationale": "not permitted without expiry",
                "allowed_json_pointer_differences": ["/result"],
                "removal_condition": "",
            }
        ]
    }

    with pytest.raises(ValidationError):
        BaselineLedgerDAO.model_validate(invalid_role)
    with pytest.raises(ValidationError):
        BaselineLedgerDAO.model_validate(missing_removal_condition)

    invalid_approval_ledger: BaselineLedgerDAO = BaselineLedgerDAO.model_validate(
        {
            "entries": [
                {
                    "case_id": "cli-bare-workdir-resume-subcommand",
                    "artifact_path": "wrong.json",
                    "normalizer_version": "v1",
                    "approved_by_role": "Slo release/documentation maintainer",
                    "approved_at": "2026-09-16",
                    "rationale": "wrong fixture must not authorize",
                    "allowed_json_pointer_differences": ["/result"],
                    "removal_condition": "remove after a reviewed fixture update",
                }
            ]
        }
    )
    changed: bytes = json.dumps({"changed": True}).encode("utf-8")
    with pytest.raises(AssertionError, match="artifact_path"):
        BaselineComparator.compare(
            case=BaselineCaseDAO(
                case_id="cli-bare-workdir-resume-subcommand",
                artifact_path="tests/fixtures/79_tui_v2/baseline/cli/bare_workdir_resume_subcommand.json",
                normalizer_version="v1",
            ),
            observed=changed,
            expected=b'{"changed": false}',
            ledger=invalid_approval_ledger,
        )


def test_comparator_allows_only_approved_json_pointer_leaf_differences() -> None:
    """Allow an approved array leaf and reject every unapproved neighboring value.

    WHAT: Exercises the comparator's only deviation mechanism with an exact
        release-maintainer approval and a pointer into a nested JSON array.
    WHO: Future baseline editors rely on this to understand the ledger's narrow
        review boundary.
    WHEN: Alongside the editor-role policy test before baseline review readiness.
    """
    case: BaselineCaseDAO = BaselineCaseDAO(
        case_id="approved-array-leaf",
        artifact_path="tests/fixtures/79_tui_v2/baseline/example.json",
        normalizer_version="v1",
    )
    ledger: BaselineLedgerDAO = BaselineLedgerDAO.model_validate(
        {
            "entries": [
                {
                    "case_id": case.case_id,
                    "artifact_path": case.artifact_path,
                    "normalizer_version": case.normalizer_version,
                    "approved_by_role": "Slo release/documentation maintainer",
                    "approved_at": "2026-09-18",
                    "rationale": "Reviewed visible frame row variation.",
                    "allowed_json_pointer_differences": ["/frame/1"],
                    "removal_condition": "Remove after the replacement renderer is certified.",
                }
            ]
        }
    )
    expected: bytes = normalize_baseline_capture(
        capture=b'{"frame":["first","before"],"kind":"capture"}',
        case_id=case.case_id,
    )
    approved_observed: bytes = normalize_baseline_capture(
        capture=b'{"frame":["first","after"],"kind":"capture"}',
        case_id=case.case_id,
    )
    BaselineComparator.compare(
        case=case,
        observed=approved_observed,
        expected=expected,
        ledger=ledger,
    )

    unapproved_observed: bytes = normalize_baseline_capture(
        capture=b'{"frame":["first","after"],"kind":"changed"}',
        case_id=case.case_id,
    )
    with pytest.raises(AssertionError, match="exceeds ledger approval"):
        BaselineComparator.compare(
            case=case,
            observed=unapproved_observed,
            expected=expected,
            ledger=ledger,
        )


def test_jsonl_artifact_when_ledger_entry_exists_remains_byte_equal() -> None:
    """Reject JSON-pointer ledger deviations for JSONL baseline artifacts.

    WHAT: Proves a ledger entry cannot bypass byte equality for ordered headless
        JSONL records.
    WHO: The b.2 headless baseline relies on this policy boundary.
    WHEN: Whenever baseline-ledger behavior is verified.
    """
    case: BaselineCaseDAO = BaselineCaseDAO(
        case_id="headless-jsonl-abort-preflight-bypassed",
        artifact_path="tests/fixtures/79_tui_v2/baseline/headless/jsonl_abort_preflight_bypassed.jsonl",
        normalizer_version="v1",
    )
    ledger: BaselineLedgerDAO = BaselineLedgerDAO.model_validate(
        {
            "entries": [
                {
                    "case_id": case.case_id,
                    "artifact_path": case.artifact_path,
                    "normalizer_version": case.normalizer_version,
                    "approved_by_role": "Slo release/documentation maintainer",
                    "approved_at": "2026-09-18",
                    "rationale": "JSONL order must remain exact.",
                    "allowed_json_pointer_differences": ["/kind"],
                    "removal_condition": "Remove after fixture review.",
                }
            ]
        }
    )
    expected: bytes = normalize_baseline_capture(
        capture=b'{"kind":"preflight_bypassed"}\n{"kind":"run_aborted"}\n',
        case_id=case.case_id,
    )
    observed: bytes = normalize_baseline_capture(
        capture=b'{"kind":"preflight_bypassed"}\n{"kind":"run_failed"}\n',
        case_id=case.case_id,
    )

    with pytest.raises(AssertionError, match="JSON artifact"):
        BaselineComparator.compare(case=case, observed=observed, expected=expected, ledger=ledger)
