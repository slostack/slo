"""Pure identity extraction and ordinary CLI compatibility contracts."""

import pytest

from src.agents.slo_agent.sessions import identity
from src.cli import headless_request

UUID_TEXT = "12345678-1234-1234-9234-123456789abc"


@pytest.mark.parametrize(
    "value,expected",
    [
        (UUID_TEXT, UUID_TEXT),
        (UUID_TEXT.upper(), UUID_TEXT),
        (UUID_TEXT.replace("-", ""), UUID_TEXT),
        ("{" + UUID_TEXT + "}", UUID_TEXT),
        ("urn:uuid:" + UUID_TEXT, UUID_TEXT),
        (" My-task_1.2 ", "My-task_1.2"),
        (".", "."),
        ("  " + UUID_TEXT + "  ", UUID_TEXT),
    ],
)
def test_normalization_is_shared(value: str, expected: str) -> None:
    """CLI compatibility uses the lower-layer validator, including non-v4 UUIDs."""
    assert headless_request.validate_session_id is identity.validate_session_id
    assert identity.validate_session_id(value=value) == expected
    assert headless_request.HeadlessRunRequestDAO(prompt="test", session_id=value).session_id == expected


@pytest.mark.parametrize(
    "value,message",
    [
        ("", "must not be empty"),
        ("  ", "must not be empty"),
        ("a/b", "path separators"),
        ("a\\b", "path separators"),
        ("a..b", "traversal component"),
        ("a b", "must be a UUID4"),
        ("é", "must be a UUID4"),
        ("a\x00b", "must be a UUID4"),
    ],
)
def test_rejections_are_preserved(value: str, message: str) -> None:
    """Extraction preserves existing errors, including path guards before parsing."""
    with pytest.raises(ValueError, match=message):
        identity.validate_session_id(value=value)


def test_validator_closure_is_not_owned_by_cli() -> None:
    """No private parser, regex or UUID dependency remains in the CLI owner."""
    for name in (
        "_try_parse_uuid",
        "_reject_path_components",
        "_normalise_to_slug_or_uuid",
        "_SESSION_ID_SLUG_RE",
        "UUID",
    ):
        assert hasattr(identity, name)
        assert not hasattr(headless_request, name)


@pytest.mark.parametrize(
    "value,expected",
    [
        (UUID_TEXT, True),
        ("00000000-0000-0000-0000-000000000000", True),
        (UUID_TEXT.upper(), False),
        (UUID_TEXT.replace("-", ""), False),
        ("{" + UUID_TEXT + "}", False),
        ("urn:uuid:" + UUID_TEXT, False),
        (" " + UUID_TEXT, False),
        (UUID_TEXT + "\n", False),
        ("my-run.1", False),
        ("", False),
        ("../private", False),
        ("secret\x00", False),
    ],
)
def test_canonical_gate_does_not_normalize(value: str, expected: bool) -> None:
    """Herdr accepts exact UUID spelling only without tightening ordinary resume."""
    assert identity.is_canonical_uuid_session_id(value=value) is expected
