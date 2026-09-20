"""Typed adapter-fixture contracts for future Slotui core wheel verification.

These models belong to Slo's consumer boundary.  They are intentionally not a
Slotui owner schema and never import or execute the protected package.
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
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreExportDAO",
    "SlotuiCoreManifestDAO",
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
"""Closed generic capability list required by this Slo adapter fixture."""

SlotuiPresentationName = Literal["textual_current", "slotui_core"]
"""Operator-selected interactive presentation names; Textual remains the default."""

_HEX_SHA256_PATTERN: str = r"^[0-9a-f]{64}$"
_MODULE_PATTERN: str = r"^slotui(?:\.[a-z_][a-z0-9_]*)*$"
_SYMBOL_PATTERN: str = r"^[A-Za-z_][A-Za-z0-9_]*$"


class SlotuiCoreArtifactReferenceDAO(BaseModel):
    """Pin exact local adapter-fixture manifest bytes by absolute path and digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_path: Path
    manifest_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _require_absolute_manifest_path(self) -> "SlotuiCoreArtifactReferenceDAO":
        """Reject relative fixture references before Slo reads their bytes.

        Raises:
            ValueError: If the reference cannot name one local immutable file.
        """
        if not self.manifest_path.is_absolute():
            raise ValueError("Slotui adapter fixture manifest path must be absolute")
        return self


class SlotuiCoreCapabilityDAO(BaseModel):
    """Map one required generic capability to explicit module-qualified exports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    required_exports: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_module_qualified_exports(self) -> "SlotuiCoreCapabilityDAO":
        """Reject capability exports that do not name an explicit Slotui module and symbol.

        Raises:
            ValueError: If a capability declaration could be satisfied by an ambiguous export.
        """
        if any(not _is_module_qualified_export(declaration=export) for export in self.required_exports):
            raise ValueError("capability exports must be module-qualified Slotui declarations")
        return self


class SlotuiCoreExportDAO(BaseModel):
    """Declare one generic public symbol at one explicit Slotui module path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str = Field(pattern=_MODULE_PATTERN)
    symbol: str = Field(pattern=_SYMBOL_PATTERN)

    @property
    def declaration(self) -> str:
        """Return the immutable module-qualified declaration used by capabilities.

        Returns:
            str: ``slotui.<module>.<symbol>`` without importing Slotui.
        """
        return f"{self.module}.{self.symbol}"


class SlotuiCoreSourceIdentityDAO(BaseModel):
    """Record the independently supplied protected-source identity and clean assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    clean: Literal[True]


class SlotuiOpaqueEvidenceDAO(BaseModel):
    """Carry owner-produced opaque canonical JSON evidence without modelling its schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_json: str = Field(min_length=2)
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _require_exact_opaque_json_hash(self) -> "SlotuiOpaqueEvidenceDAO":
        """Require canonical JSON bytes and their opaque evidence digest.

        Raises:
            ValueError: If owner evidence is malformed, non-canonical, or unpinned.
        """
        try:
            payload: object = json.loads(self.canonical_json)
        except json.JSONDecodeError as error:
            raise ValueError("opaque Slotui evidence must contain JSON") from error
        canonical_json: str = _canonical_json(payload=payload)
        if self.canonical_json != canonical_json:
            raise ValueError("opaque Slotui evidence JSON must be canonical")
        actual_sha256: str = _sha256(value=self.canonical_json.encode("utf-8"))
        if actual_sha256 != self.sha256:
            raise ValueError("opaque Slotui evidence SHA-256 does not match its canonical JSON")
        return self


class SlotuiCoreTestReportHashDAO(BaseModel):
    """Pin one opaque owner-produced core test report without reproducing owner tests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)


class SlotuiCoreManifestDAO(BaseModel):
    """Describe Slo's strict b.0/b.0.1 adapter-fixture projection of a core release.

    This consumer contract records opaque evidence from the core owners.  It is
    deliberately not a replacement for a future Slotui b.1 owner schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["slo-slotui-adapter-fixture-v1"]
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
    b0_stream_schema: SlotuiOpaqueEvidenceDAO
    b0_1_live_transcript_evidence: SlotuiOpaqueEvidenceDAO
    core_test_report_hashes: tuple[SlotuiCoreTestReportHashDAO, ...] = Field(min_length=1)
    manifest_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_contract(self) -> "SlotuiCoreManifestDAO":
        """Reject incomplete, ambiguous, rich-only, or internally inconsistent fixtures.

        Raises:
            ValueError: If Slo cannot prove a closed generic adapter fixture contract.
        """
        self._require_exact_wheel_name()
        self._require_exact_capabilities()
        self._require_exact_generic_exports()
        self._require_export_signature_hash()
        self._require_unique_test_reports()
        return self

    def canonical_projection_bytes(self) -> bytes:
        """Return canonical manifest bytes excluding only the manifest's self hash.

        Returns:
            bytes: Deterministic UTF-8 projection used to verify ``manifest_sha256``.
        """
        projection: dict[str, object] = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return _canonical_json(payload=projection).encode("utf-8")

    def require_canonical_manifest_hash(self) -> None:
        """Verify this manifest's non-self-referential canonical projection hash.

        Raises:
            ValueError: If ``manifest_sha256`` is not the digest of every other field.
        """
        actual_sha256: str = _sha256(value=self.canonical_projection_bytes())
        if actual_sha256 != self.manifest_sha256:
            raise ValueError(
                "Slotui adapter fixture manifest SHA-256 does not match its canonical projection"
            )

    def _require_exact_wheel_name(self) -> None:
        """Require the declared version in the exact declared wheel filename.

        Raises:
            ValueError: If artifact identity can diverge from its version.
        """
        if not self.wheel_filename.startswith(f"slotui-{self.version}-"):
            raise ValueError("wheel_filename must contain the adapter fixture distribution version")

    def _require_exact_capabilities(self) -> None:
        """Require each and only each generic capability exactly once.

        Raises:
            ValueError: If required generic capability coverage is incomplete or duplicate.
        """
        names: tuple[str, ...] = tuple(capability.name for capability in self.capabilities)
        if tuple(sorted(names)) != tuple(sorted(REQUIRED_SLOTUI_CAPABILITIES)):
            raise ValueError("core capabilities must exactly match Slo's required generic capability list")

    def _require_exact_generic_exports(self) -> None:
        """Require one non-rich signature declaration for every claimed capability export.

        Raises:
            ValueError: If exports are duplicate, rich-only, or differ from the immutable signature.
        """
        signature_declarations: tuple[str, ...] = tuple(
            item.declaration for item in self.immutable_core_export_signature
        )
        capability_declarations: tuple[str, ...] = tuple(
            declaration for capability in self.capabilities for declaration in capability.required_exports
        )
        self._require_no_duplicate_declarations(declarations=signature_declarations, owner="export signature")
        self._require_no_duplicate_declarations(declarations=capability_declarations, owner="capabilities")
        if set(signature_declarations) != set(capability_declarations):
            raise ValueError("capability exports must exactly match the immutable core export signature")
        if any("rich" in declaration.lower() for declaration in signature_declarations):
            raise ValueError("adapter fixture export signature must not declare rich-only exports")

    def _require_export_signature_hash(self) -> None:
        """Require the canonical immutable export signature hash.

        Raises:
            ValueError: If the listed module-qualified exports are not digest-pinned.
        """
        signature: list[dict[str, str]] = [
            item.model_dump(mode="json") for item in self.immutable_core_export_signature
        ]
        actual_sha256: str = _sha256(value=_canonical_json(payload=signature).encode("utf-8"))
        if actual_sha256 != self.immutable_core_export_signature_sha256:
            raise ValueError(
                "immutable core export signature SHA-256 does not match its canonical declaration list"
            )

    def _require_unique_test_reports(self) -> None:
        """Require distinct opaque core test report names.

        Raises:
            ValueError: If report evidence is duplicated or rich-only.
        """
        report_names: tuple[str, ...] = tuple(item.report_name for item in self.core_test_report_hashes)
        if len(set(report_names)) != len(report_names):
            raise ValueError("core test report hashes may not contain duplicate report names")
        if any("rich" in report_name for report_name in report_names):
            raise ValueError("adapter fixture may not claim a rich-only core test report")

    @staticmethod
    def _require_no_duplicate_declarations(*, declarations: tuple[str, ...], owner: str) -> None:
        """Reject repeated declarations from one immutable fixture field.

        Args:
            declarations (tuple[str, ...]): Values whose uniqueness is required.
            owner (str): Human-readable manifest field name for the failure.

        Raises:
            ValueError: If an export declaration occurs more than once.
        """
        if len(set(declarations)) != len(declarations):
            raise ValueError(f"{owner} may not contain duplicate export declarations")


class SlotuiCoreVerificationReceiptDAO(BaseModel):
    """Record a static verification result; this scaffold never installs a wheel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: Literal["slotui"]
    version: str
    wheel_path: Path
    manifest: SlotuiCoreManifestDAO


class SlotuiPresentationSelectionDAO(BaseModel):
    """Carry an explicit interactive selection after static local verification only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    presentation: SlotuiPresentationName
    core_verification_receipt: SlotuiCoreVerificationReceiptDAO | None = None

    @model_validator(mode="after")
    def _require_receipt_only_for_core(self) -> "SlotuiPresentationSelectionDAO":
        """Keep current Textual selection independent of Slotui fixture artifacts.

        Raises:
            ValueError: If an opt-in receipt is absent or leaks into Textual selection.
        """
        if self.presentation == "slotui_core" and self.core_verification_receipt is None:
            raise ValueError("Slotui core selection requires a verified adapter fixture receipt")
        if self.presentation == "textual_current" and self.core_verification_receipt is not None:
            raise ValueError("Textual selection must not carry a Slotui verification receipt")
        return self


def _canonical_json(*, payload: object) -> str:
    """Serialize one already-typed fixture value in the contract's canonical JSON form.

    Args:
        payload (object): JSON-compatible typed fixture value.

    Returns:
        str: Sorted, compact JSON with stable Unicode spelling.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _is_module_qualified_export(*, declaration: str) -> bool:
    """Determine whether a capability export names an explicit valid Slotui module and symbol.

    Args:
        declaration (str): Manifest capability export declaration.

    Returns:
        bool: ``True`` only for ``slotui.<module>.<symbol>`` declarations.
    """
    module, separator, symbol = declaration.rpartition(".")
    return bool(
        separator and module and symbol and _matches_module(module=module) and _matches_symbol(symbol=symbol)
    )


def _matches_module(*, module: str) -> bool:
    """Determine whether a dotted module is confined to valid Slotui identifiers.

    Args:
        module (str): Dotted module declaration.

    Returns:
        bool: Whether the module starts with ``slotui`` and has valid segments.
    """
    segments: list[str] = module.split(".")
    return bool(
        segments and segments[0] == "slotui" and all(_is_identifier(value=segment) for segment in segments)
    )


def _matches_symbol(*, symbol: str) -> bool:
    """Determine whether an export symbol is a valid Python identifier.

    Args:
        symbol (str): Declared export symbol.

    Returns:
        bool: Whether the symbol can name a Python declaration.
    """
    return _is_identifier(value=symbol)


def _is_identifier(*, value: str) -> bool:
    """Determine whether a string is a lowercase-module or arbitrary-symbol identifier.

    Args:
        value (str): Identifier segment to validate.

    Returns:
        bool: Whether the segment is a non-keyword Python identifier.
    """
    return value.isidentifier() and not keyword.iskeyword(value)


def _sha256(*, value: bytes) -> str:
    """Return a lowercase SHA-256 digest for one immutable fixture byte sequence.

    Args:
        value (bytes): Bytes to pin.

    Returns:
        str: Lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(value).hexdigest()
