"""Qualified local Claude Code routes, not a provider availability catalog."""

from config.cfg import cfg

from src.agents.model_catalog.dao import (
    ModelCatalogEntryDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
)
from src.auth.credential_dao import ProviderName


class ClaudeBridgeRoute:
    """Admit operator-requested native routes without claiming native entitlement.

    The catalog's mandatory numeric values are Slo planning policy, not discovered
    native capacities. Unknown provider limits and availability remain unchecked.
    """

    PREFIX: str = "claude-bridge:"
    """Canonical qualified-route prefix; the single owner of route recognition."""

    FAMILIES: tuple[str, ...] = ("haiku", "sonnet", "opus", "fable")
    VERSIONS: tuple[str, ...] = ("4-8", "4-9", "5-0", "5-1", "5-2", "5-3", "5-4", "5-5")

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
        """List exact local routes, including existing catalog Sonnet/Fable identifiers.

        Returns:
            Qualified identifiers; the range means 4.8, 4.9 and 5.0 through 5.5.
            Inclusion does not establish provider existence or account availability.
        """
        native_names = tuple(
            f"claude-{family}-{version}" for family in cls.FAMILIES for version in cls.VERSIONS
        )
        return tuple(cls.PREFIX + name for name in native_names) + (
            cls.PREFIX + "claude-sonnet-4-6",
            cls.PREFIX + "claude-haiku-4-5",
            cls.PREFIX + "claude-fable",
            cls.PREFIX + "claude-fable-5",
        )

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
        if model_name not in cls.model_names():
            raise ValueError(
                "Unsupported Claude bridge model; use claude-bridge:claude-<family>-<version> "
                "with haiku, sonnet, opus or fable and 4-8 through 5-5, "
                "or the retained claude-bridge:claude-sonnet-4-6 route."
            )

    @classmethod
    def entry(cls, *, model_name: str) -> ModelCatalogEntryDAO:
        """Build in-memory host planning metadata, never a shared cache entry.

        Args:
            model_name: Exact qualified local route.

        Returns:
            A selectable route with native effort controls and access unchecked.
        """
        cls.validate(model_name=model_name)
        return ModelCatalogEntryDAO(
            model_name=model_name,
            display_name=f"{model_name} (native access unchecked; host planning limits)",
            provider=ProviderName.ANTHROPIC,
            support_tier="local_route",
            visible_in_picker=True,
            api_model_name=model_name,
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=4096,
                context_window=200_000,
                streaming=True,
                requests_per_minute=60,
                tokens_per_minute=None,
                automatic_retry_attempts=0,
                local_retry_wait_cap_seconds=0,
            ),
            reasoning_profile=ModelReasoningProfileDAO(
                supported_levels=("off", "minimal", "low", "medium", "high", "xhigh", "max"),
                default_level="high",
                provider_effort_map={
                    "minimal": "low",
                    "low": "low",
                    "medium": "medium",
                    "high": "high",
                    "xhigh": "xhigh",
                    "max": "max",
                },
            ),
        )
