"""Typed fail-closed contracts for a protected Slotui candidate adapter wheel.

Slo is a consumer.  It verifies this manifest without importing the candidate;
the candidate owns every Slotui constructor behind one declared adapter entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import keyword
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "REQUIRED_SLOTUI_CAPABILITIES",
    "REQUIRED_SLOTUI_ADAPTER_CAPABILITIES",
    "SlotuiCandidateAdapterDAO",
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreBundleDAO",
    "SlotuiCoreBundleWheelDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreExportDAO",
    "SlotuiCoreManifestDAO",
    "SlotuiCandidateRunnerDAO",
    "SlotuiCoreSourceIdentityDAO",
    "SlotuiCoreTestReportHashDAO",
    "SlotuiCoreVerificationReceiptDAO",
    "SlotuiOpaqueEvidenceDAO",
    "SlotuiPresentationName",
    "SlotuiPresentationSelectionDAO",
]

REQUIRED_SLOTUI_CAPABILITIES: tuple[str, ...] = (
    "terminal",
    "editor",
    "events",
    "session",
    "history",
    "replay",
    "slash",
    "live_transcript",
)
"""Closed generic evidence list required by the static consumer fixture."""

REQUIRED_SLOTUI_ADAPTER_CAPABILITIES: tuple[str, ...] = (
    "terminal",
    "root",
    "editor",
    "mounted_live_transcript",
    "control_channel",
    "isolation_attestation",
    "protocol_test_hook",
)
"""Capabilities a candidate-defined adapter must implement before Slo will launch it."""

SlotuiPresentationName = Literal["textual_current", "slotui_core"]
_HEX_SHA256_PATTERN: str = r"^[0-9a-f]{64}$"
_MODULE_PATTERN: str = r"^slotui(?:\.[a-z_][a-z0-9_]*)*$"
_SYMBOL_PATTERN: str = r"^[A-Za-z_][A-Za-z0-9_]*$"
_HOST_PROTOCOL_VERSION: str = "slo-slotui-host-control-v2"


class SlotuiCoreArtifactReferenceDAO(BaseModel):
    """Pin a complete local bundle and its manifest by their exact bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["slo-slotui-candidate-adapter-v2"]
    candidate_label: str = Field(min_length=1)
    manifest_path: Path
    manifest_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    bundle_path: Path
    bundle_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _require_absolute_release_paths(self) -> "SlotuiCoreArtifactReferenceDAO":
        """Reject release references that do not independently pin both artifacts.

        Raises:
            ValueError: If either immutable release artifact is relative.
        """
        if not self.manifest_path.is_absolute():
            raise ValueError("Slotui candidate manifest path must be absolute")
        if not self.bundle_path.is_absolute():
            raise ValueError("Slotui candidate bundle path must be absolute")
        return self


class SlotuiCoreBundleManifestDAO(BaseModel):
    """Describe the adapter manifest as recorded by an immutable local bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.json$")
    schema_version: Literal["slo-slotui-candidate-adapter-v2"]
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)


class SlotuiCoreBundleWheelDAO(BaseModel):
    """Pin one wheel in the complete offline candidate dependency closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.whl$")
    role: Literal["core", "runtime_dependency"]
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)


class SlotuiCoreBundleSourceIdentityDAO(BaseModel):
    """Pin the clean source archive identity that produced a bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    tree: str = Field(pattern=r"^[0-9a-f]{40}$")


class SlotuiCoreBundleCandidateDAO(BaseModel):
    """Record the closed raw-fallback posture of the candidate delivery bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    source_kind: Literal["clean_committed_git_archive"]
    rich_fallback_declaration: dict[
        Literal["a.9_b.8_rich_capability", "rich_capability_state"],
        Literal["raw/literal fallback only", "raw_fallback_only"],
    ]

    @model_validator(mode="after")
    def _require_exact_raw_fallback_declaration(self) -> "SlotuiCoreBundleCandidateDAO":
        """Require both independent raw-fallback statements exactly once.

        Raises:
            ValueError: If the bundle claims rich capability or omits a declaration.
        """
        expected: dict[str, str] = {
            "a.9_b.8_rich_capability": "raw/literal fallback only",
            "rich_capability_state": "raw_fallback_only",
        }
        if self.rich_fallback_declaration != expected:
            raise ValueError("Slotui bundle must retain the exact raw/literal fallback declaration")
        return self


class SlotuiCoreBundleDAO(BaseModel):
    """Strict manifest for the entire immutable local offline wheel closure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["slotui-local-core-bundle-v2"]
    candidate: SlotuiCoreBundleCandidateDAO
    requires_python: str = Field(min_length=1)
    slo_adapter_manifest: SlotuiCoreBundleManifestDAO
    source_identity: SlotuiCoreBundleSourceIdentityDAO
    wheels: tuple[SlotuiCoreBundleWheelDAO, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _require_exact_wheel_closure_shape(self) -> "SlotuiCoreBundleDAO":
        """Reject duplicate wheels or anything other than one core wheel.

        Raises:
            ValueError: If the closure is ambiguous or lacks its core artifact.
        """
        filenames: tuple[str, ...] = tuple(wheel.filename for wheel in self.wheels)
        names: tuple[str, ...] = tuple(
            wheel.distribution_name.lower().replace("_", "-") for wheel in self.wheels
        )
        core_wheels: tuple[SlotuiCoreBundleWheelDAO, ...] = tuple(
            wheel for wheel in self.wheels if wheel.role == "core"
        )
        if len(set(filenames)) != len(filenames) or len(set(names)) != len(names):
            raise ValueError("Slotui bundle wheel filenames and distributions must be unique")
        if len(core_wheels) != 1 or core_wheels[0].distribution_name != "slotui":
            raise ValueError("Slotui bundle must declare exactly one slotui core wheel")
        return self


class SlotuiCoreCapabilityDAO(BaseModel):
    """Map a generic static capability to module-qualified candidate exports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    required_exports: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_module_qualified_exports(self) -> "SlotuiCoreCapabilityDAO":
        """Reject ambiguous or non-Slotui exports.

        Raises:
            ValueError: If an export does not name an explicit Slotui module and symbol.
        """
        if any(not _is_module_qualified_export(declaration=value) for value in self.required_exports):
            raise ValueError("capability exports must be module-qualified Slotui declarations")
        return self


class SlotuiCoreExportDAO(BaseModel):
    """Declare one generic public symbol at one explicit Slotui module path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str = Field(pattern=_MODULE_PATTERN)
    symbol: str = Field(pattern=_SYMBOL_PATTERN)

    @property
    def declaration(self) -> str:
        """Return the static module-qualified export declaration.

        Returns:
            str: The candidate declaration without importing it.
        """
        return f"{self.module}.{self.symbol}"


class SlotuiCandidateAdapterDAO(BaseModel):
    """Declare the sole candidate-defined runtime entrypoint Slo is allowed to call.

    The verified wheel must define exactly an ``async def`` with keyword-only
    ``launch`` and ``control`` parameters.  Its implementation owns terminal,
    root, editor, and transcript construction; Slo has no knowledge of those
    candidate APIs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str = Field(pattern=_MODULE_PATTERN)
    symbol: str = Field(pattern=_SYMBOL_PATTERN)
    callable_kind: Literal["async_function"]
    keyword_parameters: tuple[Literal["launch", "control"], Literal["launch", "control"]]
    protocol_version: Literal["slo-slotui-host-control-v2"]
    capabilities: tuple[str, ...] = Field(min_length=1)
    signature_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _require_closed_adapter_capabilities(self) -> "SlotuiCandidateAdapterDAO":
        """Require every and only every v2 adapter capability once.

        Raises:
            ValueError: If the adapter does not prove the whole launch contract.
        """
        if tuple(sorted(self.capabilities)) != tuple(sorted(REQUIRED_SLOTUI_ADAPTER_CAPABILITIES)):
            raise ValueError("candidate adapter capabilities must exactly match the v2 adapter contract")
        return self

    @property
    def declaration(self) -> str:
        """Return the candidate-defined entrypoint declaration.

        Returns:
            str: Module plus callable symbol.
        """
        return f"{self.module}.{self.symbol}"


class SlotuiCandidateRunnerDAO(BaseModel):
    """Declare the sole candidate-owned process runner that invokes the adapter.

    The installed wheel runner has a separately pinned async entrypoint and a
    ``python_module_main`` executable bridge. It receives only the private
    control configuration, imports the manifested adapter, and calls it with
    the launch/control objects it establishes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str = Field(pattern=_MODULE_PATTERN)
    symbol: str = Field(pattern=_SYMBOL_PATTERN)
    execution_mode: Literal["python_module_main"]
    """Require the module's verified ``if __name__ == "__main__"`` CLI bridge."""
    callable_kind: Literal["async_function"]
    keyword_parameters: tuple[
        Literal["control_socket"],
        Literal["adapter_module"],
        Literal["adapter_symbol"],
        Literal["protocol_version"],
    ]
    protocol_version: Literal["slo-slotui-host-control-v2"]
    signature_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @property
    def declaration(self) -> str:
        """Return the candidate runner entrypoint declaration.

        Returns:
            str: Module plus async runner symbol.
        """
        return f"{self.module}.{self.symbol}"


class SlotuiCoreSourceIdentityDAO(BaseModel):
    """Record independently supplied protected-source identity and clean assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    clean: Literal[True]


class SlotuiOpaqueEvidenceDAO(BaseModel):
    """Carry owner-produced canonical JSON evidence without owning its schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_json: str = Field(min_length=2)
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _require_exact_opaque_json_hash(self) -> "SlotuiOpaqueEvidenceDAO":
        """Verify opaque owner evidence is canonical and digest-pinned.

        Raises:
            ValueError: If the evidence cannot be proven exact.
        """
        try:
            payload: object = json.loads(self.canonical_json)
        except json.JSONDecodeError as error:
            raise ValueError("opaque Slotui evidence must contain JSON") from error
        if self.canonical_json != _canonical_json(payload=payload):
            raise ValueError("opaque Slotui evidence JSON must be canonical")
        if _sha256(value=self.canonical_json.encode("utf-8")) != self.sha256:
            raise ValueError("opaque Slotui evidence SHA-256 does not match its canonical JSON")
        return self


class SlotuiCoreTestReportHashDAO(BaseModel):
    """Pin one opaque owner-produced core test report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)


class SlotuiCoreManifestDAO(BaseModel):
    """Strict v2 manifest for one versioned candidate adapter wheel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["slo-slotui-candidate-adapter-v2"]
    core_scope: Literal["b.0.1"]
    distribution_name: Literal["slotui"]
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    requires_python: str = Field(min_length=1)
    wheel_filename: str = Field(pattern=r"^slotui-[0-9]+\.[0-9]+\.[0-9]+-[A-Za-z0-9_.-]+\.whl$")
    wheel_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    wheel_artifact: dict[Literal["source"], str]
    source_identity: SlotuiCoreSourceIdentityDAO
    rich_capability_state: Literal["raw_fallback_only"]
    immutable_core_export_signature: tuple[SlotuiCoreExportDAO, ...] = Field(min_length=1)
    immutable_core_export_signature_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    capabilities: tuple[SlotuiCoreCapabilityDAO, ...] = Field(min_length=1)
    candidate_adapter: SlotuiCandidateAdapterDAO
    candidate_runner: SlotuiCandidateRunnerDAO
    b0_stream_schema: SlotuiOpaqueEvidenceDAO
    b0_1_live_transcript_evidence: SlotuiOpaqueEvidenceDAO
    core_test_report_hashes: tuple[SlotuiCoreTestReportHashDAO, ...] = Field(min_length=1)
    manifest_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_contract(self) -> "SlotuiCoreManifestDAO":
        """Reject incomplete, ambiguous, rich-only, or inconsistent candidate manifests.

        Raises:
            ValueError: If static proof cannot establish the closed consumer contract.
        """
        self._require_exact_wheel_name()
        self._require_exact_capabilities()
        self._require_exact_generic_exports()
        self._require_export_signature_hash()
        self._require_unique_test_reports()
        return self

    def canonical_projection_bytes(self) -> bytes:
        """Return canonical manifest bytes excluding its self hash.

        Returns:
            bytes: Deterministic projection that the manifest hash covers.
        """
        projection: dict[str, object] = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return _canonical_json(payload=projection).encode("utf-8")

    def require_canonical_manifest_hash(self) -> None:
        """Verify the manifest's non-self-referential projection hash.

        Raises:
            ValueError: If a manifest field is not covered by its digest.
        """
        if _sha256(value=self.canonical_projection_bytes()) != self.manifest_sha256:
            raise ValueError("Slotui candidate manifest SHA-256 does not match its canonical projection")

    def _require_exact_wheel_name(self) -> None:
        """Require the declared version in the exact wheel name.

        Raises:
            ValueError: If wheel identity and version diverge.
        """
        if not self.wheel_filename.startswith(f"slotui-{self.version}-"):
            raise ValueError("wheel_filename must contain the candidate distribution version")

    def _require_exact_capabilities(self) -> None:
        """Require each generic static capability exactly once.

        Raises:
            ValueError: If capability coverage is incomplete or duplicated.
        """
        names: tuple[str, ...] = tuple(item.name for item in self.capabilities)
        if tuple(sorted(names)) != tuple(sorted(REQUIRED_SLOTUI_CAPABILITIES)):
            raise ValueError("core capabilities must exactly match Slo's required generic capability list")

    def _require_exact_generic_exports(self) -> None:
        """Require the generic evidence signature to exactly cover capability exports.

        Raises:
            ValueError: If declarations are duplicate, rich-only, or incomplete.
        """
        signature: tuple[str, ...] = tuple(item.declaration for item in self.immutable_core_export_signature)
        required: tuple[str, ...] = tuple(
            value for capability in self.capabilities for value in capability.required_exports
        )
        self._require_no_duplicates(declarations=signature, owner="export signature")
        self._require_no_duplicates(declarations=required, owner="capabilities")
        if set(signature) != set(required):
            raise ValueError("capability exports must exactly match the immutable core export signature")
        if any("rich" in value.lower() for value in signature):
            raise ValueError("adapter fixture export signature must not declare rich-only exports")

    def _require_export_signature_hash(self) -> None:
        """Require a digest of the exact generic export signature.

        Raises:
            ValueError: If generic evidence is not pinned.
        """
        signature: list[dict[str, str]] = [
            item.model_dump(mode="json") for item in self.immutable_core_export_signature
        ]
        if (
            _sha256(value=_canonical_json(payload=signature).encode("utf-8"))
            != self.immutable_core_export_signature_sha256
        ):
            raise ValueError(
                "immutable core export signature SHA-256 does not match its canonical declaration list"
            )

    def _require_unique_test_reports(self) -> None:
        """Require distinct non-rich opaque test report names.

        Raises:
            ValueError: If owner test evidence is ambiguous or rich-only.
        """
        names: tuple[str, ...] = tuple(item.report_name for item in self.core_test_report_hashes)
        if len(set(names)) != len(names):
            raise ValueError("core test report hashes may not contain duplicate report names")
        if any("rich" in value for value in names):
            raise ValueError("adapter fixture may not claim a rich-only core test report")

    @staticmethod
    def _require_no_duplicates(*, declarations: tuple[str, ...], owner: str) -> None:
        """Reject repeated export declarations.

        Args:
            declarations (tuple[str, ...]): Values requiring uniqueness.
            owner (str): Manifest field named in a useful failure.

        Raises:
            ValueError: If a declaration repeats.
        """
        if len(set(declarations)) != len(declarations):
            raise ValueError(f"{owner} may not contain duplicate export declarations")


class SlotuiCoreVerificationReceiptDAO(BaseModel):
    """Record static proof authorizing a separate isolated candidate process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: Literal["slotui"]
    version: str
    wheel_path: Path
    verified_wheel_paths: tuple[Path, ...] = Field(min_length=2)
    manifest: SlotuiCoreManifestDAO

    @model_validator(mode="after")
    def _require_core_wheel_in_verified_closure(self) -> "SlotuiCoreVerificationReceiptDAO":
        """Require the exact core wheel to remain in the installable closure.

        Raises:
            ValueError: If the receipt's core wheel is not an exact verified member.
        """
        if self.wheel_path not in self.verified_wheel_paths:
            raise ValueError("Slotui receipt core wheel must belong to its verified closure")
        return self


class SlotuiPresentationSelectionDAO(BaseModel):
    """Carry one explicit interactive selection after static verification only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    presentation: SlotuiPresentationName
    core_verification_receipt: SlotuiCoreVerificationReceiptDAO | None = None

    @model_validator(mode="after")
    def _require_receipt_only_for_core(self) -> "SlotuiPresentationSelectionDAO":
        """Keep Textual selection independent of candidate artifacts.

        Raises:
            ValueError: If an opt-in receipt is missing or leaks into Textual selection.
        """
        if self.presentation == "slotui_core" and self.core_verification_receipt is None:
            raise ValueError("Slotui core selection requires a verified candidate adapter receipt")
        if self.presentation == "textual_current" and self.core_verification_receipt is not None:
            raise ValueError("Textual selection must not carry a Slotui verification receipt")
        return self


def _canonical_json(*, payload: object) -> str:
    """Serialize a JSON-compatible fixture value canonically.

    Args:
        payload (object): Typed fixture value.

    Returns:
        str: Sorted compact UTF-8-safe JSON.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _is_module_qualified_export(*, declaration: str) -> bool:
    """Determine whether a declaration names a valid Slotui module and symbol.

    Args:
        declaration (str): Candidate export declaration.

    Returns:
        bool: Whether it is an explicit ``slotui.<module>.<symbol>`` value.
    """
    module, separator, symbol = declaration.rpartition(".")
    return bool(separator and _matches_module(module=module) and _is_identifier(value=symbol))


def _matches_module(*, module: str) -> bool:
    """Determine whether a dotted module is confined to Slotui identifiers.

    Args:
        module (str): Dotted module declaration.

    Returns:
        bool: Whether it starts with ``slotui`` and has valid segments.
    """
    parts: list[str] = module.split(".")
    return bool(parts and parts[0] == "slotui" and all(_is_identifier(value=value) for value in parts))


def _is_identifier(*, value: str) -> bool:
    """Determine whether a string is a non-keyword Python identifier.

    Args:
        value (str): Identifier to validate.

    Returns:
        bool: Whether Python can use it as an identifier.
    """
    return value.isidentifier() and not keyword.iskeyword(value)


def _sha256(*, value: bytes) -> str:
    """Return the lowercase SHA-256 digest of bytes.

    Args:
        value (bytes): Bytes to pin.

    Returns:
        str: Lowercase hexadecimal digest.
    """
    return hashlib.sha256(value).hexdigest()
