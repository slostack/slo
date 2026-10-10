"""Tests for manual override application to the catalog snapshot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.model_catalog.dao import (
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
)
from src.auth.credential_dao import ProviderName
from src.agents.model_catalog.discovery import ModelCatalogOverrideService
from src.agents.model_catalog.seed import SeedModelCatalog
from src.agents.model_catalog.service import ModelCatalogService


@pytest.mark.parametrize("control", ["effort", "budget", "required", "sampling", "levels"])
def test_required_responses_override_controls(control: str) -> None:
    """Schema-valid control changes reach the record guard and fail before adoption."""
    snapshot = SeedModelCatalog.load()
    data = snapshot.entries["gpt-6-luna"].reasoning_profile.model_dump()
    if control == "effort":
        data["provider_effort_map"]["medium"] = "high"
    if control == "budget":
        data["provider_budget_map"] = {"off": 1}
    if control == "required":
        data["provider_reasoning_required"] = True
    if control == "sampling":
        data["forbid_sampling_parameters_when_enabled"] = False
    if control == "levels":
        data["supported_levels"] = data["supported_levels"][:-1]
        del data["provider_effort_map"]["max"]
    candidate = ModelReasoningProfileDAO.model_validate(data)
    override = ModelCatalogOverrideDAO(model_name="gpt-6-luna", reasoning_profile=candidate)
    original = ModelCatalogEntryDAO.require_reasoning_override_compatibility
    with patch.object(
        target=ModelCatalogEntryDAO,
        attribute="require_reasoning_override_compatibility",
        autospec=True,
        side_effect=original,
    ) as guard:
        with pytest.raises(
            ValueError,
            match=r"^Model catalog overrides cannot change required Responses reasoning controls\.$",
        ):
            ModelCatalogOverrideService.apply_overrides(snapshot=snapshot, overrides=[override])
    assert guard.call_count == 1
    assert guard.call_args.kwargs["reasoning_profile"] == candidate


@pytest.mark.parametrize("level", ["off", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_required_responses_default_only_override_passes(level: str) -> None:
    """Operators may choose any supported default without changing fixed controls."""
    snapshot = SeedModelCatalog.load()
    profile = snapshot.entries["gpt-6-luna"].reasoning_profile.model_copy(update={"default_level": level})
    result = ModelCatalogOverrideService.apply_overrides(
        snapshot=snapshot,
        overrides=[ModelCatalogOverrideDAO(model_name="gpt-6-luna", reasoning_profile=profile)],
    )
    assert result.entries["gpt-6-luna"].reasoning_profile.default_level == level
    assert result.entries["gpt-6-luna"].requires_responses_api is True
    assert result.entries["gpt-6-luna"].supports_chatgpt_codex is True


@pytest.mark.parametrize("invalid", ["missing", "outside", "both"])
def test_invalid_reasoning_schema_never_reaches_record_guard(invalid: str) -> None:
    """Schema errors must not masquerade as fixed-control guard coverage."""
    from pydantic import ValidationError

    data = SeedModelCatalog.load().entries["gpt-6-luna"].reasoning_profile.model_dump()
    if invalid == "missing":
        del data["provider_effort_map"]["medium"]
    if invalid == "outside":
        data["provider_effort_map"]["bogus"] = "low"
    if invalid == "both":
        data["provider_budget_map"] = {"medium": 1}
    with patch.object(ModelCatalogEntryDAO, "require_reasoning_override_compatibility") as guard:
        with pytest.raises(ValidationError):
            ModelCatalogOverrideDAO.model_validate({"model_name": "gpt-6-luna", "reasoning_profile": data})
    guard.assert_not_called()


def test_invalid_cold_override_does_not_publish_snapshot() -> None:
    """A schema-valid but incompatible cold override fails before publication."""
    from src.agents.model_catalog.store import ModelCatalogStore

    profile = (
        SeedModelCatalog.load()
        .entries["gpt-6-luna"]
        .reasoning_profile.model_copy(update={"provider_reasoning_required": True})
    )
    override = ModelCatalogOverrideDAO(model_name="gpt-6-luna", reasoning_profile=profile)
    ModelCatalogService.reset()
    try:
        with patch.object(ModelCatalogStore, "load_overrides", return_value=[override]):
            with pytest.raises(ValueError, match="cannot change required Responses reasoning controls"):
                ModelCatalogService.load()
        assert ModelCatalogService._snapshot is None
    finally:
        ModelCatalogService.reset()


async def test_invalid_refresh_override_preserves_publication_and_cache(isolated_slo_home: "Path") -> None:
    """Reject an incompatible refresh candidate without replacing last-good state."""
    from src.agents.model_catalog.store import ModelCatalogStore
    from src.auth.credential_dao import AuthType, CredentialDAO, CredentialSource, ResolvedCredentialDAO
    from tests.agents.model_catalog.test_openrouter_lifecycle import FakeOpenRouterClient

    credential = CredentialDAO(
        provider=ProviderName.OPENROUTER, auth_type=AuthType.API_KEY, access_token="fixture-89"
    )
    client = FakeOpenRouterClient(credential=credential)
    resolved = ResolvedCredentialDAO(credential=credential, source=CredentialSource.ENVIRONMENT)
    cache_path = isolated_slo_home / "global/model_catalog_cache.v2.json"
    assert cache_path.resolve().is_relative_to(isolated_slo_home.resolve())
    ModelCatalogService.reset()
    try:
        first = await ModelCatalogService.refresh(
            provider=ProviderName.OPENROUTER,
            resolved_credential=resolved,
            client_factory=lambda credential: client,
        )
        assert first.status == "refreshed"
        snapshot = ModelCatalogService.load()
        before = cache_path.read_bytes()
        profile = snapshot.entries["gpt-6-luna"].reasoning_profile.model_copy(
            update={"provider_reasoning_required": True}
        )
        override = ModelCatalogOverrideDAO(model_name="gpt-6-luna", reasoning_profile=profile)
        with patch.object(ModelCatalogStore, "load_overrides", return_value=[override]):
            result = await ModelCatalogService.refresh(
                provider=ProviderName.OPENROUTER,
                resolved_credential=resolved,
                client_factory=lambda credential: client,
                force=True,
            )
        assert result.status == "failed"
        assert ModelCatalogService._snapshot is snapshot
        assert cache_path.read_bytes() == before
    finally:
        ModelCatalogService.reset()


class TestOverrideApplication:
    """Operator overrides patch the merged snapshot."""

    def test_override_forces_visibility_on(self) -> None:
        """An override can make claude-mythos visible."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="claude-mythos",
            visible_in_picker=True,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["claude-mythos"].visible_in_picker is True

    def test_override_forces_visibility_off(self) -> None:
        """An override can hide a visible first-class entry."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            visible_in_picker=False,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].visible_in_picker is False

    def test_unknown_override_target_is_ignored(self) -> None:
        """An override for an unknown model does not crash the merge."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="unknown-model",
            visible_in_picker=True,
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries == snapshot.entries

    def test_override_patches_support_tier(self) -> None:
        """An override can change the support tier."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            support_tier="compatibility_only",
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].support_tier == "compatibility_only"

    def test_override_patches_runtime_profile(self) -> None:
        """An override can patch runtime defaults."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="gpt-5.5",
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=16_384,
                context_window=2_000_000,
                streaming=True,
                requests_per_minute=100,
                tokens_per_minute=1_000_000,
                automatic_retry_attempts=2,
                local_retry_wait_cap_seconds=30,
            ),
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries["gpt-5.5"].runtime_profile.max_tokens == 16_384

    def test_override_cannot_make_ineligible_openrouter_entry_visible(self) -> None:
        """An override may not revive a route the provider marked ineligible."""
        snapshot = SeedModelCatalog.load().model_copy(
            update={
                "entries": {
                    "openrouter:vendor/ineligible": SeedModelCatalog.load()
                    .entries["gpt-5.5"]
                    .model_copy(
                        update={
                            "model_name": "openrouter:vendor/ineligible",
                            "api_model_name": "vendor/ineligible",
                            "visible_in_picker": False,
                            "availability": "ineligible",
                            "provider": ProviderName.OPENROUTER,
                        }
                    )
                }
            }
        )
        override = ModelCatalogOverrideDAO(
            model_name="openrouter:vendor/ineligible",
            visible_in_picker=True,
        )

        result = ModelCatalogOverrideService.apply_overrides(snapshot=snapshot, overrides=[override])

        assert result.entries["openrouter:vendor/ineligible"].visible_in_picker is False

    def test_override_cannot_increase_openrouter_provider_limit(self) -> None:
        """An override cannot broaden a discovered route's output cap."""
        entry = (
            SeedModelCatalog.load()
            .entries["gpt-5.5"]
            .model_copy(
                update={
                    "model_name": "openrouter:vendor/limited",
                    "api_model_name": "vendor/limited",
                    "provider": ProviderName.OPENROUTER,
                    "runtime_profile": ModelRuntimeProfileDAO(
                        max_tokens=100,
                        context_window=1_000,
                        streaming=True,
                        requests_per_minute=20,
                        tokens_per_minute=None,
                        automatic_retry_attempts=2,
                        local_retry_wait_cap_seconds=60,
                    ),
                }
            )
        )
        snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})
        override = ModelCatalogOverrideDAO(
            model_name=entry.model_name,
            runtime_profile=entry.runtime_profile.model_copy(update={"max_tokens": 101}),
        )

        with pytest.raises(ValueError, match="cannot increase provider limits"):
            ModelCatalogOverrideService.apply_overrides(snapshot=snapshot, overrides=[override])

    def test_openrouter_override_can_apply_finite_local_token_cap_when_provider_cap_is_unlimited(
        self,
    ) -> None:
        """A finite local rate cap restricts rather than broadens an unlimited provider policy."""
        entry = (
            SeedModelCatalog.load()
            .entries["gpt-5.5"]
            .model_copy(
                update={
                    "model_name": "openrouter:vendor/unlimited",
                    "api_model_name": "vendor/unlimited",
                    "provider": ProviderName.OPENROUTER,
                    "runtime_profile": ModelRuntimeProfileDAO(
                        max_tokens=100,
                        context_window=1_000,
                        streaming=True,
                        requests_per_minute=20,
                        tokens_per_minute=None,
                        automatic_retry_attempts=2,
                        local_retry_wait_cap_seconds=60,
                    ),
                }
            )
        )
        override = ModelCatalogOverrideDAO(
            model_name=entry.model_name,
            runtime_profile=entry.runtime_profile.model_copy(update={"tokens_per_minute": 100}),
        )
        snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})

        result = ModelCatalogOverrideService.apply_overrides(snapshot=snapshot, overrides=[override])

        assert result.entries[entry.model_name].runtime_profile.tokens_per_minute == 100

    def test_openrouter_override_cannot_remove_mandatory_reasoning(self) -> None:
        """Overrides cannot turn a mandatory provider reasoning contract into an optional one."""
        entry = (
            SeedModelCatalog.load()
            .entries["gpt-6-astra"]
            .model_copy(
                update={"model_name": "openrouter:vendor/mandatory", "provider": ProviderName.OPENROUTER}
            )
        )
        override = ModelCatalogOverrideDAO(
            model_name=entry.model_name,
            reasoning_profile=entry.reasoning_profile.model_copy(
                update={"provider_reasoning_required": False}
            ),
        )
        snapshot = SeedModelCatalog.load().model_copy(update={"entries": {entry.model_name: entry}})

        with pytest.raises(ValueError, match="cannot remove mandatory reasoning"):
            ModelCatalogOverrideService.apply_overrides(snapshot=snapshot, overrides=[override])

    def test_override_patches_reasoning_profile(self) -> None:
        """An override can patch reasoning support."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO(
            model_name="claude-mythos",
            reasoning_profile=ModelReasoningProfileDAO(
                supported_levels=("off", "minimal", "low", "medium", "high", "xhigh"),
                default_level="high",
                provider_effort_map={
                    "minimal": "low",
                    "low": "low",
                    "medium": "medium",
                    "high": "high",
                    "xhigh": "high",
                },
            ),
        )

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert "xhigh" in result.entries["claude-mythos"].reasoning_profile.supported_levels

    def test_override_without_target_is_ignored(self) -> None:
        """An override with neither model_name nor alias is ignored."""
        snapshot = SeedModelCatalog.load()
        override = ModelCatalogOverrideDAO()

        result = ModelCatalogOverrideService.apply_overrides(
            snapshot=snapshot,
            overrides=[override],
        )

        assert result.entries == snapshot.entries


class TestServiceOverrideIntegration:
    """Service loads and applies overrides from disk."""

    def test_service_applies_override_file(self, tmp_path) -> None:
        """The service loads overrides and makes claude-mythos visible."""
        overrides_path = tmp_path / "overrides.json"
        overrides_path.write_text(
            '[{"model_name":"claude-mythos","visible_in_picker":true}]',
            encoding="utf-8",
        )
        ModelCatalogService.reset()

        with patch.object(
            ModelCatalogService,
            "_apply_manual_overrides",
            return_value=ModelCatalogOverrideService.apply_overrides(
                snapshot=SeedModelCatalog.load(),
                overrides=[
                    ModelCatalogOverrideDAO(
                        model_name="claude-mythos",
                        visible_in_picker=True,
                    ),
                ],
            ),
        ):
            snapshot = ModelCatalogService.load()

        assert snapshot.entries["claude-mythos"].visible_in_picker is True
