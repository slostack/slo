"""Canonical model catalog package.

This package is the single source of truth for model identity, provider
ownership, runtime defaults, reasoning support, visibility, aliases, and
support tier. Downstream layers consume projections from
``ModelCatalogService`` rather than maintaining independent tables.
"""

from src.agents.model_catalog.dao import (
    ModelAliasDAO,
    ModelCatalogEntryDAO,
    ModelCatalogOverrideDAO,
    ModelCatalogSnapshotDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
    ProviderDiscoveryResultDAO,
    ProviderModelMetadataDAO,
    ProviderModelTemplateDAO,
    ReasoningLevel,
)
from src.agents.model_catalog.service import ModelCatalogService

__all__ = [
    "ModelAliasDAO",
    "ModelCatalogEntryDAO",
    "ModelCatalogOverrideDAO",
    "ModelCatalogSnapshotDAO",
    "ModelCatalogService",
    "ModelReasoningProfileDAO",
    "ModelRuntimeProfileDAO",
    "ProviderDiscoveryResultDAO",
    "ProviderModelMetadataDAO",
    "ProviderModelTemplateDAO",
    "ReasoningLevel",
]
