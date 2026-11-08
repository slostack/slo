"""Canonical finite JSON and safe failures on their existing policy owners."""

import pytest

from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.sdk.response import NativeResponseAssembly


def test_protocol_failure_has_fixed_payload_free_message() -> None:
    """Callers obtain the same bounded failure without supplying native content."""
    error: ClaudeBridgeError = ClaudeBridgeError.protocol_error()
    assert error.code == "stream_protocol_failed"
    assert str(error) == "Malformed or unfinished Claude response."


def test_canonical_json_preserves_exact_types_and_array_order() -> None:
    """Object order is irrelevant without weakening numeric or sequence identity."""
    assert NativeResponseAssembly.json_identity(value={"b": 2, "a": 1}) == '{"a":1,"b":2}'
    identities: set[str] = {
        NativeResponseAssembly.json_identity(value=value) for value in (True, 1, 1.0, [1, 2], [2, 1])
    }
    assert len(identities) == 5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object()])
def test_invalid_json_never_exposes_payload(value: object) -> None:
    """Nonfinite and non-JSON values fail using the shared safe category."""
    with pytest.raises(ClaudeBridgeError) as failure:
        NativeResponseAssembly.json_identity(value=value)
    assert failure.value.code == "stream_protocol_failed"
    assert str(failure.value) == "Malformed or unfinished Claude response."
