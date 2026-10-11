"""Convert validated OpenRouter user-model metadata into canonical catalog entries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from src.agents.model_catalog.dao import (
    CANONICAL_REASONING_LEVEL_ORDER,
    ModelCatalogEntryDAO,
    ModelCapabilitiesDAO,
    ModelReasoningProfileDAO,
    ModelRuntimeProfileDAO,
    ProviderDiscoveryResultDAO,
    ReasoningLevel,
)
from src.auth.credential_dao import ProviderName
from src.integrations.openrouter.dao import OpenRouterModelsResponseDAO


class OpenRouterCatalogConverter:
    """Translate OpenRouter wire records without author-family inference or I/O."""

    @classmethod
    def invoke(
        cls,
        *,
        response: OpenRouterModelsResponseDAO,
        now: datetime,
    ) -> ProviderDiscoveryResultDAO:
        """Convert each user-model wire row into a conservative canonical record.

        Args:
            response (OpenRouterModelsResponseDAO): Validated authenticated model envelope.
            now (datetime): Injection seam for expiry evaluation.

        Returns:
            ProviderDiscoveryResultDAO: Exact OpenRouter entries for catalog publication.
        """
        records = cls._unique_records(records=response.data)
        entries: list[ModelCatalogEntryDAO] = [
            cls._convert_entry(record=record, now=now) for record in records
        ]
        return ProviderDiscoveryResultDAO(
            provider=ProviderName.OPENROUTER,
            available_model_names=[entry.model_name for entry in entries],
            entries=entries,
            complete=True,
        )

    @classmethod
    def _unique_records(cls, *, records: list[dict[str, object]]) -> list[dict[str, object]]:
        """Deduplicate equal rows in first-seen order and reject conflicting identities.

        Args:
            records (list[dict[str, object]]): Validated-but-unconverted remote model records.

        Raises:
            ValueError: If conflicting records claim the same exact remote ID.

        Returns:
            list[dict[str, object]]: Unique records preserving wire order.
        """
        unique: dict[str, dict[str, object]] = {}
        for record in records:
            model_id: str = cls._required_id(record=record)
            if model_id in unique and unique[model_id] != record:
                raise ValueError("OpenRouter discovery contains conflicting model ids.")
            unique.setdefault(model_id, record)
        return list(unique.values())

    @classmethod
    def _convert_entry(cls, *, record: dict[str, object], now: datetime) -> ModelCatalogEntryDAO:
        """Create one route while keeping insufficient metadata unselectable."""
        api_model_name: str = cls._required_id(record=record)
        context_window: int = cls._context_window(record=record)
        output_cap: int = cls._output_cap(record=record, context_window=context_window)
        expired: bool = cls._is_expired(record=record, now=now)
        visible: bool = cls._is_eligible(
            record=record,
            api_model_name=api_model_name,
            context_window=context_window,
            expired=expired,
        )
        reasoning_profile: ModelReasoningProfileDAO = cls._reasoning_profile(record=record)
        return ModelCatalogEntryDAO(
            model_name=f"openrouter:{api_model_name}",
            display_name=cls._display_name(record=record, fallback=api_model_name),
            provider=ProviderName.OPENROUTER,
            support_tier="auto_discovered",
            visible_in_picker=visible,
            runtime_profile=ModelRuntimeProfileDAO(
                max_tokens=output_cap,
                context_window=context_window,
                streaming=True,
                requests_per_minute=20,
                tokens_per_minute=None,
                automatic_retry_attempts=2,
                local_retry_wait_cap_seconds=60,
            ),
            reasoning_profile=reasoning_profile,
            api_model_name=api_model_name,
            capabilities=ModelCapabilitiesDAO(
                input_modalities=cls._modalities(record=record, field="input_modalities"),
                output_modalities=cls._modalities(record=record, field="output_modalities"),
                supported_parameters=cls._supported_parameters(record=record),
                reported_output_ceiling=cls._reported_output_ceiling(record=record),
                expires_at=cls._expiry_evidence(record=record),
                reasoning_controls_available=cls._reasoning_controls_available(record=record),
                reasoning_disable_available=cls._reasoning_disable_available(record=record),
                supports_max_tokens=cls._reasoning_budget_evidence(record=record),
            ),
            availability="expired" if expired else "available" if visible else "ineligible",
        )

    @staticmethod
    def _required_id(*, record: dict[str, object]) -> str:
        """Return an exact remote ID or reject malformed catalog data."""
        value: object | None = record.get("id")
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ValueError("OpenRouter discovery contains an invalid model id.")
        from src.auth.provider_for_model import provider_for_model

        provider_for_model(model_name=f"openrouter:{value}")
        return value

    @staticmethod
    def _context_window(*, record: dict[str, object]) -> int:
        """Return the smaller valid model and endpoint context ceilings."""
        model_context: int | None = OpenRouterCatalogConverter._valid_context_window(
            value=record.get("context_length")
        )
        if model_context is None:
            return 2
        top_provider: object | None = record.get("top_provider")
        endpoint_value: object | None = (
            top_provider.get("context_length") if isinstance(top_provider, dict) else None
        )
        if endpoint_value is None:
            return model_context
        endpoint_context: int | None = OpenRouterCatalogConverter._valid_context_window(value=endpoint_value)
        if endpoint_context is None:
            return 2
        return min(model_context, endpoint_context)

    @staticmethod
    def _valid_context_window(*, value: object | None) -> int | None:
        """Return a bounded strict integer context window or no validated value."""
        if isinstance(value, int) and not isinstance(value, bool) and 2 <= value <= 10_000_000:
            return value
        return None

    @classmethod
    def _is_eligible(
        cls,
        *,
        record: dict[str, object],
        api_model_name: str,
        context_window: int,
        expired: bool,
    ) -> bool:
        """Decide whether a valid record can be selected for a text tool agent."""
        return (
            cls._has_text_io(record=record)
            and cls._supports_tools(record=record)
            and not cls._is_excluded_id(api_model_name=api_model_name)
            and cls._context_metadata_valid(record=record)
            and cls._output_metadata_valid(record=record)
            and context_window >= 2
            and not expired
        )

    @staticmethod
    def _output_cap(*, record: dict[str, object], context_window: int) -> int:
        """Return the smaller validated remote output ceiling or local safe default."""
        top_provider: object | None = record.get("top_provider")
        remote_cap: object | None = (
            top_provider.get("max_completion_tokens") if isinstance(top_provider, dict) else None
        )
        if isinstance(remote_cap, bool) or not isinstance(remote_cap, int) or remote_cap <= 0:
            return min(4096, context_window // 2)
        return min(4096, remote_cap, context_window // 2)

    @classmethod
    def _is_expired(cls, *, record: dict[str, object], now: datetime) -> bool:
        """Evaluate persisted expiry with the same rule used at admission."""
        return cls.is_expired(expires_at=cls._expiry_evidence(record=record), now=now)

    @staticmethod
    def _expiry_evidence(*, record: dict[str, object]) -> str | None:
        """Keep absence distinct from malformed advertised expiry."""
        value = record.get("expiration_date")
        if value is None:
            return None
        return value if isinstance(value, str) else "invalid"

    @staticmethod
    def is_expired(*, expires_at: str | None, now: datetime) -> bool:
        """Evaluate a UTC date or exact aware timestamp, failing closed on malformed data.

        Args:
            expires_at: Advertised expiry or None when absent.
            now: Aware evaluation clock.

        Returns:
            bool: Whether expiry has arrived or its evidence is malformed.
        """
        if expires_at is None:
            return False
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            return True
        if len(expires_at) == 10:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry.tzinfo is None:
            return True
        return now.astimezone(timezone.utc) >= expiry.astimezone(timezone.utc)

    @classmethod
    def _context_metadata_valid(cls, *, record: dict[str, object]) -> bool:
        """Require valid model context and every supplied endpoint context."""
        if cls._valid_context_window(value=record.get("context_length")) is None:
            return False
        provider = record.get("top_provider")
        if provider is None:
            return True
        if not isinstance(provider, dict):
            return False
        value = provider.get("context_length")
        return value is None or cls._valid_context_window(value=value) is not None

    @staticmethod
    def _output_metadata_valid(*, record: dict[str, object]) -> bool:
        """Accept unknown capacity during conversion without inventing provider limits.

        Args:
            record: Authenticated model metadata before eligibility projection.

        Returns:
            Whether output evidence is absent, null or a positive strict integer.
                Independent text, tool and context gates still apply.
        """
        provider: object = record.get("top_provider")
        if not isinstance(provider, dict):
            return provider is None
        value: object = provider.get("max_completion_tokens")
        if value is None:
            return True
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @staticmethod
    def _has_text_io(*, record: dict[str, object]) -> bool:
        """Require explicit text input and output modalities."""
        architecture: object | None = record.get("architecture")
        if not isinstance(architecture, dict):
            return False
        inputs: object | None = architecture.get("input_modalities")
        outputs: object | None = architecture.get("output_modalities")
        return (
            isinstance(inputs, list) and isinstance(outputs, list) and "text" in inputs and "text" in outputs
        )

    @staticmethod
    def _supported_parameters(*, record: dict[str, object]) -> tuple[str, ...]:
        """Retain sanitized advertised parameter names for catalog metadata."""
        parameters: object | None = record.get("supported_parameters")
        if not isinstance(parameters, list):
            return ()
        return tuple(parameter for parameter in parameters if isinstance(parameter, str))

    @classmethod
    def _reported_output_ceiling(cls, *, record: dict[str, object]) -> int | None:
        """Retain a valid advertised output ceiling separately from the local cap."""
        top_provider: object | None = record.get("top_provider")
        if not isinstance(top_provider, dict):
            return None
        value: object | None = top_provider.get("max_completion_tokens")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None

    @staticmethod
    def _supports_tools(*, record: dict[str, object]) -> bool:
        """Require advertised tool support without guessing from the route name."""
        parameters: object | None = record.get("supported_parameters")
        return isinstance(parameters, list) and "tools" in parameters

    @staticmethod
    def _reasoning_budget_evidence(*, record: dict[str, object]) -> bool | None:
        """Retain strict budget evidence during conversion without enabling budget requests.

        Args:
            record: Authenticated model metadata supplied to the converter.

        Returns:
            Advertised boolean, or None for absent or malformed evidence.
        """
        reasoning: object | None = record.get("reasoning")
        if not isinstance(reasoning, dict):
            return None
        value: object | None = reasoning.get("supports_max_tokens")
        return value if isinstance(value, bool) else None

    @classmethod
    def _reasoning_disable_available(cls, *, record: dict[str, object]) -> bool:
        """Return whether the record explicitly permits a reasoning disable request.

        Args:
            record (dict[str, object]): Unconverted authenticated model metadata.

        Returns:
            bool: Whether the reasoning parameter and explicit non-mandatory metadata permit disable.
        """
        reasoning: object | None = record.get("reasoning")
        return (
            isinstance(reasoning, dict)
            and reasoning.get("mandatory") is False
            and "reasoning" in cls._supported_parameters(record=record)
            and "supported_efforts" in reasoning
        )

    @classmethod
    def _reasoning_controls_available(cls, *, record: dict[str, object]) -> bool:
        """Return whether metadata establishes a known enabled reasoning effort.

        Missing ``mandatory`` withholds only the permission to send an explicit
        disable control; it must not discard an otherwise known enabled effort.
        A ``none``-only response has no enabled effort and remains conservative.
        """
        reasoning: object | None = record.get("reasoning")
        if not isinstance(reasoning, dict):
            return False
        if "reasoning" not in cls._supported_parameters(record=record):
            return False
        if "supported_efforts" not in reasoning:
            return False
        return bool(cls._recognized_efforts(efforts=reasoning.get("supported_efforts")))

    @classmethod
    def _reasoning_profile(cls, *, record: dict[str, object]) -> ModelReasoningProfileDAO:
        """Translate known enabled efforts and explicit disable permission separately."""
        reasoning: object | None = record.get("reasoning")
        if not isinstance(reasoning, dict):
            return ModelReasoningProfileDAO(supported_levels=("off",), default_level="off")
        recognized: tuple[ReasoningLevel, ...] = cls._recognized_efforts(
            efforts=reasoning.get("supported_efforts")
        )
        disable_available: bool = cls._reasoning_disable_available(record=record)
        if not recognized:
            if disable_available:
                return cls._disable_only_reasoning_profile(disable_available=disable_available)
            return ModelReasoningProfileDAO(supported_levels=("off",), default_level="off")
        if not cls._reasoning_controls_available(record=record):
            return ModelReasoningProfileDAO(supported_levels=("off",), default_level="off")
        mandatory_value: object | None = reasoning.get("mandatory")
        default_effort: ReasoningLevel = cls._default_effort(
            value=reasoning.get("default_effort"), supported=recognized
        )
        if mandatory_value is True:
            return cls._build_reasoning_profile(
                recognized=recognized,
                default_effort=default_effort,
                mandatory=True,
                default_enabled=True,
            )
        if mandatory_value is False:
            return cls._build_reasoning_profile(
                recognized=recognized,
                default_effort=default_effort,
                mandatory=False,
                default_enabled=reasoning.get("default_enabled") is not False,
            )
        return ModelReasoningProfileDAO(
            supported_levels=cast(tuple[ReasoningLevel, ...], ("off",) + recognized),
            default_level=default_effort,
            provider_effort_map={level: level for level in recognized},
        )

    @staticmethod
    def _disable_only_reasoning_profile(*, disable_available: bool) -> ModelReasoningProfileDAO:
        """Build an off-only profile that retains explicit gateway disable permission.

        Args:
            disable_available (bool): Whether advertised metadata explicitly permits disable.

        Returns:
            ModelReasoningProfileDAO: Off-only compatibility profile with no invented enabled effort.
        """
        return ModelReasoningProfileDAO(supported_levels=("off",), default_level="off")

    @staticmethod
    def _recognized_efforts(*, efforts: object | None) -> tuple[ReasoningLevel, ...]:
        """Return known canonical efforts, treating explicit null as full gateway vocabulary."""
        if efforts is None:
            return tuple(
                level for level in CANONICAL_REASONING_LEVEL_ORDER if level != "off"
            )  # type: ignore[return-value]
        if not isinstance(efforts, list):
            return ()
        values: set[str] = {value for value in efforts if isinstance(value, str)}
        return tuple(
            level for level in CANONICAL_REASONING_LEVEL_ORDER if level != "off" and level in values
        )  # type: ignore[return-value]

    @staticmethod
    def _default_effort(*, value: object | None, supported: tuple[ReasoningLevel, ...]) -> ReasoningLevel:
        """Return an advertised default when valid, otherwise the lowest enabled effort."""
        if isinstance(value, str) and value in supported:
            return cast(ReasoningLevel, value)
        return supported[0]

    @staticmethod
    def _build_reasoning_profile(
        *,
        recognized: tuple[ReasoningLevel, ...],
        default_effort: ReasoningLevel,
        mandatory: bool,
        default_enabled: bool,
    ) -> ModelReasoningProfileDAO:
        """Build one validated generic profile from complete gateway control evidence."""
        levels: tuple[ReasoningLevel, ...] = cast(tuple[ReasoningLevel, ...], ("off",) + recognized)
        effort_map: dict[ReasoningLevel, str] = {level: level for level in recognized}
        if mandatory:
            levels = recognized
        default_level: ReasoningLevel = default_effort if mandatory or default_enabled else "off"
        return ModelReasoningProfileDAO(
            supported_levels=levels,
            default_level=default_level,
            provider_effort_map=effort_map,
            # This flag means Astra-style off-preserving semantics, not mandatory clamping.
            provider_reasoning_required=False,
        )

    @staticmethod
    def _modalities(*, record: dict[str, object], field: str) -> tuple[str, ...]:
        """Preserve explicit modality evidence without inferring missing support."""
        architecture = record.get("architecture")
        if not isinstance(architecture, dict):
            return ()
        values = architecture.get(field)
        if not isinstance(values, list):
            return ()
        return tuple(value for value in values if isinstance(value, str))

    @staticmethod
    def _is_excluded_id(*, api_model_name: str) -> bool:
        """Exclude batch, automatic-router, and latest alias identities from v1 selection."""
        return (
            "batch" in api_model_name.split(":")[1:]
            or api_model_name.startswith("openrouter/")
            or "~" in api_model_name
        )

    @staticmethod
    def _display_name(*, record: dict[str, object], fallback: str) -> str:
        """Return a bounded literal label without terminal-control characters."""
        value: object | None = record.get("name")
        if not isinstance(value, str):
            return fallback
        printable: str = "".join(character for character in value if character.isprintable())
        cleaned: str = " ".join(printable.split())
        return cleaned[:160] or fallback
