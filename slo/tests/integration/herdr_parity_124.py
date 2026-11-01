"""Strict ordered serialization oracle for the mounted parity family."""

import builtins
import io
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from src.agents.slo_agent.sessions.service import SloAgentSession

import pytest
from pydantic import BaseModel

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO


class IntegrationWriteAttempts:
    """Reject low-level mutations of one test-owned integration tree before I/O."""

    def __init__(self, *, home: Path, owned_root: Path) -> None:
        """Bind only a contained home; never accept a real host target."""
        root = owned_root.resolve(strict=True)
        assert home.resolve(strict=True).is_relative_to(root)
        assert not any(path.is_symlink() for path in (home, *home.parents))
        self._integration = home.resolve() / "integrations"
        self.attempts: list[tuple[str, str]] = []

    def install(self, *, monkeypatch: pytest.MonkeyPatch) -> None:
        """Observe Python filesystem mutation boundaries for the mounted lifetime."""
        for owner, names in (
            (os, ("mkdir", "open", "chmod", "rename", "replace", "unlink", "rmdir")),
            (io, ("open",)),
            (builtins, ("open",)),
        ):
            for name in names:
                original = cast(Callable[..., object], getattr(owner, name))
                monkeypatch.setattr(owner, name, self._wrap(name=name, original=original))

    def _wrap(self, *, name: str, original: Callable[..., object]) -> Callable[..., object]:
        """Record before denial so swallowed optional-integration errors remain visible."""

        def invoke(*args: object, **kwargs: object) -> object:
            """Delegate unrelated history I/O unchanged; reject scoped attempts."""
            paths = args[:2] if name in ("rename", "replace") else args[:1]
            for value in paths:
                if not isinstance(value, (str, bytes, os.PathLike)):
                    continue
                path = Path(os.fsdecode(value)).absolute()
                if path == self._integration or path.is_relative_to(self._integration):
                    self.attempts.append((name, str(path)))
                    raise OSError("controlled integration I/O denial")
            return original(*args, **kwargs)

        return invoke

    def assert_unused(self) -> None:
        """Assert after isolated callbacks and teardown, never inside them."""
        assert not self.attempts, f"integration I/O attempts: {self.attempts}"


class ReportingCredentialBlockers:
    """Record forbidden lookup attempts throughout an admitted reporter lifetime."""

    def __init__(self) -> None:
        """Retain independent call evidence beyond optional callback containment."""
        self.calls: dict[str, MagicMock] = {}

    def install(self, *, stack: ExitStack) -> None:
        """Block lookup and refresh only after ordinary session/factory admission.

        Args:
            stack: Caller-owned scope spanning async save, wire, rotation and drain.
        """
        for owner, names in (
            (
                CredentialResolver,
                (
                    "resolve",
                    "resolve_with_source",
                    "require",
                    "_from_env",
                    "_from_store",
                    "_from_legacy_claude",
                ),
            ),
            (CredentialStore, ("load", "_load_owned", "_read_envelope", "_parse_existing", "persist")),
            (SloAgentSession, ("_refresh_oauth_credential_if_needed",)),
        ):
            for name in names:
                self.calls[f"{owner.__name__}.{name}"] = stack.enter_context(
                    patch.object(owner, name, side_effect=AssertionError("reporter credential access"))
                )
        self.calls["refresh_if_stale"] = stack.enter_context(
            patch(
                "src.auth.credential_refresher.refresh_if_stale",
                side_effect=AssertionError("reporter refresh"),
            )
        )

    def assert_unused(self) -> None:
        """Check recorded calls outside all isolated reporting callbacks."""
        assert not {name: spy.call_count for name, spy in self.calls.items() if spy.called}


class SemanticTrace:
    """Normalize schema-owned identities, never matching keys in arbitrary payloads."""

    def __init__(self) -> None:
        """Create a per-journey identity map shared by events and durable history."""
        self._identities: dict[str, str] = {}

    def serialize(self, *, records: list[BaseModel]) -> list[object]:
        """Retain ordered complete records, changing only known generated fields.

        Args:
            records: Actual stream or loaded durable history records.

        Returns:
            Full JSON-shaped values with identity references consistently renamed.

        Raises:
            TypeError: A record has no reviewed normalization schema.
        """
        return [self._record(record=record) for record in records]

    def _record(self, *, record: BaseModel) -> dict[str, object]:
        """Apply an explicit schema path allowlist to a fresh serialized copy."""
        value = record.model_dump(mode="json")
        if isinstance(record, AgentStreamEventDAO):
            value["block_id"] = self._identity(value=value["block_id"])
            return value
        if not isinstance(record, SessionHistoryEventDAO):
            raise TypeError("Unreviewed parity record schema")
        for key in ("session_id", "event_id", "turn_id"):
            value[key] = self._identity(value=value[key])
        value["recorded_at"] = "<wall-clock>"
        payload = value["payload"]
        payload["block_id"] = self._identity(value=payload["block_id"])
        metadata = payload["metadata"]
        for key in ("entry_id", "parent_entry_id"):
            if key in metadata:
                metadata[key] = self._identity(value=metadata[key])
        return value

    def _identity(self, *, value: object) -> str | None:
        """Preserve null and reference topology across the complete journey."""
        if value is None:
            return None
        assert isinstance(value, str)
        return self._identities.setdefault(value, f"<identity-{len(self._identities)}>")
