"""Tests for UserPreferencesDAO and UserPreferencesStore (26.a.1)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.preferences.dao import UserPreferencesDAO, UserPreferencesStoreCorruptError
from src.agents.slo_agent.preferences.service import UserPreferencesStore


class TestUserPreferencesStoreLoad:
    """``UserPreferencesStore.load`` — absent, valid, and corrupt paths."""

    def test_returns_empty_dao_when_file_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing file returns an all-None DAO without error."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))

        prefs: UserPreferencesDAO = UserPreferencesStore.load()

        assert prefs == UserPreferencesDAO()
        assert prefs.default_model_name is None
        assert prefs.default_reasoning_level is None

    def test_returns_parsed_dao_when_file_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid file is parsed into a populated DAO."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="claude-sonnet-4-5", reasoning_level="high")

        prefs: UserPreferencesDAO = UserPreferencesStore.load()

        assert prefs.default_model_name == "claude-sonnet-4-5"
        assert prefs.default_reasoning_level == "high"

    def test_raises_corrupt_error_on_invalid_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A malformed JSON file raises UserPreferencesStoreCorruptError."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(UserPreferencesStoreCorruptError) as exc_info:
            UserPreferencesStore.load()

        assert exc_info.value.path == path

    def test_raises_corrupt_error_on_schema_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file with wrong schema raises UserPreferencesStoreCorruptError."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        path.write_text(
            json.dumps({"schema_version": 1, "default_reasoning_level": "invalid_level"}),
            encoding="utf-8",
        )

        with pytest.raises(UserPreferencesStoreCorruptError):
            UserPreferencesStore.load()


class TestUserPreferencesStoreUpsert:
    """``UserPreferencesStore.upsert`` — write semantics and permissions."""

    def test_creates_file_with_mode_600(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The preferences file is written with 0600 permissions."""
        path: Path = tmp_path / "global" / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))

        UserPreferencesStore.upsert(model_name="gpt-5.4")

        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_creates_parent_dir_with_mode_700(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The parent directory is created with 0700 permissions."""
        path: Path = tmp_path / "global" / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))

        UserPreferencesStore.upsert(model_name="gpt-5.4")

        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_updates_model_name_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Updating model_name leaves reasoning_level unchanged."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="old-model", reasoning_level="medium")

        UserPreferencesStore.upsert(model_name="new-model")
        prefs: UserPreferencesDAO = UserPreferencesStore.load()

        assert prefs.default_model_name == "new-model"
        assert prefs.default_reasoning_level == "medium"

    def test_updates_reasoning_level_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Updating reasoning_level leaves model_name unchanged."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="claude-sonnet-4-5", reasoning_level="low")

        UserPreferencesStore.upsert(reasoning_level="high")
        prefs: UserPreferencesDAO = UserPreferencesStore.load()

        assert prefs.default_model_name == "claude-sonnet-4-5"
        assert prefs.default_reasoning_level == "high"

    def test_updates_both_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both fields can be updated in a single call."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))

        result: UserPreferencesDAO = UserPreferencesStore.upsert(
            model_name="claude-opus-4-5",
            reasoning_level="xhigh",
        )

        assert result.default_model_name == "claude-opus-4-5"
        assert result.default_reasoning_level == "xhigh"

    def test_none_args_leave_fields_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passing None for both args is a no-op (returns current prefs)."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="m1", reasoning_level="medium")

        result: UserPreferencesDAO = UserPreferencesStore.upsert()

        assert result.default_model_name == "m1"
        assert result.default_reasoning_level == "medium"


class TestUserPreferencesStoreClear:
    """``UserPreferencesStore.clear`` — file exists and absent paths."""

    def test_deletes_existing_file_returns_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting an existing file returns True."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="m1")

        result: bool = UserPreferencesStore.clear()

        assert result is True
        assert not path.exists()

    def test_returns_false_when_file_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Clear on a missing file returns False without error."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "nonexistent.json"))

        result: bool = UserPreferencesStore.clear()

        assert result is False

    def test_load_returns_empty_after_clear(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After clear, load returns an empty DAO."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))
        UserPreferencesStore.upsert(model_name="m1")
        UserPreferencesStore.clear()

        prefs: UserPreferencesDAO = UserPreferencesStore.load()

        assert prefs == UserPreferencesDAO()


class TestUserPreferencesStoreEnvOverride:
    """``SLO_PREFERENCES_FILE`` redirects the file path for tests."""

    def test_env_override_used_instead_of_default_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SLO_PREFERENCES_FILE must be used when set."""
        custom_path: Path = tmp_path / "custom_prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(custom_path))

        UserPreferencesStore.upsert(model_name="test-model")

        assert custom_path.exists()


# ---------------------------------------------------------------------------
# default_model_pool preference (review fix #8)
# ---------------------------------------------------------------------------


class TestUserPreferencesModelPool:
    """``default_model_pool`` round-trips through upsert/load and is preserved."""

    def test_upsert_sets_default_model_pool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """upsert(model_pool=...) persists the pool preference."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        UserPreferencesStore.upsert(model_pool="gpt-5.4,claude-sonnet-4-6")
        assert UserPreferencesStore.load().default_model_pool == "gpt-5.4,claude-sonnet-4-6"

    def test_upsert_preserves_model_pool_when_setting_other_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting model_name later does not wipe a stored pool preference."""
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
        UserPreferencesStore.upsert(model_pool="gpt-5.4,claude-sonnet-4-6")
        UserPreferencesStore.upsert(model_name="gpt-5.4")
        loaded = UserPreferencesStore.load()
        assert loaded.default_model_pool == "gpt-5.4,claude-sonnet-4-6"
        assert loaded.default_model_name == "gpt-5.4"


class TestUserPreferencesCanonicalMax:
    """Feature 83.a.1: canonical ``max`` is a valid persisted reasoning level."""

    def test_upsert_accepts_canonical_max_reasoning_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``max`` persists and reloads unchanged."""
        path: Path = tmp_path / "prefs.json"
        monkeypatch.setenv("SLO_PREFERENCES_FILE", str(path))

        result: UserPreferencesDAO = UserPreferencesStore.upsert(
            model_name="gpt-6-astra",
            reasoning_level="max",
        )

        assert result.default_model_name == "gpt-6-astra"
        assert result.default_reasoning_level == "max"

    def test_dao_rejects_invalid_reasoning_level(self) -> None:
        """Unknown reasoning tokens remain rejected by the shared literal."""
        with pytest.raises(ValidationError):
            UserPreferencesDAO(default_reasoning_level="ultra")  # type: ignore[arg-type]
