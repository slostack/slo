"""New Slo never takes ownership of released Slo's catalog cache names."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import httpx
import pytest

from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.model_catalog.store import ModelCatalogStore
from src.auth.credential_dao import CredentialDAO, ProviderName
from src.integrations.openrouter.client import OpenRouterAPIClient
from tests.catalog_cache_samples import openrouter_cache_sample


@pytest.fixture(autouse=True)
def fresh_catalog() -> Iterator[None]:
    """Reset catalog publications around each separation test, including failures."""
    ModelCatalogService.reset()
    try:
        yield
    finally:
        ModelCatalogService.reset()


def _global_path(*, slo_home: Path, name: str) -> Path:
    """Return a contained target before a separation test writes default state.

    Args:
        slo_home (Path): Per-test state root supplied by the isolation fixture.
        name (str): File name below the global directory.

    Returns:
        Path: Target verified before directory creation or file writes.
    """
    path: Path = slo_home / "global" / name
    assert path.resolve().is_relative_to(slo_home.resolve())
    return path


def test_backend_policy_is_excluded_only_at_disk_boundary(isolated_slo_home: Path) -> None:
    """Every provider slice omits seed policy only when the real writer serializes it."""
    from src.agents.model_catalog.dao import ModelCatalogCacheDAO, ProviderCatalogCacheDAO

    entry = (
        SeedModelCatalog.load()
        .entries["gpt-5.4"]
        .model_copy(update={"supports_chatgpt_codex": False, "requires_responses_api": True})
    )
    assert entry.model_dump()["supports_chatgpt_codex"] is False
    assert entry.model_copy().requires_responses_api is True
    cache = ModelCatalogCacheDAO(
        provider_slices=[
            ProviderCatalogCacheDAO(provider=provider, entries=[entry]) for provider in ProviderName
        ]
    )
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    assert ModelCatalogStore.write_provider_cache(cache=cache).committed
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "2"
    for provider_slice in raw["provider_slices"]:
        assert "supports_chatgpt_codex" not in provider_slice["entries"][0]
        assert "requires_responses_api" not in provider_slice["entries"][0]
    assert not (path.parent / "model_catalog_cache.json").exists()
    assert not (path.parent / "model_catalog_cache.lock").exists()


def test_write_provider_cache_when_path_is_default_writes_provider_cache_file_only(
    isolated_slo_home: Path,
) -> None:
    """Default writes round-trip provider slices without creating the released file."""
    provider_path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    outcome = ModelCatalogStore.write_provider_cache(cache=openrouter_cache_sample())

    assert outcome.committed is True
    assert provider_path.is_file()
    assert not (provider_path.parent / "model_catalog_cache.json").exists()
    assert ModelCatalogStore.load_provider_cache() == openrouter_cache_sample()


async def test_refresh_lease_when_path_is_default_locks_refresh_lease_file(isolated_slo_home: Path) -> None:
    """Default refresh locking creates only the provider cache's lease file."""
    lease_path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.lock")
    async with ModelCatalogStore.refresh_lease():
        assert lease_path.is_file()

    assert not (lease_path.parent / "model_catalog_cache.lock").exists()


@pytest.mark.parametrize(
    argnames="payload",
    argvalues=[
        b"{private-cache-sentinel",
        b'{"schema_version":"2","provider_slices":"private-cache-sentinel"}',
        b"\xffprivate-cache-sentinel",
    ],
    ids=["malformed-json", "invalid-slices", "invalid-encoding"],
)
def test_load_provider_cache_when_corrupt_serves_seed_with_one_safe_warning(
    isolated_slo_home: Path, caplog: pytest.LogCaptureFixture, payload: bytes
) -> None:
    """Cold reads reject bad provider files without logging their content or traceback."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    with caplog.at_level(level=logging.INFO, logger="slo"):
        snapshot = ModelCatalogService.load()

    assert snapshot.entries == SeedModelCatalog.load().entries
    records = [record for record in caplog.records if record.name == "slo"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == "model_catalog_cache_load_failed"
    assert records[0].__dict__["path"] == str(path)
    assert records[0].exc_info is None and records[0].stack_info is None
    assert "private-cache-sentinel" not in caplog.text
    assert path.read_bytes() == payload


@pytest.mark.parametrize(
    argnames="payload", argvalues=['{"schema_version":"1"}', '{"schema_version":"3"}', "[]"]
)
def test_load_provider_cache_when_other_version_serves_seed_with_one_info(
    isolated_slo_home: Path, caplog: pytest.LogCaptureFixture, payload: str
) -> None:
    """Other cache shapes remain on disk and produce just the schema-ignore notice."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data=payload, encoding="utf-8")
    with caplog.at_level(level=logging.INFO, logger="slo"):
        snapshot = ModelCatalogService.load()

    assert snapshot.entries == SeedModelCatalog.load().entries
    records = [record for record in caplog.records if record.name == "slo"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].getMessage() == "model_catalog_cache_schema_ignored"
    assert records[0].__dict__["path"] == str(path)
    assert records[0].exc_info is None and records[0].stack_info is None
    assert path.read_text(encoding="utf-8") == payload


def test_load_provider_cache_when_unreadable_serves_seed_with_one_safe_warning(
    isolated_slo_home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A synthetic read refusal follows the same safe fallback even under root."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data="{}", encoding="utf-8")
    with (
        caplog.at_level(level=logging.INFO, logger="slo"),
        patch.object(
            target=Path, attribute="read_text", side_effect=PermissionError("private-read-sentinel")
        ),
    ):
        snapshot = ModelCatalogService.load()

    assert snapshot.entries == SeedModelCatalog.load().entries
    records = [record for record in caplog.records if record.name == "slo"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == "model_catalog_cache_load_failed"
    assert records[0].__dict__["path"] == str(path)
    assert records[0].exc_info is None and records[0].stack_info is None
    assert "private-read-sentinel" not in caplog.text
    assert ModelCatalogStore.write_provider_cache(cache=openrouter_cache_sample()).committed
    assert ModelCatalogStore.load_provider_cache() == openrouter_cache_sample()


@pytest.mark.parametrize(
    argnames="released_text",
    argvalues=[
        '{"schema_version":"1","generated_at":"2026-10-04T00:00:00+00:00",'
        '"entries":{},"aliases":{},"templates":[]}',
        '{"schema_version":"2","provider_slices":[]}',
        "{not-json",
    ],
    ids=["schema-one", "pre-fix-schema-two", "corrupt"],
)
async def test_load_provider_cache_when_released_files_exist_preserves_bytes_and_mtime(
    isolated_slo_home: Path, released_text: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Cold load, lease and write leave both released files in place without repairs."""
    released = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.json")
    lock = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.lock")
    _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.lock")
    released.parent.mkdir(parents=True, exist_ok=True)
    released.write_text(data=released_text, encoding="utf-8")
    lock.write_text(data="released-lock-sentinel", encoding="utf-8")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (released, lock)}

    with caplog.at_level(level=logging.INFO, logger="slo"):
        snapshot = ModelCatalogService.load()
        async with ModelCatalogStore.refresh_lease():
            outcome = ModelCatalogStore.write_provider_cache(cache=openrouter_cache_sample())

    assert snapshot.entries == SeedModelCatalog.load().entries
    assert outcome.committed is True
    assert ModelCatalogStore.load_provider_cache() == openrouter_cache_sample()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before
    assert not [record for record in caplog.records if record.name == "slo"]
    assert {path.name for path in released.parent.iterdir()} == {
        "model_catalog_cache.json",
        "model_catalog_cache.lock",
        "model_catalog_cache.v2.json",
        "model_catalog_cache.v2.lock",
    }


def test_load_provider_cache_when_missing_serves_seed_without_writes_or_logs(
    isolated_slo_home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """First-run cold reads serve seed without creating even the global directory."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    with caplog.at_level(level=logging.INFO, logger="slo"):
        snapshot = ModelCatalogService.load()

    assert snapshot.entries == SeedModelCatalog.load().entries
    assert not path.parent.exists()
    assert not [record for record in caplog.records if record.name == "slo"]


def test_load_provider_cache_when_valid_merges_seed_and_slice_without_logging(
    isolated_slo_home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A valid provider cache adds its exact route to the cold offline seed view."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    assert ModelCatalogStore.write_provider_cache(cache=openrouter_cache_sample()).committed
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with caplog.at_level(level=logging.INFO, logger="slo"):
        snapshot = ModelCatalogService.load()

    assert set(snapshot.entries) == set(SeedModelCatalog.load().entries) | {"openrouter:vendor/compat"}
    assert (
        snapshot.entries["openrouter:vendor/compat"]
        == openrouter_cache_sample().provider_slices[0].entries[0]
    )
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not [record for record in caplog.records if record.name == "slo"]


@pytest.mark.parametrize(
    argnames="payload",
    argvalues=[
        None,
        "{not-json",
        '{"schema_version":"1"}',
        '{"schema_version":"3"}',
        '{"schema_version":"2","provider_slices":false}',
        openrouter_cache_sample().model_dump_json(),
    ],
    ids=["missing", "corrupt", "schema-one", "schema-three", "invalid-slices", "valid"],
)
async def test_refresh_when_provider_cache_needs_rebuilding_publishes_only_provider_file(
    isolated_slo_home: Path, monkeypatch: pytest.MonkeyPatch, payload: Optional[str]
) -> None:
    """Real offline refresh replaces disposable state and survives a cold catalog reload."""
    path = _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.json")
    _global_path(slo_home=isolated_slo_home, name="model_catalog_cache.v2.lock")
    if payload is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data=payload, encoding="utf-8")
    monkeypatch.setenv(name="SLO_OPENROUTER_API_KEY", value="synthetic-cache-rebuild-key")
    requests: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        """Serve only metadata GETs for the real catalog client inside this test."""
        assert request.method == "GET"
        requests.append(request.url.path)
        if request.url.path == "/api/v1/key":
            return httpx.Response(status_code=200, json={"data": {}})
        assert request.url.path == "/api/v1/models/user"
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {
                        "id": "vendor/rebuilt",
                        "context_length": 64000,
                        "supported_parameters": ["tools"],
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:

        def client_factory(credential: CredentialDAO) -> OpenRouterAPIClient:
            """Keep the real metadata client while replacing its network transport."""
            return OpenRouterAPIClient(credential=credential, http_client=http_client)

        outcome = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER, force=True, client_factory=client_factory
        )

    assert outcome.status == "refreshed"
    assert requests == ["/api/v1/key", "/api/v1/models/user"]
    assert "synthetic-cache-rebuild-key" not in path.read_text(encoding="utf-8")
    ModelCatalogService.reset()
    assert set(ModelCatalogService.load().entries) == set(SeedModelCatalog.load().entries) | {
        "openrouter:vendor/rebuilt"
    }
    assert {file.name for file in path.parent.iterdir()} == {
        "model_catalog_cache.v2.json",
        "model_catalog_cache.v2.lock",
    }
