"""Immutable local artifact and selection contracts for Slotui core consumption."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "REQUIRED_SLOTUI_CAPABILITIES",
    "SlotuiCoreArtifactReferenceDAO",
    "SlotuiCoreCapabilityDAO",
    "SlotuiCoreInstallationPlanDAO",
    "SlotuiCoreManifestDAO",
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
"""Closed capability vocabulary required before an opt-in core can be used."""

SlotuiPresentationName = Literal["textual_current", "slotui_core"]
"""Operator-selected interactive presentation names; Textual remains the default."""


class SlotuiCoreArtifactReferenceDAO(BaseModel):
    """Pin one typed core-manifest fixture by absolute local path and SHA-256."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_path: Path
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_absolute_manifest_path(self) -> "SlotuiCoreArtifactReferenceDAO":
        """Reject a relative manifest reference before the release proof is read.

        Raises:
            ValueError: If the reference cannot identify an immutable local file.
        """
        if not self.manifest_path.is_absolute():
            raise ValueError("Slotui core manifest path must be absolute")
        return self


class SlotuiCoreCapabilityDAO(BaseModel):
    """Declare the public symbols required for one core integration capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    required_exports: tuple[str, ...] = Field(min_length=1)


class SlotuiCoreManifestDAO(BaseModel):
    """Represent exact bytes and public contract supplied by protected core release CI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["slotui-core-release-manifest-v1"]
    distribution_name: Literal["slotui"]
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    wheel_filename: str = Field(pattern=r"^slotui-[0-9]+\.[0-9]+\.[0-9]+-[A-Za-z0-9_.-]+\.whl$")
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wheel_artifact: dict[Literal["source"], str]
    export_surface: tuple[str, ...] = Field(min_length=1)
    capabilities: tuple[SlotuiCoreCapabilityDAO, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_contract(self) -> "SlotuiCoreManifestDAO":
        """Require exact capability coverage and exports before wheel inspection.

        Raises:
            ValueError: If capability names, exports, or wheel naming are not immutable.
        """
        self._require_exact_wheel_name()
        self._require_exact_capabilities()
        self._require_capability_exports()
        return self

    def _require_exact_wheel_name(self) -> None:
        """Require the declared version in the exact declared wheel filename.

        Raises:
            ValueError: If the version and artifact filename can diverge.
        """
        expected_prefix: str = f"slotui-{self.version}-"
        if not self.wheel_filename.startswith(expected_prefix):
            raise ValueError("wheel_filename must contain the manifest distribution version")

    def _require_exact_capabilities(self) -> None:
        """Require each and only each mandatory capability name.

        Raises:
            ValueError: If the core contract is incomplete, duplicate, or expanded silently.
        """
        names: tuple[str, ...] = tuple(capability.name for capability in self.capabilities)
        if tuple(sorted(names)) != tuple(sorted(REQUIRED_SLOTUI_CAPABILITIES)):
            raise ValueError("core capabilities must exactly match the required capability manifest")

    def _require_capability_exports(self) -> None:
        """Require every capability's public symbols in the global export surface.

        Raises:
            ValueError: If a claimed capability has an unavailable required export.
        """
        export_surface: set[str] = set(self.export_surface)
        if len(export_surface) != len(self.export_surface):
            raise ValueError("export_surface may not contain duplicates")
        for capability in self.capabilities:
            if not set(capability.required_exports).issubset(export_surface):
                raise ValueError(f"capability exports are missing from export_surface: {capability.name}")


class SlotuiCoreInstallationPlanDAO(BaseModel):
    """Describe a safe no-index installation to execute only in a fresh release venv."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_name: Literal["slotui"]
    version: str
    wheel_path: Path
    manifest: SlotuiCoreManifestDAO
    argv: tuple[str, ...]


class SlotuiPresentationSelectionDAO(BaseModel):
    """Carry explicit interactive presentation selection after local core verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    presentation: SlotuiPresentationName
    core_installation_plan: SlotuiCoreInstallationPlanDAO | None = None

    @model_validator(mode="after")
    def _require_plan_only_for_core(self) -> "SlotuiPresentationSelectionDAO":
        """Keep Textual selection independent of all Slotui release artifacts.

        Raises:
            ValueError: If a core plan is absent for opt-in or leaks into Textual.
        """
        if self.presentation == "slotui_core" and self.core_installation_plan is None:
            raise ValueError("Slotui core selection requires a verified installation plan")
        if self.presentation == "textual_current" and self.core_installation_plan is not None:
            raise ValueError("Textual selection must not carry a Slotui installation plan")
        return self
