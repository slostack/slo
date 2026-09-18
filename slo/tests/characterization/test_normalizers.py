"""Unit coverage for the b.2 capture normalizer's deliberately narrow scope."""

from __future__ import annotations

from tests.characterization.normalizers import normalize_baseline_capture


def test_normalize_baseline_capture_when_pytest_temp_root_replaces_only_volatile_root() -> None:
    """Replace a pytest-created temporary root while preserving its captured suffix."""
    observed: bytes = normalize_baseline_capture(
        capture=b'{"path":"/tmp/pytest-of-agent/pytest-7/test_case0/effects.jsonl"}',
        case_id="normalizer-temp-root",
    )

    assert observed == b'{"path":"<TEMP_ROOT>"}'


def test_normalize_baseline_capture_when_arbitrary_tmp_path_preserves_semantic_path() -> None:
    """Preserve arbitrary /tmp paths because they are not proven pytest temp roots."""
    capture: bytes = b'{"path":"/tmp/customer-imports/semantic-output.json"}'

    observed: bytes = normalize_baseline_capture(capture=capture, case_id="normalizer-temp-root")

    assert observed == capture
