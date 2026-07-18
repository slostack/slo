"""Tests for model catalog cache and override store."""

from __future__ import annotations

import json

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.store import ModelCatalogStore


class TestModelCatalogStoreCache:
    """Cache persistence round-trips."""

    def test_missing_cache_returns_none(self, tmp_path) -> None:
        """A missing cache file returns None rather than crashing."""
        cache_path = tmp_path / "missing.json"

        result = ModelCatalogStore.load_cache(override_path=cache_path)

        assert result is None

    def test_invalid_cache_returns_none(self, tmp_path) -> None:
        """A corrupt cache file is logged and returns None."""
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("not-json", encoding="utf-8")

        result = ModelCatalogStore.load_cache(override_path=cache_path)

        assert result is None

    def test_write_cache_round_trips(self, tmp_path) -> None:
        """A written snapshot can be reloaded."""
        snapshot = SeedModelCatalog.load()
        cache_path = tmp_path / "cache.json"

        ModelCatalogStore.write_cache(snapshot=snapshot, override_path=cache_path)
        loaded = ModelCatalogStore.load_cache(override_path=cache_path)

        assert loaded is not None
        assert loaded.entries.keys() == snapshot.entries.keys()

    def test_schema_version_mismatch_returns_none(self, tmp_path) -> None:
        """A cache with a future schema version is rejected."""
        cache_path = tmp_path / "cache.json"
        snapshot = SeedModelCatalog.load()
        data = json.loads(snapshot.model_dump_json())
        data["schema_version"] = "99"
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        loaded = ModelCatalogStore.load_cache(override_path=cache_path)

        assert loaded is None


class TestModelCatalogStoreOverrides:
    """Operator override file loading."""

    def test_missing_overrides_returns_empty(self, tmp_path) -> None:
        """A missing override file yields an empty list."""
        overrides_path = tmp_path / "missing_overrides.json"

        result = ModelCatalogStore.load_overrides(override_path=overrides_path)

        assert result == []

    def test_overrides_load_from_file(self, tmp_path) -> None:
        """A valid override file parses into typed DAOs."""
        overrides_path = tmp_path / "overrides.json"
        overrides = [
            {
                "model_name": "claude-mythos",
                "visible_in_picker": True,
            },
        ]
        overrides_path.write_text(json.dumps(overrides), encoding="utf-8")

        result = ModelCatalogStore.load_overrides(override_path=overrides_path)

        assert len(result) == 1
        assert result[0].model_name == "claude-mythos"
        assert result[0].visible_in_picker is True

    def test_invalid_overrides_returns_empty(self, tmp_path) -> None:
        """A corrupt override file is logged and returns an empty list."""
        overrides_path = tmp_path / "overrides.json"
        overrides_path.write_text("not-json", encoding="utf-8")

        result = ModelCatalogStore.load_overrides(override_path=overrides_path)

        assert result == []

    def test_non_list_overrides_returns_empty(self, tmp_path) -> None:
        """An override file that is not a JSON list is rejected."""
        overrides_path = tmp_path / "overrides.json"
        overrides_path.write_text(json.dumps({"model_name": "x"}), encoding="utf-8")

        result = ModelCatalogStore.load_overrides(override_path=overrides_path)

        assert result == []

    def test_env_override_overrides_default_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """SLO_MODEL_CATALOG_OVERRIDES_FILE redirects the overrides path."""
        overrides_path = tmp_path / "custom_overrides.json"
        overrides_path.write_text(
            '[{"model_name":"claude-mythos","visible_in_picker":true}]',
            encoding="utf-8",
        )
        monkeypatch.setenv("SLO_MODEL_CATALOG_OVERRIDES_FILE", str(overrides_path))

        result = ModelCatalogStore.load_overrides()

        assert len(result) == 1
        assert result[0].model_name == "claude-mythos"
        assert result[0].visible_in_picker is True

    def test_cache_fresh_within_ttl(self) -> None:
        """A snapshot generated now is considered fresh."""
        snapshot = SeedModelCatalog.load()
        assert ModelCatalogStore.is_cache_fresh(snapshot=snapshot) is True

    def test_cache_stale_past_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A snapshot older than the TTL is considered stale."""
        from datetime import datetime, timedelta, timezone

        snapshot = SeedModelCatalog.load()
        old_generated_at = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        old_snapshot = snapshot.model_copy(update={"generated_at": old_generated_at})
        assert ModelCatalogStore.is_cache_fresh(snapshot=old_snapshot) is False
