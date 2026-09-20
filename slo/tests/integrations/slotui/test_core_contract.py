"""Tests for Slo's static, fail-closed Slotui adapter-fixture contract."""

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


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    [
        (
            lambda payload: payload.__setitem__("rich_capability_state", "rich_parity"),
            "invalid canonical typed",
        ),
        (lambda payload: payload.__setitem__("requires_python", ""), "invalid canonical typed"),
        (lambda payload: payload["capabilities"].pop(), "invalid canonical typed"),  # type: ignore[index]
        (
            lambda payload: payload.__setitem__(
                "capabilities", payload["capabilities"] + [payload["capabilities"][0]]  # type: ignore[index]
            ),
            "invalid canonical typed",
        ),
        (
            lambda payload: payload["capabilities"][0].__setitem__(  # type: ignore[index]
                "required_exports", ["slotui.terminal.TerminalDriver", "slotui.terminal.TerminalDriver"]
            ),
            "invalid canonical typed",
        ),
    ],
)
def test_build_verification_receipt_when_manifest_contract_is_incomplete_or_non_raw_rejects(
    tmp_path: Path,
    mutation: object,
    error_match: str,
) -> None:
    """Reject each non-generic, incomplete, or duplicate adapter-fixture contract branch."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    mutation(payload)  # type: ignore[operator]
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match=error_match):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert "slotui" not in sys.modules


def test_build_verification_receipt_when_typed_fixture_matches_exact_static_wheel_proves_without_import(
    tmp_path: Path,
) -> None:
    """Accept exact fixture bytes and source declarations without installing or importing Slotui."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert receipt.distribution_name == "slotui"
    assert receipt.version == "0.1.0"
    assert receipt.wheel_path == wheel_path
    assert receipt.manifest == SlotuiCoreManifestDAO.model_validate(_canonical_payload(payload=payload))
    assert not hasattr(receipt, "argv")
    assert "slotui" not in sys.modules


@pytest.mark.parametrize(
    ("wheel_mutation", "error_match"),
    [
        ("missing_symbol", "missing declared export slotui.terminal.TerminalDriver"),
        ("renamed_module", "missing declared module slotui.terminal"),
        ("outside_package", "outside the expected slotui package"),
    ],
)
def test_build_verification_receipt_when_static_export_proof_fails_rejects_without_import(
    tmp_path: Path,
    wheel_mutation: str,
    error_match: str,
) -> None:
    """Reject absent, renamed, or out-of-bound generic exports using archive AST only."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path, mutation=wheel_mutation)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match=error_match):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert "slotui" not in sys.modules


def test_build_verification_receipt_when_export_signature_is_rich_only_rejects(tmp_path: Path) -> None:
    """Reject a rich-only declaration even if matching Python source exists in the fixture wheel."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    signature = payload["immutable_core_export_signature"]  # type: ignore[assignment]
    signature[0]["symbol"] = "RichTerminalDriver"  # type: ignore[index]
    payload["capabilities"][0]["required_exports"] = ["slotui.terminal.RichTerminalDriver"]  # type: ignore[index]
    _finalize_signature_hash(payload=payload)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="invalid canonical typed"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_manifest_projection_hash_is_wrong_rejects_before_wheel(
    tmp_path: Path,
) -> None:
    """Reject a reference-pinned canonical manifest whose non-self hash is stale."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    payload["manifest_sha256"] = "0" * 64
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="projection hash"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_reference_digest_changes_rejects_before_schema_or_wheel(
    tmp_path: Path,
) -> None:
    """Reject changed manifest bytes before their schema or referenced wheel are inspected."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    manifest_path: Path = tmp_path / "slotui-adapter-fixture.json"
    manifest_path.write_bytes(_canonical_json(payload=payload).encode("utf-8") + b"\n")
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=_canonical_json(payload=payload).encode("utf-8")),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="pinned reference"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


@pytest.mark.parametrize(
    "artifact_source",
    [
        "https://pypi.org/packages/slotui-0.1.0-py3-none-any.whl",
        "git+https://example.invalid/slotui.git",
        "../slotui",
        "file:///root/Code/slotui",
    ],
)
def test_build_verification_receipt_when_artifact_is_not_local_regular_wheel_rejects(
    tmp_path: Path,
    artifact_source: str,
) -> None:
    """Reject registry, VCS, relative, and source checkout artifact fallbacks."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    payload["wheel_artifact"] = {"source": artifact_source}
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="local wheel artifact"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def _manifest_payload(*, wheel_path: Path) -> dict[str, object]:
    """Build an Slo-owned canonical adapter fixture, not a Slotui owner schema.

    Args:
        wheel_path (Path): Local, non-importable wheel-shaped archive to pin.

    Returns:
        dict[str, object]: Mutable payload finalized with both required hashes by callers.
    """
    signature: list[dict[str, str]] = [
        {"module": "slotui.terminal", "symbol": "TerminalDriver"},
        {"module": "slotui.editor", "symbol": "EditorComponent"},
        {"module": "slotui.events", "symbol": "AgentStreamEventDAO"},
        {"module": "slotui.session", "symbol": "AgentSession"},
        {"module": "slotui.history", "symbol": "SessionHistoryEventDAO"},
        {"module": "slotui.replay", "symbol": "TranscriptEntryDAO"},
        {"module": "slotui.slash", "symbol": "SlashRouter"},
        {"module": "slotui.live_transcript", "symbol": "LiveTranscript"},
    ]
    capability_exports: dict[str, list[str]] = {
        name: [f"{item['module']}.{item['symbol']}"]
        for name, item in zip(REQUIRED_SLOTUI_CAPABILITIES, signature, strict=True)
    }
    b0_stream_schema: dict[str, object] = _opaque_evidence(payload={"schema": "b.0-stream", "version": 1})
    b0_1_live_transcript: dict[str, object] = _opaque_evidence(
        payload={"evidence": "b.0.1-live-transcript", "version": 1}
    )
    return {
        "schema_version": "slo-slotui-adapter-fixture-v1",
        "core_scope": "b.0.1",
        "distribution_name": "slotui",
        "version": "0.1.0",
        "requires_python": ">=3.11",
        "wheel_filename": wheel_path.name,
        "wheel_sha256": _sha256(value=wheel_path.read_bytes()),
        "wheel_artifact": {"source": wheel_path.as_uri()},
        "source_identity": {
            "repository": "https://example.invalid/protected/slotui",
            "commit": "a" * 40,
            "clean": True,
        },
        "rich_capability_state": "raw_fallback_only",
        "immutable_core_export_signature": signature,
        "immutable_core_export_signature_sha256": "",
        "capabilities": [
            {"name": name, "required_exports": capability_exports[name]}
            for name in REQUIRED_SLOTUI_CAPABILITIES
        ],
        "b0_stream_schema": b0_stream_schema,
        "b0_1_live_transcript_evidence": b0_1_live_transcript,
        "core_test_report_hashes": [
            {"report_name": "core-generic", "sha256": "b" * 64},
            {"report_name": "core-static", "sha256": "c" * 64},
        ],
        "manifest_sha256": "",
    }


def _write_wheel_fixture(*, tmp_path: Path, mutation: str | None = None) -> Path:
    """Write a wheel-shaped archive whose package import raises if verification imports it.

    Args:
        tmp_path (Path): Test-local directory for the archive.
        mutation (str | None): Optional static proof failure shape. Defaults to ``None``.

    Returns:
        Path: Exact local wheel path.
    """
    wheel_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    modules: dict[str, str] = {
        "terminal": "class TerminalDriver: pass\nclass RichTerminalDriver: pass\n",
        "editor": "class EditorComponent: pass\n",
        "events": "class AgentStreamEventDAO: pass\n",
        "session": "class AgentSession: pass\n",
        "history": "class SessionHistoryEventDAO: pass\n",
        "replay": "class TranscriptEntryDAO: pass\n",
        "slash": "class SlashRouter: pass\n",
        "live_transcript": "class LiveTranscript: pass\n",
    }
    if mutation == "missing_symbol":
        modules["terminal"] = "class OtherTerminalDriver: pass\n"
    if mutation == "renamed_module":
        modules["renamed_terminal"] = modules.pop("terminal")
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr("slotui/__init__.py", "raise AssertionError('slotui must not be imported')\n")
        for module, source in modules.items():
            archive.writestr(f"slotui/{module}.py", source)
        if mutation == "outside_package":
            archive.writestr("unexpected.py", "class Unexpected: pass\n")
        archive.writestr(
            "slotui-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: slotui\nVersion: 0.1.0\nRequires-Python: >=3.11\n",
        )
        archive.writestr(
            "slotui-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return wheel_path


def _write_reference(*, tmp_path: Path, payload: dict[str, object]) -> SlotuiCoreArtifactReferenceDAO:
    """Persist canonical adapter-fixture bytes and build its Slo local reference.

    Args:
        tmp_path (Path): Test-local storage root.
        payload (dict[str, object]): Fully finalized canonical fixture payload.

    Returns:
        SlotuiCoreArtifactReferenceDAO: Absolute digest-pinned local reference.
    """
    manifest_bytes: bytes = _canonical_json(payload=payload).encode("utf-8")
    manifest_path: Path = tmp_path / "slotui-adapter-fixture.json"
    manifest_path.write_bytes(manifest_bytes)
    return SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
    )


def _opaque_evidence(*, payload: dict[str, object]) -> dict[str, str]:
    """Create opaque owner-evidence-shaped canonical JSON and its independent digest.

    Args:
        payload (dict[str, object]): Minimal opaque evidence content for this Slo test fixture.

    Returns:
        dict[str, str]: Canonical JSON plus SHA-256 without modelling owner schemas.
    """
    canonical_json: str = _canonical_json(payload=payload)
    return {"canonical_json": canonical_json, "sha256": _sha256(value=canonical_json.encode("utf-8"))}


def _finalize_signature_hash(*, payload: dict[str, object]) -> None:
    """Calculate the immutable generic export signature hash in manifest spelling.

    Args:
        payload (dict[str, object]): Mutable adapter fixture payload.
    """
    signature = payload["immutable_core_export_signature"]
    payload["immutable_core_export_signature_sha256"] = _sha256(
        value=_canonical_json(payload=signature).encode("utf-8")
    )


def _finalize_manifest_hash(*, payload: dict[str, object]) -> None:
    """Calculate the canonical non-self-referential adapter-fixture manifest hash.

    Args:
        payload (dict[str, object]): Mutable adapter fixture payload.
    """
    _finalize_signature_hash(payload=payload)
    projection: dict[str, object] = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    payload["manifest_sha256"] = _sha256(value=_canonical_json(payload=projection).encode("utf-8"))


def _canonical_payload(*, payload: dict[str, object]) -> dict[str, object]:
    """Round-trip a fixture through canonical JSON to remove mutable test aliases.

    Args:
        payload (dict[str, object]): Fixture payload to normalize.

    Returns:
        dict[str, object]: JSON-compatible canonical copy.
    """
    return json.loads(_canonical_json(payload=payload))


def _canonical_json(*, payload: object) -> str:
    """Encode a JSON-compatible fixture value deterministically.

    Args:
        payload (object): JSON-compatible fixture value.

    Returns:
        str: Compact sorted canonical JSON.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(*, value: bytes) -> str:
    """Return lowercase SHA-256 for one test fixture byte sequence.

    Args:
        value (bytes): Bytes to hash.

    Returns:
        str: Lowercase SHA-256 digest.
    """
    return hashlib.sha256(value).hexdigest()
