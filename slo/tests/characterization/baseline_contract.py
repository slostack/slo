"""Immutable baseline fixture comparison contracts for Slo integration characterization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "BaselineCaseDAO",
    "BaselineComparator",
    "BaselineLedgerDAO",
    "BaselineLedgerEntryDAO",
]

_RELEASE_DOCUMENTATION_MAINTAINER_ROLE: Literal["Slo release/documentation maintainer"] = (
    "Slo release/documentation maintainer"
)


class BaselineCaseDAO(BaseModel):
    """Identify one exact Slo behavior capture and its immutable fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    normalizer_version: Literal["v1"]


class BaselineLedgerEntryDAO(BaseModel):
    """Record a reviewed exception to byte-equal baseline comparison.

    WHAT: Holds the documented approval required before one named baseline may
        differ at listed JSON pointers.
    WHO: The Slo release/documentation maintainer creates this record after
        reviewing the raw capture and replacement artifact.
    WHEN: Only while a migration changes a known behavior intentionally; it is
        removed once the listed removal condition has been satisfied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    normalizer_version: Literal["v1"]
    approved_by_role: Literal["Slo release/documentation maintainer"]
    approved_at: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    allowed_json_pointer_differences: list[str] = Field(default_factory=list)
    removal_condition: str = Field(min_length=1)


class BaselineLedgerDAO(BaseModel):
    """Contain reviewed baseline deviations without allowing untracked cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: list[BaselineLedgerEntryDAO] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_duplicate_case_ids(self) -> "BaselineLedgerDAO":
        """Reject multiple approvals for one baseline case.

        WHAT: Preserves one authoritative approval record per characterized
            surface.
        WHO: Called by Pydantic whenever the fixture ledger is parsed.
        WHEN: Before a comparator examines a potential baseline difference.

        Returns:
            BaselineLedgerDAO: The validated ledger.

        Raises:
            ValueError: If more than one entry names the same case id.
        """
        case_ids: list[str] = [entry.case_id for entry in self.entries]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("baseline ledger may contain only one entry per case_id")
        return self

    def entry_for(self, *, case: BaselineCaseDAO) -> BaselineLedgerEntryDAO | None:
        """Return the sole ledger entry matching one baseline case.

        WHAT: Finds the narrow approval that can authorize a difference for the
            requested fixture.
        WHO: BaselineComparator calls this before failing an unequal capture.
        WHEN: Only after normalized observed and expected bytes differ.

        Args:
            case (BaselineCaseDAO): The exact named baseline being compared.

        Returns:
            BaselineLedgerEntryDAO | None: Matching approved deviation, if any.
        """
        for entry in self.entries:
            if entry.case_id == case.case_id:
                return entry
        return None


class BaselineComparator:
    """Compare normalized behavior captures against exact seeded fixtures."""

    @classmethod
    def load_ledger(cls, *, ledger_path: Path) -> BaselineLedgerDAO:
        """Load one explicit baseline ledger from its committed fixture path.

        WHAT: Parses the sensitive-free JSON ledger into its strict Pydantic DAO.
        WHO: Each characterization test uses it before comparing a capture.
        WHEN: Once per test invocation after direct capture normalization.

        Args:
            ledger_path (Path): Exact committed baseline-ledger JSON path.

        Returns:
            BaselineLedgerDAO: Validated ledger content.
        """
        raw_ledger: str = ledger_path.read_text(encoding="utf-8")
        return BaselineLedgerDAO.model_validate_json(raw_ledger)

    @classmethod
    def compare(
        cls,
        *,
        case: BaselineCaseDAO,
        observed: bytes,
        expected: bytes,
        ledger: BaselineLedgerDAO,
    ) -> None:
        """Reject unapproved normalized capture differences.

        WHAT: Enforces byte equality by default, allowing only a ledger record
            whose case, artifact, normalizer, editor role, and removal condition
            all match the requested comparison.
        WHO: Every b.2 exercise test calls this after its direct normalizer call.
        WHEN: At the final assertion point for each current-Slo surface.

        Args:
            case (BaselineCaseDAO): Identifier and fixture contract for the capture.
            observed (bytes): Fresh normalized behavior capture.
            expected (bytes): Seeded normalized artifact bytes.
            ledger (BaselineLedgerDAO): Reviewed deviation approvals.

        Raises:
            AssertionError: If bytes differ without an exact valid approval.
        """
        if observed == expected:
            return
        entry: BaselineLedgerEntryDAO | None = ledger.entry_for(case=case)
        cls._assert_approved_difference(case=case, entry=entry)
        cls._assert_allowed_json_difference(observed=observed, expected=expected, entry=entry)

    @classmethod
    def _assert_approved_difference(
        cls,
        *,
        case: BaselineCaseDAO,
        entry: BaselineLedgerEntryDAO | None,
    ) -> None:
        """Validate the ledger identity and editor policy for one difference.

        WHAT: Confirms that only the named release/documentation maintainer can
            authorize a deviation for the exact case and artifact.
        WHO: compare calls it when byte equality failed.
        WHEN: Before inspecting JSON pointer differences.

        Args:
            case (BaselineCaseDAO): Capture contract whose bytes differed.
            entry (BaselineLedgerEntryDAO | None): Candidate ledger approval.

        Raises:
            AssertionError: If no exact legitimate approval exists.
        """
        if entry is None:
            raise AssertionError(f"unapproved baseline difference for {case.case_id}")
        if entry.artifact_path != case.artifact_path:
            raise AssertionError(f"ledger artifact_path does not match case {case.case_id}")
        if entry.normalizer_version != case.normalizer_version:
            raise AssertionError(f"ledger normalizer_version does not match case {case.case_id}")
        if entry.approved_by_role != _RELEASE_DOCUMENTATION_MAINTAINER_ROLE:
            raise AssertionError(f"ledger editor role is invalid for {case.case_id}")
        if not entry.approved_at.strip():
            raise AssertionError(f"ledger approved_at is required for {case.case_id}")
        if not entry.rationale.strip():
            raise AssertionError(f"ledger rationale is required for {case.case_id}")
        if not entry.removal_condition.strip():
            raise AssertionError(f"ledger removal_condition is required for {case.case_id}")

    @classmethod
    def _assert_allowed_json_difference(
        cls,
        *,
        observed: bytes,
        expected: bytes,
        entry: BaselineLedgerEntryDAO | None,
    ) -> None:
        """Reject any difference outside the explicitly approved JSON pointers.

        WHAT: Compares parsed JSON values after removing only approved pointer
            locations from both copies.
        WHO: compare calls it after validating a ledger approval.
        WHEN: Only for a non-byte-equal JSON fixture capture.

        Args:
            observed (bytes): Fresh normalized JSON capture.
            expected (bytes): Seeded normalized JSON fixture.
            entry (BaselineLedgerEntryDAO | None): Already-validated approval.

        Raises:
            AssertionError: If the capture is JSONL/non-JSON, has no approved
                pointers, or differs outside its declared pointer set.
        """
        assert entry is not None
        if not entry.allowed_json_pointer_differences:
            raise AssertionError(f"ledger permits no differences for {entry.case_id}")
        observed_json: object = cls._load_json_for_ledger(value=observed)
        expected_json: object = cls._load_json_for_ledger(value=expected)
        for pointer in entry.allowed_json_pointer_differences:
            cls._remove_json_pointer(value=observed_json, pointer=pointer)
            cls._remove_json_pointer(value=expected_json, pointer=pointer)
        if observed_json != expected_json:
            raise AssertionError(f"baseline difference exceeds ledger approval for {entry.case_id}")

    @staticmethod
    def _load_json_for_ledger(*, value: bytes) -> object:
        """Decode one JSON artifact used by the narrow ledger exception path.

        WHAT: Rejects non-JSON values because JSON pointers cannot safely
            authorize arbitrary byte or JSONL differences.
        WHO: _assert_allowed_json_difference calls it for both comparison sides.
        WHEN: Only after an explicit ledger entry requested pointer approval.

        Args:
            value (bytes): UTF-8 JSON bytes.

        Returns:
            object: Parsed JSON value.

        Raises:
            AssertionError: If the bytes are not a single JSON document.
        """
        try:
            return json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssertionError("ledger JSON pointer approvals require a JSON artifact") from error

    @staticmethod
    def _remove_json_pointer(*, value: object, pointer: str) -> None:
        """Remove one RFC-6901-style object member or array element.

        WHAT: Deletes an explicitly approved leaf so remaining behavior still
            compares exactly.
        WHO: _assert_allowed_json_difference invokes it for both JSON trees.
        WHEN: During a reviewed deviation comparison only.

        Args:
            value (object): Parsed JSON document to mutate locally.
            pointer (str): Absolute JSON pointer naming a permitted leaf.

        Raises:
            AssertionError: If the pointer is malformed or names no leaf.
        """
        path_segments: list[str] = BaselineComparator._json_pointer_segments(pointer=pointer)
        parent: object = BaselineComparator._json_pointer_parent(
            value=value, path_segments=path_segments, pointer=pointer
        )
        BaselineComparator._remove_json_pointer_leaf(
            parent=parent,
            segment=path_segments[-1],
            pointer=pointer,
        )

    @staticmethod
    def _json_pointer_segments(*, pointer: str) -> list[str]:
        """Parse one non-root RFC-6901 pointer into decoded path segments.

        Args:
            pointer (str): Absolute pointer naming one approved difference.

        Returns:
            list[str]: Decoded nonempty pointer segments.

        Raises:
            AssertionError: If the pointer is root or malformed.
        """
        if not pointer.startswith("/") or pointer == "/":
            raise AssertionError("allowed JSON pointer must name a non-root leaf")
        return [segment.replace("~1", "/").replace("~0", "~") for segment in pointer[1:].split("/")]

    @staticmethod
    def _json_pointer_parent(*, value: object, path_segments: list[str], pointer: str) -> object:
        """Resolve the container that owns one JSON-pointer leaf.

        Args:
            value (object): Parsed JSON document.
            path_segments (list[str]): Decoded pointer segments including the leaf.
            pointer (str): Original pointer retained for diagnostics.

        Returns:
            object: Mapping or array containing the requested leaf.

        Raises:
            AssertionError: If an intermediate segment is absent or invalid.
        """
        parent: object = value
        for segment in path_segments[:-1]:
            parent = BaselineComparator._json_pointer_child(parent=parent, segment=segment, pointer=pointer)
        return parent

    @staticmethod
    def _json_pointer_child(*, parent: object, segment: str, pointer: str) -> object:
        """Return one intermediate object or array child for a JSON pointer.

        Args:
            parent (object): Current object or array in the parsed document.
            segment (str): Decoded object key or array index.
            pointer (str): Original pointer retained for diagnostics.

        Returns:
            object: The resolved next-level value.

        Raises:
            AssertionError: If the child does not exist.
        """
        if isinstance(parent, dict) and segment in parent:
            return parent[segment]
        if isinstance(parent, list):
            index: int = BaselineComparator._json_pointer_index(segment=segment, pointer=pointer)
            if 0 <= index < len(parent):
                return parent[index]
        raise AssertionError(f"approved JSON pointer is absent: {pointer}")

    @staticmethod
    def _remove_json_pointer_leaf(*, parent: object, segment: str, pointer: str) -> None:
        """Delete a leaf from its resolved JSON object or array parent.

        Args:
            parent (object): Mapping or array that owns the approved leaf.
            segment (str): Decoded object key or array index.
            pointer (str): Original pointer retained for diagnostics.

        Raises:
            AssertionError: If the requested leaf does not exist.
        """
        if isinstance(parent, dict) and segment in parent:
            del parent[segment]
            return
        if isinstance(parent, list):
            index: int = BaselineComparator._json_pointer_index(segment=segment, pointer=pointer)
            if 0 <= index < len(parent):
                del parent[index]
                return
        raise AssertionError(f"approved JSON pointer is absent: {pointer}")

    @staticmethod
    def _json_pointer_index(*, segment: str, pointer: str) -> int:
        """Validate and convert one array-index pointer segment.

        Args:
            segment (str): Candidate RFC-6901 array index.
            pointer (str): Original pointer retained for diagnostics.

        Returns:
            int: Non-negative integer index without leading zero ambiguity.

        Raises:
            AssertionError: If the segment is not a valid array index.
        """
        if not segment.isdigit() or (len(segment) > 1 and segment.startswith("0")):
            raise AssertionError(f"approved JSON pointer is absent: {pointer}")
        return int(segment)
