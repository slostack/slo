"""Exact resume wire bounds are checked independently of private schema validation."""

from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.dao import HerdrRestoreReferenceDAO, HerdrSavedRestoreDAO
from tests.agents.slo_agent.herdr.test_reporter import publication, reporter
from src.agents.slo_agent.herdr.reporter import HerdrReporter


@pytest.mark.parametrize("count", [64, 65])
def test_resume_argument_count_boundary(count: int) -> None:
    """Count the launcher itself in the inclusive 64-argument wire limit."""
    argv = ("slo",) + ("x",) * (count - 1)
    assert len(argv) == count
    assert HerdrReporter._resume_argv_is_safe(argv=argv) is (count == 64)


@pytest.mark.parametrize("size", [8192, 8193])
@pytest.mark.parametrize("multibyte", [False, True])
def test_resume_encoded_byte_boundary(size: int, multibyte: bool) -> None:
    """Measure UTF-8 bytes including separators, not Python character count."""
    payload_size = size - len("slo ")
    payload = "é" * (payload_size // 2) + "x" * (payload_size % 2) if multibyte else "x" * payload_size
    argv = ("slo", payload)
    assert len(" ".join(argv).encode("utf-8")) == size
    assert HerdrReporter._resume_argv_is_safe(argv=argv) is (size == 8192)


@pytest.mark.parametrize(
    "reference",
    ["r1-" + "a" * 32, "x" * 8192, "bad'quote", "bad\ncontrol"],
    ids=["valid", "oversize", "apostrophe", "control"],
)
async def test_resume_builder_rejects_unsafe_wire(
    tmp_path: Path,
    reference: str,
) -> None:
    """Defense at the builder never advertises overlong or unsafe opaque values."""
    owner = reporter(root=tmp_path)
    facts = publication(eligible=True)
    owner.publish(publication=facts)
    assert facts.restore_capture is not None
    # Bypass schema only to exercise the independently required argv boundary.
    saved = HerdrSavedRestoreDAO(
        configuration_generation=0,
        capture=facts.restore_capture,
        reference=HerdrRestoreReferenceDAO.model_construct(restore_reference=reference),
    )
    owner._saved = saved
    owner._resume_available = True
    argv = owner._build_resume_argv(publication=facts, saved=saved)
    if reference.startswith("r1-"):
        assert argv == ("slo", "--resume", facts.snapshot.session_id, "--herdr-restore", reference)
        assert len(argv) <= 64
        assert len(" ".join(argv).encode("utf-8")) <= 8192
    else:
        assert argv == ()
