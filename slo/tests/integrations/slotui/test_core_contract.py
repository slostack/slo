"""Tests for Slo's fail-closed, wheel-only Slotui core consumer contract."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from src.integrations.slotui.dao import (
    REQUIRED_SLOTUI_CAPABILITIES,
    SlotuiCoreArtifactReferenceDAO,
    SlotuiCoreManifestDAO,
)
from src.integrations.slotui.verifier import (
    SlotuiCoreVerificationError,
    SlotuiCoreWheelVerificationService,
)


def test_build_installation_plan_when_typed_fixture_matches_exact_wheel_and_digest(
    tmp_path: Path,
) -> None:
    """Accept only fixture bytes that name the exact local wheel and its digest."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    manifest_bytes: bytes = _manifest_bytes(wheel_path=wheel_path)
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    plan = SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert plan.distribution_name == "slotui"
    assert plan.version == "0.1.0"
    assert plan.wheel_path == wheel_path
    assert plan.argv == (
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--no-deps",
        str(wheel_path),
    )
    assert plan.manifest == SlotuiCoreManifestDAO.model_validate_json(manifest_bytes)
    assert "slotui" not in sys.modules


def test_build_installation_plan_when_manifest_bytes_digest_changes_rejects_before_schema_or_wheel(
    tmp_path: Path,
) -> None:
    """Reject changed typed fixture bytes even when their JSON remains valid."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    manifest_bytes: bytes = _manifest_bytes(wheel_path=wheel_path)
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes + b"\n")
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="manifest SHA-256 does not match"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert "slotui" not in sys.modules


def test_build_installation_plan_when_manifest_schema_omits_core_capability_rejects_closed(
    tmp_path: Path,
) -> None:
    """Reject a digest-valid fixture that cannot declare every required capability."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = json.loads(_manifest_bytes(wheel_path=wheel_path))
    payload["capabilities"] = payload["capabilities"][:-1]  # type: ignore[index]
    manifest_bytes: bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="invalid typed schema"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert "slotui" not in sys.modules


@pytest.mark.parametrize(
    "artifact_source",
    [
        "https://pypi.org/packages/slotui-0.1.0-py3-none-any.whl",
        "git+https://example.invalid/slotui.git",
        "../slo-tui",
        "file:///root/Code/slo-tui",
    ],
)
def test_build_installation_plan_when_artifact_is_not_local_regular_wheel_rejects_source_and_registry_fallbacks(
    tmp_path: Path,
    artifact_source: str,
) -> None:
    """Reject registries, VCS, directories, and source-checkout-shaped artifacts."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = json.loads(_manifest_bytes(wheel_path=wheel_path))
    payload["wheel_artifact"] = {"source": artifact_source}
    manifest_bytes: bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="local wheel artifact"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert "slotui" not in sys.modules


def test_build_installation_plan_when_wheel_name_hash_or_metadata_differs_rejects(tmp_path: Path) -> None:
    """Reject a wheel that is not the manifest's exact distribution artifact."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path, metadata_version="0.1.1")
    manifest_bytes: bytes = _manifest_bytes(wheel_path=wheel_path, declared_version="0.1.0")
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="wheel METADATA version"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert "slotui" not in sys.modules


def test_build_installation_plan_when_wheel_path_is_a_symlink_rejects_path_fallback(
    tmp_path: Path,
) -> None:
    """Reject a symlink even when it points to an otherwise valid local wheel fixture."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    symlink_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    wheel_path.rename(tmp_path / "slotui-target-0.1.0-py3-none-any.whl")
    symlink_path.symlink_to(tmp_path / "slotui-target-0.1.0-py3-none-any.whl")
    payload: dict[str, object] = json.loads(_manifest_bytes(wheel_path=symlink_path))
    payload["wheel_artifact"] = {"source": symlink_path.as_uri()}
    manifest_bytes: bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="regular valid zip wheel"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)


def test_build_installation_plan_when_wheel_is_not_zip_rejects_before_any_slotui_import(
    tmp_path: Path,
) -> None:
    """Reject a regular non-wheel file despite an otherwise matching artifact declaration."""
    wheel_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    wheel_path.write_bytes(b"not a wheel")
    manifest_bytes: bytes = _manifest_bytes(wheel_path=wheel_path)
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="valid zip wheel"):
        SlotuiCoreWheelVerificationService.build_installation_plan(reference=reference)

    assert "slotui" not in sys.modules


def _manifest_bytes(*, wheel_path: Path, declared_version: str = "0.1.0") -> bytes:
    """Build immutable JSON bytes for a typed release-manifest fixture."""
    capability_exports: dict[str, list[str]] = {
        "terminal": ["TerminalDriver"],
        "editor": ["EditorComponent"],
        "events": ["AgentStreamEventDAO"],
        "session": ["AgentSession"],
        "history": ["SessionHistoryEventDAO"],
        "replay": ["TranscriptEntryDAO"],
        "slash": ["SlashRouter"],
        "live_transcript": ["LiveTranscript"],
    }
    payload: dict[str, object] = {
        "schema_version": "slotui-core-release-manifest-v1",
        "distribution_name": "slotui",
        "version": declared_version,
        "wheel_filename": wheel_path.name,
        "wheel_sha256": _sha256(value=wheel_path.read_bytes()),
        "wheel_artifact": {"source": wheel_path.resolve().as_uri()},
        "export_surface": sorted({name for names in capability_exports.values() for name in names}),
        "capabilities": [
            {"name": name, "required_exports": capability_exports[name]}
            for name in REQUIRED_SLOTUI_CAPABILITIES
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_wheel_fixture(*, tmp_path: Path, metadata_version: str = "0.1.0") -> Path:
    """Write a non-importable minimal wheel-shaped zip for consumer verification tests."""
    wheel_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr("slotui/__init__.py", "raise AssertionError('slotui must not be imported')\n")
        archive.writestr(
            "slotui-0.1.0.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: slotui\nVersion: {metadata_version}\n",
        )
        archive.writestr(
            "slotui-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return wheel_path


def _sha256(*, value: bytes) -> str:
    """Return the fixture digest in the release manifest's canonical spelling."""
    return hashlib.sha256(value).hexdigest()
