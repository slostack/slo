"""Qualified local Claude Code routes, not a provider availability catalog."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from config.cfg import cfg

from src.agents.model_catalog.dao import (
    ModelCatalogEntryDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
    ReasoningLevel,
)
from src.auth.credential_dao import ProviderName

_REASONING_LEVELS: tuple[ReasoningLevel, ...] = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
_GENERIC_EFFORT_MAP: Mapping[ReasoningLevel, str] = MappingProxyType(
    {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"}
)
_FABLE_EFFORT_MAP: Mapping[ReasoningLevel, str] = MappingProxyType({"off": "low", **_GENERIC_EFFORT_MAP})


def _identity_native_model_ids(
    *, prefix: str, families: tuple[str, ...], versions: tuple[str, ...]
) -> dict[str, str]:
    """Map each generated ``claude-<family>-<version>`` route to its own unprefixed name.

    The grid is the operator-requested range, not a list of verified models, so each
    generated route keeps today's identity mapping. Exceptions are explicit table rows.

    Args:
        prefix (str): Qualified-route prefix prepended to each generated name.
        families (tuple[str, ...]): Model families in the grid.
        versions (tuple[str, ...]): Dashed versions in the grid.

    Returns:
        dict[str, str]: Qualified route to native model id, in grid order.
    """
    return {
        f"{prefix}claude-{family}-{version}": f"claude-{family}-{version}"
        for family in families
        for version in versions
    }


class ClaudeBridgeRoute:
    """Admit operator-requested native routes without claiming native entitlement.

    The catalog's mandatory numeric values are Slo planning policy, not discovered
    native capacities. Unknown provider limits and availability remain unchecked.
    ``NATIVE_MODEL_IDS`` is the only place a qualified route becomes the native model
    id that Claude Code receives.
    """

    PREFIX: str = "claude-bridge:"
    """Canonical qualified-route prefix; the single owner of route recognition."""

    FAMILIES: tuple[str, ...] = ("haiku", "sonnet", "opus")
    """Grid families. Fable is not generated: most grid versions do not exist for it."""
    VERSIONS: tuple[str, ...] = ("4-8", "4-9", "5-0", "5-1", "5-2", "5-3", "5-4", "5-5")

    FABLE_NATIVE_MODEL_IDS: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            PREFIX + "claude-fable": "claude-fable-5-1",
            PREFIX + "claude-fable-5-1": "claude-fable-5-1",
            PREFIX + "claude-fable-5": "claude-fable-5",
        }
    )
    """Explicit Fable routes. The family route follows the CLI's ``fable`` alias to Fable 5.1."""

    NATIVE_MODEL_IDS: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            **_identity_native_model_ids(prefix=PREFIX, families=FAMILIES, versions=VERSIONS),
            PREFIX + "claude-sonnet-4-6": "claude-sonnet-4-6",
            PREFIX + "claude-haiku-4-5": "claude-haiku-4-5",
            **FABLE_NATIVE_MODEL_IDS,
        }
    )
    """Single route table: every admitted qualified route mapped to its native model id."""

    @classmethod
    def is_bridge_route(cls, *, model_name: str) -> bool:
        """Return whether ``model_name`` is a qualified native bridge route.

        This is the single bridge-owned route predicate: credential and
        readiness owners consult it instead of repeating the raw prefix, so a
        malformed or disabled route can be denied before any native work or
        state mutation. An ordinary direct-provider name always returns
        ``False``; route *support* (configuration and family/version) is validated
        separately by :meth:`validate`.

        Args:
            model_name (str): Candidate model identifier from configuration
                or selection.

        Returns:
            bool: ``True`` only for the qualified ``claude-bridge:`` form.
        """
        return model_name.startswith(cls.PREFIX)

    @staticmethod
    def is_enabled() -> bool:
        """Enable local routes by default unless configuration explicitly disables them."""
        return (cfg("SLO_CLAUDE_BRIDGE_ENABLED") or "").strip().lower() not in {"0", "false", "no", "off"}

    @classmethod
    def model_names(cls) -> tuple[str, ...]:
        """List exact local routes in picker order.

        Returns:
            Qualified identifiers from the route table: the generated grid for haiku,
            sonnet and opus (4.8, 4.9 and 5.0 through 5.5), the retained catalog
            identifiers, then the explicit Fable routes. Inclusion does not establish
            provider existence or account availability.
        """
        return tuple(cls.NATIVE_MODEL_IDS)

    @classmethod
    def is_provider_reasoning_required(cls, *, model_name: str) -> bool:
        """Return whether ``model_name`` is a Fable route, which rejects disabled thinking.

        Args:
            model_name (str): Candidate qualified route, admitted or not.

        Returns:
            bool: ``True`` only for an explicit Fable route.
        """
        return model_name in cls.FABLE_NATIVE_MODEL_IDS

    @classmethod
    def native_model_id(cls, *, model_name: str) -> str:
        """Return the native model id Claude Code receives for an admitted route.

        This is the only route-to-model translation point. Validation runs first, so an
        unsupported or disabled route raises before any native work starts.

        Args:
            model_name (str): Exact qualified local route.

        Returns:
            str: Unprefixed native model identifier.

        Raises:
            ValueError: The bridge is disabled or the route is not in the route table.
        """
        cls.validate(model_name=model_name)
        return cls.NATIVE_MODEL_IDS[model_name]

    @classmethod
    def validate(cls, *, model_name: str) -> None:
        """Reject disabled or unsupported local routes without a direct-provider fallback.

        Args:
            model_name: Exact qualified identifier from configuration or selection.

        Raises:
            ValueError: The bridge is explicitly disabled or the identifier is not locally supported.
        """
        if not cls.is_enabled():
            raise ValueError("Claude bridge is disabled; unset SLO_CLAUDE_BRIDGE_ENABLED or set it to 1.")
        if model_name not in cls.NATIVE_MODEL_IDS:
            raise ValueError(
                "Unsupported Claude bridge model; use claude-bridge:claude-<family>-<version> "
                "with haiku, sonnet or opus and 4-8 through 5-5, the retained "
                "claude-bridge:claude-sonnet-4-6 and claude-bridge:claude-haiku-4-5 routes, "
                f"or one of the Fable routes: {', '.join(cls.FABLE_NATIVE_MODEL_IDS)}."
            )

    @classmethod
    def entry(cls, *, model_name: str) -> ModelCatalogEntryDAO:
        """Build in-memory host planning metadata, never a shared cache entry.

        Args:
            model_name: Exact qualified local route.

        Returns:
            A selectable route reporting its native model id, with native effort
            controls and access unchecked.
        """
        native_model_id: str = cls.native_model_id(model_name=model_name)
        return ModelCatalogEntryDAO(
            model_name=model_name,
            display_name=f"{model_name} (native access unchecked; host planning limits)",
            provider=ProviderName.ANTHROPIC,
            support_tier="local_route",
            visible_in_picker=True,
            api_model_name=native_model_id,
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=4096,
                context_window=200_000,
                streaming=True,
                requests_per_minute=60,
                tokens_per_minute=None,
                automatic_retry_attempts=0,
                local_retry_wait_cap_seconds=0,
            ),
            reasoning_profile=cls._reasoning_profile(model_name=model_name),
        )

    @classmethod
    def _reasoning_profile(cls, *, model_name: str) -> ModelReasoningProfileDAO:
        """Return the route's reasoning profile; Fable keeps provider reasoning on.

        Fable rejects disabled thinking, so its selected ``off`` maps to native effort
        ``low``, the same shape as the Astra catalog profile. Other families keep the
        generic profile, where ``off`` sends no effort and disables thinking.

        Args:
            model_name (str): Exact qualified local route.

        Returns:
            ModelReasoningProfileDAO: Reasoning levels and native effort mapping for the route.
        """
        if cls.is_provider_reasoning_required(model_name=model_name):
            return ModelReasoningProfileDAO(
                supported_levels=_REASONING_LEVELS,
                default_level="high",
                provider_effort_map=_FABLE_EFFORT_MAP,
                provider_reasoning_required=True,
            )
        return ModelReasoningProfileDAO(
            supported_levels=_REASONING_LEVELS,
            default_level="high",
            provider_effort_map=_GENERIC_EFFORT_MAP,
        )
