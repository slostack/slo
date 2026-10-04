"""Released -> new -> released catalog operations share state, never file schemas."""

from pathlib import Path

from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from tests.catalog_cache_samples import openrouter_cache_sample
from tests.compat.released_runner import run_released_slo
from tests.compat.released_scripts import RELEASED_LOAD_CATALOG, RELEASED_WRITE_SCHEMA_ONE_CACHE


def test_load_when_new_slo_wrote_provider_cache_released_slo_stays_silent(
    released_slo_source: Path, isolated_slo_home: Path
) -> None:
    """Released cache survives new publication; released CLI import remains silent."""
    written = run_released_slo(
        source=released_slo_source, slo_home=isolated_slo_home, script=RELEASED_WRITE_SCHEMA_ONE_CACHE
    )
    assert written.returncode == 0, written.stderr
    released_file = isolated_slo_home / "global/model_catalog_cache.json"
    released_bytes = released_file.read_bytes()
    ModelCatalogService.reset()
    try:
        assert (
            (isolated_slo_home / "global/model_catalog_cache.v2.json")
            .resolve()
            .is_relative_to(isolated_slo_home)
        )
        assert ModelCatalogStore.write_provider_cache(cache=openrouter_cache_sample()).committed
        assert "gpt-5.4" in ModelCatalogService.load().entries
        loaded = run_released_slo(
            source=released_slo_source, slo_home=isolated_slo_home, script=RELEASED_LOAD_CATALOG
        )
        assert loaded.returncode == 0, loaded.stderr
        assert loaded.result == written.result
        assert "model_catalog_cache_load_failed" not in loaded.stderr + loaded.stdout
        assert "Traceback" not in loaded.stderr + loaded.stdout
        assert released_file.read_bytes() == released_bytes
        assert ModelCatalogStore.load_provider_cache() == openrouter_cache_sample()
    finally:
        ModelCatalogService.reset()
