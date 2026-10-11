"""Tests for model catalog cache and override store."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

import src.agents.model_catalog.store as store_module

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.store import ModelCatalogRefreshLeaseUnavailableError, ModelCatalogStore
from src.auth.credential_dao import ProviderName


class TestModelCatalogStoreCache:
    """Cache persistence round-trips."""

    def test_merged_snapshot_writer_is_removed(self) -> None:
        """Only raw provider slices can be persisted; overrides cannot be baked in."""
        assert not hasattr(ModelCatalogStore, "write_cache")

    def test_schema_two_provider_cache_round_trips_without_merged_snapshot(self, tmp_path) -> None:
        """Schema two preserves a raw OpenRouter slice independently of overrides."""
        from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO

        cache_path = tmp_path / "cache.json"
        entry = (
            SeedModelCatalog.load()
            .entries["gpt-5.5"]
            .model_copy(update={"model_name": "openrouter:vendor/model", "api_model_name": "vendor/model"})
        )
        cache = ModelCatalogCacheDAO(
            provider_slices=[
                ProviderCatalogCacheDAO(
                    provider=ProviderName.OPENROUTER,
                    credential_fingerprint="fingerprint",
                    entries=[entry],
                )
            ]
        )

        outcome = ModelCatalogStore.write_provider_cache(cache=cache, override_path=cache_path)
        loaded = ModelCatalogStore.load_provider_cache(override_path=cache_path)

        assert outcome.committed is True
        assert loaded is not None
        assert loaded.provider_slices[0].entries[0].model_name == "openrouter:vendor/model"


class TestModelCatalogStoreRefreshLease:
    """Private refresh-lease descriptor ownership."""

    async def test_refresh_lease_closes_late_descriptor_when_cancelled_during_off_loop_open(
        self, tmp_path: Path
    ) -> None:
        """Cancellation drains and closes a descriptor opened after the waiter exits."""
        cache_path = tmp_path / "catalog.json"
        assert cache_path.resolve().is_relative_to(tmp_path.resolve())
        opened = Event()
        release = Event()
        descriptors: list[int] = []
        original_open = store_module._open_private_lock_file

        def blocked_open(*, cache_path: Path) -> int:
            """Open only under the verified root after the test permits completion."""
            descriptor = original_open(cache_path=cache_path)
            descriptors.append(descriptor)
            opened.set()
            assert release.wait(timeout=5)
            return descriptor

        with patch.object(store_module, "_open_private_lock_file", side_effect=blocked_open):
            task = asyncio.create_task(self._enter_refresh_lease(cache_path=cache_path))
            await asyncio.to_thread(opened.wait, 5)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert len(descriptors) == 1
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
        async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
            pass

    async def test_open_private_lock_file_closes_descriptor_when_chmod_fails(self, tmp_path: Path) -> None:
        """A post-open permissions failure closes the private descriptor before raising."""
        cache_path = tmp_path / "catalog.json"
        assert cache_path.resolve().is_relative_to(tmp_path.resolve())
        descriptors: list[int] = []
        original_open = store_module.os.open

        def recording_open(path: Path, flags: int, mode: int) -> int:
            """Record the owned descriptor without redirecting the test-owned target."""
            descriptor = original_open(path, flags, mode)
            descriptors.append(descriptor)
            return descriptor

        original_chmod = store_module.os.chmod
        chmod_calls = 0

        def failing_lock_chmod(path: Path, mode: int) -> None:
            """Allow parent privacy setup, then fail after the lock descriptor exists."""
            nonlocal chmod_calls
            chmod_calls += 1
            if chmod_calls == 2:
                raise OSError("chmod failure")
            original_chmod(path, mode)

        with (
            patch.object(store_module.os, "open", side_effect=recording_open),
            patch.object(store_module.os, "chmod", side_effect=failing_lock_chmod),
        ):
            with pytest.raises(ModelCatalogRefreshLeaseUnavailableError):
                store_module._open_private_lock_file(cache_path=cache_path)

        assert len(descriptors) == 1
        with pytest.raises(OSError):
            os.fstat(descriptors[0])

    async def test_refresh_lease_closes_descriptor_when_flock_raises_unexpected_error(
        self, tmp_path: Path
    ) -> None:
        """An unexpected advisory-lock failure releases the descriptor for a later acquisition."""
        cache_path = tmp_path / "catalog.json"
        assert cache_path.resolve().is_relative_to(tmp_path.resolve())
        assert store_module._fcntl is not None
        original_flock = store_module._fcntl.flock
        calls = 0

        def failing_once_flock(descriptor: int, operation: int) -> None:
            """Fail the acquisition once, then leave the genuine lock implementation intact."""
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("unexpected flock failure")
            original_flock(descriptor, operation)

        with patch.object(store_module._fcntl, "flock", side_effect=failing_once_flock):
            with pytest.raises(RuntimeError, match="unexpected flock failure"):
                async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
                    pytest.fail("unexpected flock failure acquired the lease")

        async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
            pass

    @staticmethod
    async def _enter_refresh_lease(*, cache_path: Path) -> None:
        """Enter a lease solely to exercise descriptor handoff cancellation."""
        async with ModelCatalogStore.refresh_lease(cache_path=cache_path):
            pytest.fail("cancelled waiter unexpectedly acquired the lease")


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
