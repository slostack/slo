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
from src.integrations.slotui.reference import (
    SlotuiCoreReferenceDerivationError,
    SlotuiCoreReferenceDerivationService,
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


@pytest.mark.parametrize(
    ("runner_source", "error_match"),
    [
        (
            "async def run_candidate(*, control_socket, adapter_module, adapter_symbol, protocol_version):\n"
            "    return None\n",
            "does not directly load and invoke",
        ),
        (
            "import asyncio\n"
            "async def run_candidate(*, control_socket, adapter_module, adapter_symbol, protocol_version):\n"
            "    adapter = await load_adapter(module=adapter_module, symbol=adapter_symbol)\n"
            "    launch, control = await connect_control(socket=control_socket, version=protocol_version)\n"
            "    await adapter(launch=launch, control=control)\n"
            "asyncio.run(asyncio.sleep(0))\n",
            "inert asyncio.run",
        ),
    ],
)
def test_build_verification_receipt_when_candidate_runner_is_inert_or_unrelated_rejects_before_runtime(
    tmp_path: Path,
    runner_source: str,
    error_match: str,
) -> None:
    """Reject a declared runner that does not actually bridge control to the candidate adapter."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    _replace_wheel_module_source(
        wheel_path=wheel_path,
        module="_slo_candidate_adapter_runner",
        source=runner_source,
    )
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match=error_match):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_candidate_runner_has_no_module_execution_bridge_rejects(
    tmp_path: Path,
) -> None:
    """Reject a valid runner function when ``python -m`` cannot invoke it with host flags."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    _replace_wheel_module_source(
        wheel_path=wheel_path,
        module="_slo_candidate_adapter_runner",
        source=(
            "async def run_candidate(*, control_socket, adapter_module, adapter_symbol, protocol_version):\n"
            "    adapter = await load_adapter(module=adapter_module, symbol=adapter_symbol)\n"
            "    launch, control = await connect_control(socket=control_socket, version=protocol_version)\n"
            "    await adapter(launch=launch, control=control)\n"
        ),
    )
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="executable module bridge"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_candidate_adapter_signature_is_wrong_rejects_before_runtime(
    tmp_path: Path,
) -> None:
    """Reject a candidate whose single runtime entrypoint signature digest is stale."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    payload["candidate_adapter"]["signature_sha256"] = "0" * 64  # type: ignore[index]
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="adapter signature SHA-256"):
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
    bundle_path: Path = tmp_path / "slotui-local-core-candidate.bundle.json"
    dependency_path: Path = tmp_path / "runtime_dependency-0.1.0-py3-none-any.whl"
    dependency_path.write_bytes(b"test-only dependency wheel bytes")
    bundle_path.write_bytes(
        _canonical_json(
            payload=_bundle_payload(
                wheel_path=wheel_path,
                manifest_path=manifest_path,
                dependency_path=dependency_path,
            )
        ).encode("utf-8")
    )
    reference = SlotuiCoreArtifactReferenceDAO(
        schema_version="slo-slotui-candidate-adapter-v2",
        candidate_label="hermetic Slotui core test fixture",
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=_canonical_json(payload=payload).encode("utf-8")),
        bundle_path=bundle_path,
        bundle_sha256=_sha256(value=bundle_path.read_bytes()),
    )

    with pytest.raises(SlotuiCoreVerificationError, match="pinned reference"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_bundle_dependency_bytes_are_tampered_rejects_before_wheel_static_proof(
    tmp_path: Path,
) -> None:
    """Reject one altered runtime dependency even though the core wheel remains intact."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    dependency_path: Path = reference.bundle_path.parent / "runtime_dependency-0.1.0-py3-none-any.whl"
    dependency_path.write_bytes(b"tampered dependency bytes")

    with pytest.raises(SlotuiCoreVerificationError, match="bundle wheel SHA-256"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_bundle_omits_dependency_rejects_before_wheel_static_proof(
    tmp_path: Path,
) -> None:
    """Reject a reference-pinned bundle whose declared closure omits a required wheel file."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    bundle_payload: dict[str, object] = json.loads(reference.bundle_path.read_text(encoding="utf-8"))
    bundle_payload["wheels"] = bundle_payload["wheels"][:-1]  # type: ignore[index]
    bundle_bytes: bytes = _canonical_json(payload=bundle_payload).encode("utf-8")
    reference.bundle_path.write_bytes(bundle_bytes)
    tampered_reference = reference.model_copy(update={"bundle_sha256": _sha256(value=bundle_bytes)})

    with pytest.raises(SlotuiCoreVerificationError, match="wheel closure"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=tampered_reference)


def test_build_verification_receipt_when_core_requirement_is_absent_from_bundle_rejects(
    tmp_path: Path,
) -> None:
    """Reject a required direct dependency that the declared offline bundle does not carry."""
    wheel_path: Path = _write_wheel_fixture(
        tmp_path=tmp_path,
        requires_dist=("missing-runtime>=1.0",),
    )
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="required dependency is absent"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_bundle_contains_unreachable_dependency_rejects(
    tmp_path: Path,
) -> None:
    """Reject a pinned dependency wheel inactive for the Python 3.11/Linux target."""
    wheel_path: Path = _write_wheel_fixture(
        tmp_path=tmp_path,
        requires_dist=("runtime-dependency==0.1.0; sys_platform == 'darwin'",),
    )
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)

    with pytest.raises(SlotuiCoreVerificationError, match="undeclared active dependency closure"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_transitive_requirement_is_absent_from_bundle_rejects(
    tmp_path: Path,
) -> None:
    """Reject an active transitive dependency absent from the declared offline closure."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(
        tmp_path=tmp_path,
        payload=payload,
        dependency_requires_dist=("missing-transitive>=1.0",),
    )

    with pytest.raises(
        SlotuiCoreVerificationError, match="required dependency is absent.*missing-transitive"
    ):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)


def test_build_verification_receipt_when_artifact_directory_has_undeclared_extra_wheel_accepts_closure(
    tmp_path: Path,
) -> None:
    """Prove arbitrary colocated wheels are not considered part of the verified install closure."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    _write_dependency_wheel_fixture(
        tmp_path=tmp_path,
        distribution_name="unrelated-extra",
        filename="unrelated_extra-0.1.0-py3-none-any.whl",
    )

    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert {path.name for path in receipt.verified_wheel_paths} == {
        "slotui-0.1.0-py3-none-any.whl",
        "runtime_dependency-0.1.0-py3-none-any.whl",
    }


def test_artifact_reference_when_bundle_pin_fields_are_absent_rejects_at_schema_boundary() -> None:
    """Reject legacy references before a same-named colocated bundle could be discovered."""
    with pytest.raises(ValueError, match="bundle_path"):
        SlotuiCoreArtifactReferenceDAO.model_validate(
            {
                "schema_version": "slo-slotui-candidate-adapter-v2",
                "candidate_label": "legacy",
                "manifest_path": "/absolute/candidate.json",
                "manifest_sha256": "0" * 64,
            }
        )


def test_build_verification_receipt_when_substituted_same_named_bundle_rejects_before_manifest_or_install(
    tmp_path: Path,
) -> None:
    """Reject a colocated conventional filename when it differs from the reference-pinned bundle."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    substituted_bundle_path: Path = tmp_path / "slotui-local-core-candidate.bundle.json"
    substituted_bundle_path.write_bytes(b'{"substituted":"bundle"}')
    pinned_reference = reference.model_copy(
        update={"bundle_path": tmp_path / "explicitly-pinned-bundle.json"}
    )

    with pytest.raises(SlotuiCoreVerificationError, match="bundle is unavailable"):
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=pinned_reference)

    assert not pinned_reference.bundle_path.exists()
    assert substituted_bundle_path.is_file()
    assert "slotui" not in sys.modules


def test_derive_when_legacy_reference_and_explicit_bundle_are_supplied_writes_a_separate_pinned_v2_reference(
    tmp_path: Path,
) -> None:
    """Create a launchable v2 reference without mutating the supplied legacy candidate reference."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    legacy_path: Path = tmp_path / "legacy-reference.json"
    legacy_payload: dict[str, object] = reference.model_dump(
        mode="json", exclude={"bundle_path", "bundle_sha256"}
    )
    legacy_path.write_text(_canonical_json(payload=legacy_payload), encoding="utf-8")
    output_path: Path = tmp_path / "derived-pinned-reference.json"

    derived = SlotuiCoreReferenceDerivationService.derive(
        legacy_reference_path=legacy_path,
        bundle_path=reference.bundle_path,
        output_path=output_path,
    )

    assert json.loads(legacy_path.read_text(encoding="utf-8")) == legacy_payload
    assert derived.bundle_path == reference.bundle_path
    assert derived.bundle_sha256 == _sha256(value=reference.bundle_path.read_bytes())
    assert (
        SlotuiCoreWheelVerificationService.build_verification_receipt(reference=derived).wheel_path
        == wheel_path
    )


def test_derive_when_legacy_manifest_bytes_do_not_match_its_digest_rejects(
    tmp_path: Path,
) -> None:
    """Reject a legacy pointer whose retained manifest facts are already stale or substituted."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    legacy_path: Path = tmp_path / "legacy-reference.json"
    legacy_payload: dict[str, object] = reference.model_dump(
        mode="json", exclude={"bundle_path", "bundle_sha256"}
    )
    legacy_path.write_text(_canonical_json(payload=legacy_payload), encoding="utf-8")
    reference.manifest_path.write_text("substituted manifest", encoding="utf-8")

    with pytest.raises(SlotuiCoreReferenceDerivationError, match="manifest SHA-256"):
        SlotuiCoreReferenceDerivationService.derive(
            legacy_reference_path=legacy_path,
            bundle_path=reference.bundle_path,
            output_path=tmp_path / "derived-pinned-reference.json",
        )


def test_derive_when_output_would_overwrite_legacy_reference_rejects(
    tmp_path: Path,
) -> None:
    """Preserve legacy evidence by refusing to overwrite it with derived v2 fields."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    legacy_path: Path = tmp_path / "legacy-reference.json"
    legacy_payload: dict[str, object] = reference.model_dump(
        mode="json", exclude={"bundle_path", "bundle_sha256"}
    )
    legacy_path.write_text(_canonical_json(payload=legacy_payload), encoding="utf-8")

    with pytest.raises(SlotuiCoreReferenceDerivationError, match="not already exist"):
        SlotuiCoreReferenceDerivationService.derive(
            legacy_reference_path=legacy_path,
            bundle_path=reference.bundle_path,
            output_path=legacy_path,
        )


def test_build_verification_receipt_when_reference_path_is_relative_rejects_at_schema_boundary(
    tmp_path: Path,
) -> None:
    """Reject relative release references before any candidate byte access."""
    with pytest.raises(ValueError, match="must be absolute"):
        SlotuiCoreArtifactReferenceDAO(
            schema_version="slo-slotui-candidate-adapter-v2",
            candidate_label="relative",
            manifest_path=Path("candidate.json"),
            manifest_sha256="0" * 64,
            bundle_path=Path("candidate.bundle.json"),
            bundle_sha256="0" * 64,
        )


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
        {"module": "slotui.history.transcript", "symbol": "TranscriptEntryDAO"},
        {"module": "slotui.slash", "symbol": "SlashRouter"},
        {"module": "slotui.transcript", "symbol": "LiveTranscript"},
    ]
    capability_exports: dict[str, list[str]] = {
        name: [f"{item['module']}.{item['symbol']}"]
        for name, item in zip(REQUIRED_SLOTUI_CAPABILITIES, signature, strict=True)
    }
    b0_stream_schema: dict[str, str] = _opaque_evidence(payload={"schema": "b.0-stream", "version": 1})
    b0_1_live_transcript: dict[str, str] = _opaque_evidence(
        payload={"evidence": "b.0.1-live-transcript", "version": 1}
    )
    return {
        "schema_version": "slo-slotui-candidate-adapter-v2",
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
        "candidate_adapter": {
            "module": "slotui.slo_adapter",
            "symbol": "launch_tui_app",
            "callable_kind": "async_function",
            "keyword_parameters": ["launch", "control"],
            "protocol_version": "slo-slotui-host-control-v2",
            "capabilities": [
                "terminal",
                "root",
                "editor",
                "mounted_live_transcript",
                "control_channel",
                "isolation_attestation",
                "protocol_test_hook",
            ],
            "signature_sha256": _sha256(value=b"async def adapter(*, launch, control)"),
        },
        "candidate_runner": {
            "module": "slotui._slo_candidate_adapter_runner",
            "symbol": "run_candidate",
            "execution_mode": "python_module_main",
            "callable_kind": "async_function",
            "keyword_parameters": ["control_socket", "adapter_module", "adapter_symbol", "protocol_version"],
            "protocol_version": "slo-slotui-host-control-v2",
            "signature_sha256": _sha256(
                value=b"async def runner(*, control_socket, adapter_module, adapter_symbol, protocol_version)"
            ),
        },
        "manifest_sha256": "",
    }


def _write_wheel_fixture(
    *,
    tmp_path: Path,
    mutation: str | None = None,
    requires_dist: tuple[str, ...] = ("runtime-dependency==0.1.0",),
) -> Path:
    """Write a wheel-shaped archive whose package import raises if verification imports it.

    Args:
        tmp_path (Path): Test-local directory for the archive.
        mutation (str | None): Optional static proof failure shape. Defaults to ``None``.
        requires_dist (tuple[str, ...]): Core metadata requirements. Defaults to the test runtime dependency.

    Returns:
        Path: Exact local wheel path.
    """
    wheel_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    modules: dict[str, str] = {
        "terminal": "class TerminalDriver: pass\nclass RichTerminalDriver: pass\n",
        "container": "class Container: pass\n",
        "editor": "class EditorComponent: pass\n",
        "events": "class AgentStreamEventDAO: pass\n",
        "session": "class AgentSession: pass\n",
        "history": "class SessionHistoryEventDAO: pass\n",
        "history/transcript": "class TranscriptEntryDAO: pass\n",
        "slash": "class SlashRouter: pass\n",
        "transcript": "class LiveTranscript: pass\nclass TranscriptMutationDAO: pass\n",
        "transcript/renderer": "class TranscriptRenderer: pass\n",
        "slo_adapter": "async def launch_tui_app(*, launch, control):\n    return None\n",
        "_slo_candidate_adapter_runner": (
            "import argparse\n"
            "import asyncio\n"
            "import sys\n"
            "\n"
            "async def run_candidate(*, control_socket, adapter_module, adapter_symbol, protocol_version):\n"
            "    adapter = await load_adapter(module=adapter_module, symbol=adapter_symbol)\n"
            "    launch, control = await connect_control(socket=control_socket, version=protocol_version)\n"
            "    await adapter(launch=launch, control=control)\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--control-socket', dest='control_socket', required=True)\n"
            "    parser.add_argument('--adapter-module', dest='adapter_module', required=True)\n"
            "    parser.add_argument('--adapter-symbol', dest='adapter_symbol', required=True)\n"
            "    parser.add_argument('--protocol-version', dest='protocol_version', required=True)\n"
            "    arguments = parser.parse_args(args=sys.argv[1:])\n"
            "    asyncio.run(run_candidate(\n"
            "        control_socket=arguments.control_socket,\n"
            "        adapter_module=arguments.adapter_module,\n"
            "        adapter_symbol=arguments.adapter_symbol,\n"
            "        protocol_version=arguments.protocol_version,\n"
            "    ))\n"
        ),
    }
    if mutation == "missing_symbol":
        modules["terminal"] = "class OtherTerminalDriver: pass\n"
    if mutation == "renamed_module":
        modules["renamed_terminal"] = modules.pop("terminal")
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr("slotui/__init__.py", "raise AssertionError('slotui must not be imported')\n")
        for module, source in modules.items():
            archive.writestr(_module_archive_path(module=module), source)
        if mutation == "outside_package":
            archive.writestr("unexpected.py", "class Unexpected: pass\n")
        metadata: str = (
            "Metadata-Version: 2.1\nName: slotui\nVersion: 0.1.0\nRequires-Python: >=3.11\n"
            + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires_dist)
        )
        archive.writestr("slotui-0.1.0.dist-info/METADATA", metadata)
        archive.writestr(
            "slotui-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return wheel_path


def _write_dependency_wheel_fixture(
    *,
    tmp_path: Path,
    distribution_name: str = "runtime-dependency",
    filename: str = "runtime_dependency-0.1.0-py3-none-any.whl",
    requires_dist: tuple[str, ...] = (),
) -> Path:
    """Write a minimal valid wheel for a declared runtime dependency test case.

    Args:
        tmp_path (Path): Test-local directory for the wheel.
        distribution_name (str): Distribution identity represented by METADATA. Defaults to runtime-dependency.
        filename (str): Wheel filename. Defaults to runtime_dependency-0.1.0-py3-none-any.whl.
        requires_dist (tuple[str, ...]): Optional transitive metadata requirements. Defaults to an empty tuple.

    Returns:
        Path: Exact local wheel with declared metadata.
    """
    dependency_path: Path = tmp_path / filename
    metadata_name: str = distribution_name.replace("-", "_")
    metadata: str = f"Metadata-Version: 2.1\nName: {distribution_name}\nVersion: 0.1.0\n" + "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requires_dist
    )
    with zipfile.ZipFile(dependency_path, mode="w") as archive:
        archive.writestr(f"{metadata_name}-0.1.0.dist-info/METADATA", metadata)
        archive.writestr(
            f"{metadata_name}-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return dependency_path


def _replace_wheel_module_source(*, wheel_path: Path, module: str, source: str) -> None:
    """Replace one test wheel source member while preserving archive metadata members.

    Args:
        wheel_path (Path): Existing local fixture wheel.
        module (str): Package-relative module key.
        source (str): Replacement Python source.
    """
    members: dict[str, bytes]
    with zipfile.ZipFile(wheel_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members[_module_archive_path(module=module)] = source.encode("utf-8")
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _module_archive_path(*, module: str) -> str:
    """Map a dotted or package module test key to its wheel source member.

    Args:
        module (str): Slash-separated package-relative test module key.

    Returns:
        str: Canonical archive member containing that module's source.
    """
    if "/" not in module:
        return f"slotui/{module}.py"
    return f"slotui/{module}/__init__.py"


def _write_reference(
    *,
    tmp_path: Path,
    payload: dict[str, object],
    dependency_requires_dist: tuple[str, ...] = (),
) -> SlotuiCoreArtifactReferenceDAO:
    """Persist canonical adapter-fixture bytes and build its Slo local reference.

    Args:
        tmp_path (Path): Test-local storage root.
        payload (dict[str, object]): Fully finalized canonical fixture payload.
        dependency_requires_dist (tuple[str, ...]): Active test requirements for the runtime dependency.

    Returns:
        SlotuiCoreArtifactReferenceDAO: Absolute digest-pinned local reference.
    """
    manifest_bytes: bytes = _canonical_json(payload=payload).encode("utf-8")
    manifest_path: Path = tmp_path / "slotui-adapter-fixture.json"
    manifest_path.write_bytes(manifest_bytes)
    declared_source: str = payload["wheel_artifact"]["source"]  # type: ignore[index]
    wheel_path: Path = Path(declared_source.removeprefix("file://"))
    if not wheel_path.is_file():
        wheel_path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    dependency_path: Path = _write_dependency_wheel_fixture(
        tmp_path=tmp_path,
        requires_dist=dependency_requires_dist,
    )
    bundle_path: Path = tmp_path / "slotui-local-core-candidate.bundle.json"
    bundle_bytes: bytes = _canonical_json(
        payload=_bundle_payload(
            wheel_path=wheel_path,
            manifest_path=manifest_path,
            dependency_path=dependency_path,
        )
    ).encode("utf-8")
    bundle_path.write_bytes(bundle_bytes)
    return SlotuiCoreArtifactReferenceDAO(
        schema_version="slo-slotui-candidate-adapter-v2",
        candidate_label="hermetic Slotui core test fixture",
        manifest_path=manifest_path,
        manifest_sha256=_sha256(value=manifest_bytes),
        bundle_path=bundle_path,
        bundle_sha256=_sha256(value=bundle_bytes),
    )


def _bundle_payload(*, wheel_path: Path, manifest_path: Path, dependency_path: Path) -> dict[str, object]:
    """Build the complete canonical local wheel closure for a test fixture.

    Args:
        wheel_path (Path): Exact fixture core wheel.

    Returns:
        dict[str, object]: Bundle that pins the manifest relationship and all wheels.
    """
    return {
        "schema_version": "slotui-local-core-bundle-v2",
        "candidate": {
            "label": "hermetic Slotui core test fixture",
            "source_kind": "clean_committed_git_archive",
            "rich_fallback_declaration": {
                "a.9_b.8_rich_capability": "raw/literal fallback only",
                "rich_capability_state": "raw_fallback_only",
            },
        },
        "requires_python": ">=3.11",
        "slo_adapter_manifest": {
            "filename": manifest_path.name,
            "schema_version": "slo-slotui-candidate-adapter-v2",
            "sha256": _sha256(value=manifest_path.read_bytes()),
        },
        "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        "wheels": [
            {
                "distribution_name": "slotui",
                "filename": wheel_path.name,
                "role": "core",
                "sha256": _sha256(value=wheel_path.read_bytes()),
            },
            {
                "distribution_name": "runtime-dependency",
                "filename": dependency_path.name,
                "role": "runtime_dependency",
                "sha256": _sha256(value=dependency_path.read_bytes()),
            },
        ],
    }


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
