"""Tests for src/cli/headless_request.py.

Decision points covered:
- validate_session_id: UUID4 / slug / path-separator / traversal / empty / non-string
- resolve_session_id: resume wins / explicit wins / env fallback / all-None
- _session_id_from_env: absent / empty / valid / invalid
- HeadlessRunRequestDAO: valid construction / invalid session_id field
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest

from src.cli.headless_request import (
    HeadlessRunRequestDAO,
    resolve_session_id,
    validate_session_id,
)


# ---------------------------------------------------------------------------
# validate_session_id
# ---------------------------------------------------------------------------


class TestValidateSessionId:
    def test_accepts_valid_uuid4(self) -> None:
        uid: str = str(uuid4())
        result: str = validate_session_id(value=uid)
        assert result == uid.lower()

    def test_normalises_uuid_to_lowercase(self) -> None:
        uid: str = str(uuid4()).upper()
        result: str = validate_session_id(value=uid)
        assert result == uid.lower()

    def test_accepts_slug_with_letters_digits_dots_dashes_underscores(self) -> None:
        slug: str = "my-task_run.1"
        result: str = validate_session_id(value=slug)
        assert result == slug

    def test_raises_for_empty_string(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_session_id(value="")

    def test_raises_for_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_session_id(value="   ")

    def test_raises_for_forward_slash(self) -> None:
        with pytest.raises(ValueError, match="path separators"):
            validate_session_id(value="some/id")

    def test_raises_for_backslash(self) -> None:
        with pytest.raises(ValueError, match="path separators"):
            validate_session_id(value="some\\id")

    def test_raises_for_dotdot_traversal(self) -> None:
        with pytest.raises(ValueError, match="traversal component"):
            validate_session_id(value="valid..but-traversal")

    def test_raises_for_invalid_slug_characters(self) -> None:
        with pytest.raises(ValueError, match=r"\[A-Za-z0-9\._-\]\+"):
            validate_session_id(value="invalid slug!")

    def test_raises_for_slug_with_space(self) -> None:
        with pytest.raises(ValueError, match=r"\[A-Za-z0-9\._-\]\+"):
            validate_session_id(value="has space")

    def test_strips_surrounding_whitespace_before_checking(self) -> None:
        uid: str = str(uuid4())
        result: str = validate_session_id(value=f"  {uid}  ")
        assert result == uid.lower()


# ---------------------------------------------------------------------------
# resolve_session_id
# ---------------------------------------------------------------------------


class TestResolveSessionId:
    def test_resume_wins_over_explicit(self) -> None:
        resume_id: str = str(uuid4())
        explicit_id: str = str(uuid4())
        result: Optional[str] = resolve_session_id(
            resume_session_id=resume_id,
            explicit_session_id=explicit_id,
        )
        assert result == resume_id

    def test_explicit_wins_when_resume_absent(self) -> None:
        explicit_id: str = str(uuid4())
        result: Optional[str] = resolve_session_id(
            resume_session_id=None,
            explicit_session_id=explicit_id,
        )
        assert result == explicit_id

    def test_env_fallback_when_both_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_id: str = str(uuid4())
        monkeypatch.setenv("SLO_SESSION_ID", env_id)
        result: Optional[str] = resolve_session_id(
            resume_session_id=None,
            explicit_session_id=None,
        )
        assert result == env_id.lower()

    def test_returns_none_when_all_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_SESSION_ID", raising=False)
        result: Optional[str] = resolve_session_id(
            resume_session_id=None,
            explicit_session_id=None,
        )
        assert result is None

    def test_env_absent_and_both_none_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_SESSION_ID", "  ")
        result: Optional[str] = resolve_session_id(
            resume_session_id=None,
            explicit_session_id=None,
        )
        assert result is None

    def test_raises_for_invalid_env_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_SESSION_ID", "bad/value")
        with pytest.raises(ValueError, match="path separators"):
            resolve_session_id(
                resume_session_id=None,
                explicit_session_id=None,
            )


# ---------------------------------------------------------------------------
# HeadlessRunRequestDAO
# ---------------------------------------------------------------------------


class TestHeadlessRunRequestDAO:
    def test_constructs_with_minimal_fields(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(prompt="do something")
        assert dao.prompt == "do something"
        assert dao.as_json is True
        assert dao.model is None
        assert dao.session_id is None
        assert dao.orchestrator_mode is False

    def test_accepts_valid_session_id(self) -> None:
        uid: str = str(uuid4())
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(
            prompt="task",
            session_id=uid,
        )
        assert dao.session_id == uid.lower()

    def test_accepts_slug_session_id(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(
            prompt="task",
            session_id="my-run.1",
        )
        assert dao.session_id == "my-run.1"

    def test_rejects_path_traversal_in_session_id(self) -> None:
        with pytest.raises(Exception):
            HeadlessRunRequestDAO(
                prompt="task",
                session_id="../evil",
            )

    def test_rejects_slash_in_session_id(self) -> None:
        with pytest.raises(Exception):
            HeadlessRunRequestDAO(
                prompt="task",
                session_id="foo/bar",
            )

    def test_accepts_workspace_file_as_path(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(
            prompt="task",
            workspace_file=Path("/tmp/test.code-workspace"),
        )
        assert dao.workspace_file == Path("/tmp/test.code-workspace")

    def test_orchestrator_mode_defaults_false(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(prompt="task")
        assert dao.orchestrator_mode is False

    def test_orchestrator_mode_can_be_set_true(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(
            prompt="task",
            orchestrator_mode=True,
        )
        assert dao.orchestrator_mode is True

    def test_enable_history_implied_by_resume_is_caller_responsibility(self) -> None:
        dao: HeadlessRunRequestDAO = HeadlessRunRequestDAO(
            prompt="task",
            resume_session_reference="some-ref",
            enable_history=True,
        )
        assert dao.resume_session_reference == "some-ref"
        assert dao.enable_history is True
