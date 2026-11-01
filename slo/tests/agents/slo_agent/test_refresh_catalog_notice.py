"""Refresh notices include safe count and last complete check evidence."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.model_catalog.dao import (
    CatalogLifecycleStatusDAO,
    CatalogRefreshResultDAO,
    ModelCatalogSnapshotDAO,
)
from src.agents.model_catalog.seed import SeedModelCatalog
from src.auth.credential_dao import ProviderName
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


@pytest.mark.parametrize("status", ["refreshed", "fresh", "failed", "credential_changed"])
async def test_refresh_notice_has_count_and_last_check(
    tmp_path: Path, status: Literal["refreshed", "fresh", "failed", "credential_changed"]
) -> None:
    """An empty published catalog reports zero, never an invented current check."""
    message = await _refresh_notice(
        tmp_path=tmp_path,
        status=status,
        snapshot=SeedModelCatalog.load(),
        checked_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )

    assert "0 models" in message
    assert "2026-10-03T00:00:00+00:00" in message
    assert "last complete check" in message
    assert len(message) <= 240


@pytest.mark.parametrize("status", ["refreshed", "fresh"])
async def test_refresh_notice_counts_only_eligible_visible_openrouter_rows(
    tmp_path: Path, status: Literal["refreshed", "fresh", "failed", "credential_changed"]
) -> None:
    """Manual refresh reports only rows eligible for the exact picker selection set."""
    seed: ModelCatalogSnapshotDAO = SeedModelCatalog.load()
    eligible = seed.entries["gpt-5.4"].model_copy(
        update={
            "model_name": "openrouter:vendor/eligible",
            "provider": ProviderName.OPENROUTER,
            "visible_in_picker": True,
            "availability": "available",
        }
    )
    hidden = eligible.model_copy(
        update={"model_name": "openrouter:vendor/hidden", "visible_in_picker": False}
    )
    removed = eligible.model_copy(
        update={"model_name": "openrouter:vendor/removed", "availability": "removed"}
    )
    snapshot = seed.model_copy(
        update={
            "entries": {
                **seed.entries,
                eligible.model_name: eligible,
                hidden.model_name: hidden,
                removed.model_name: removed,
            }
        }
    )

    message = await _refresh_notice(
        tmp_path=tmp_path,
        status=status,
        snapshot=snapshot,
        checked_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )

    assert "1 model" in message
    assert "hidden" not in message
    assert "removed" not in message


@pytest.mark.parametrize("status", ["fresh", "failed", "credential_changed"])
async def test_refresh_notice_uses_unknown_check_time_when_lifecycle_has_none(
    tmp_path: Path, status: Literal["refreshed", "fresh", "failed", "credential_changed"]
) -> None:
    """Coalesced and non-success outcomes do not manufacture a complete-check timestamp."""
    message = await _refresh_notice(
        tmp_path=tmp_path,
        status=status,
        snapshot=SeedModelCatalog.load(),
        checked_at=None,
    )

    assert "0 models" in message
    assert "last complete check: unknown" in message
    assert len(message) <= 240


async def _refresh_notice(
    *,
    tmp_path: Path,
    status: Literal["refreshed", "fresh", "failed", "credential_changed"],
    snapshot: ModelCatalogSnapshotDAO,
    checked_at: datetime | None,
) -> str:
    """Run the session-owned refresh notice path with one controlled lifecycle result."""
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
    )
    result = CatalogRefreshResultDAO(status=status, catalog_generation=1, safe_message="OpenRouter result.")
    lifecycle = CatalogLifecycleStatusDAO(catalog_checked_at=checked_at)
    with (
        patch(
            "src.agents.slo_agent.sessions.service.ModelCatalogService.refresh",
            new=AsyncMock(return_value=result),
        ),
        patch("src.agents.slo_agent.sessions.service.ModelCatalogService.load", return_value=snapshot),
        patch(
            "src.agents.slo_agent.sessions.service.ModelCatalogService.lifecycle_status",
            return_value=lifecycle,
        ),
    ):
        return await session.refresh_model_catalog()
