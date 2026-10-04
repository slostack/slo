"""Contract tests for the finite synthetic OpenRouter fixture bundle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.auth.provider_for_model import provider_for_model
from src.auth.credential_dao import ProviderName

_FIXTURE_DIRECTORY: Path = Path(__file__).resolve().parents[2] / "fixtures" / "openrouter"
_FORBIDDEN_TEXT: tuple[str, ...] = (
    "authorization",
    "bearer ",
    "sk-or-",
    "live response",
    "observed live",
)


def _fixture_path(*, name: str) -> Path:
    """Return one checked-in fixture path below the immutable fixture directory.

    Args:
        name (str): Basename of the expected fixture artifact.

    Returns:
        Path: Resolved fixture path confined to the fixture directory.
    """
    directory: Path = _FIXTURE_DIRECTORY.resolve()
    path: Path = (directory / name).resolve()
    assert path.is_relative_to(directory)
    return path


def _load_json_fixture(*, name: str) -> dict[str, object]:
    """Load one object-shaped synthetic fixture without writing any runtime file.

    Args:
        name (str): Basename of the expected JSON fixture.

    Returns:
        dict[str, object]: Decoded fixture object.
    """
    payload: object = json.loads(_fixture_path(name=name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_fixture_bundle_when_read_validates_synthetic_contract_shapes() -> None:
    """Keep required representative fixture shapes parseable and route-safe."""
    key: dict[str, object] = _load_json_fixture(name="key-valid.json")
    models: dict[str, object] = _load_json_fixture(name="models-user-page.json")
    errors: dict[str, object] = _load_json_fixture(name="errors.json")
    private_anchor: dict[str, object] = _load_json_fixture(name="private-anchor.json")
    sse: str = _fixture_path(name="chat-completions-tool.sse").read_text(encoding="utf-8")

    assert key == {"data": {}}
    assert isinstance(models["data"], list) and models["data"]
    model: object = models["data"][0]
    assert isinstance(model, dict)
    assert model["id"] == "vendor/fixture-coder"
    assert errors["authentication"] == {"status": 401, "error": {"code": "authentication_error"}}
    assert "call_fixture" in sse and sse.endswith("data: [DONE]\n\n")
    assert private_anchor["source_model_name"] == "openrouter:vendor/fixture-coder"
    assert provider_for_model(model_name=str(private_anchor["source_model_name"])) is ProviderName.OPENROUTER


@pytest.mark.parametrize(
    "name",
    [
        "key-valid.json",
        "models-user-page.json",
        "errors.json",
        "chat-completions-tool.sse",
        "private-anchor.json",
    ],
)
def test_fixture_bundle_when_read_contains_no_claimed_live_or_secret_material(name: str) -> None:
    """Reject accidental secret-like material or untruthful live-evidence claims."""
    content: str = _fixture_path(name=name).read_text(encoding="utf-8").casefold()

    for forbidden in _FORBIDDEN_TEXT:
        assert forbidden not in content
