"""Nonmutating request policy for catalog-constrained OpenAI Platform calls."""

from collections.abc import Mapping
from typing import ClassVar, Optional

from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from src.agents.providers.openai_codex import openai_reasoning_payload
from src.agents.reasoning_capabilities import ResolvedReasoningConfigDAO


class OpenAIRequestPolicy:
    """Protect SDK merge surfaces without I/O, credentials or catalog lookups."""

    _SAMPLING_KEYS: ClassVar[frozenset[str]] = frozenset({"temperature", "top_p", "top_logprobs", "logprobs"})
    _LOGPROBS_INCLUDE: ClassVar[str] = "message.output_text.logprobs"
    _PROTECTED_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "model",
            "model_name",
            "reasoning",
            "reasoning_effort",
            "use_responses_api",
            "output_version",
            "api_key",
            "openai_api_key",
            "base_url",
            "openai_api_base",
            "client",
            "async_client",
            "root_client",
            "root_async_client",
            "http_client",
            "http_async_client",
            "default_headers",
            "extra_headers",
        }
    )
    _CAP_KEYS: ClassVar[tuple[str, ...]] = ("max_tokens", "max_completion_tokens", "max_output_tokens")
    _EXTRA_PROTECTED_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "tools",
            "input",
            "messages",
            "stream",
            "extra_body",
            *_CAP_KEYS,
        }
    )

    @classmethod
    def normalize_output_override(cls, *, options: Mapping[str, object]) -> dict[str, object]:
        """Normalize one call cap before SDK defaults merge for the protected adapter.

        Args:
            options: Caller-owned bound or invocation options.

        Returns:
            Detached options using only max_completion_tokens for a non-null cap.

        Raises:
            ValueError: Multiple non-null caps or an invalid strict integer.
        """
        values = [options[key] for key in cls._CAP_KEYS if options.get(key) is not None]
        if len(values) > 1:
            raise ValueError("Conflicting OpenAI output limits.")
        result = {key: value for key, value in options.items() if key not in cls._CAP_KEYS}
        if values:
            result["max_completion_tokens"] = cls._positive_output_limit(value=values[0])
        return result

    @staticmethod
    def _positive_output_limit(*, value: object) -> int:
        """Validate the sole non-null output cap before SDK conversion."""
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("Invalid OpenAI output limit.")
        return value

    @classmethod
    def validate_caller_options(cls, *, options: Mapping[str, object], constructor: bool = False) -> None:
        """Reject caller conflicts before factory assembly or SDK conversion.

        Args:
            options: Caller-only options, not factory-owned fields.
            constructor: Whether caps must use the factory's explicit argument.

        Raises:
            ValueError: Protected keys or malformed late-body mappings are supplied.
        """
        forbidden = cls._PROTECTED_KEYS | (frozenset(cls._CAP_KEYS) if constructor else frozenset())
        cls._require_no_conflicts(options=options, forbidden=forbidden)
        extra = options.get("extra_body")
        if extra is None:
            return
        cls._require_no_conflicts(
            options=cls._extra_mapping(value=extra), forbidden=cls._PROTECTED_KEYS | cls._EXTRA_PROTECTED_KEYS
        )

    @staticmethod
    def _require_no_conflicts(*, options: Mapping[str, object], forbidden: frozenset[str]) -> None:
        """Reject owned keys by presence without exposing supplied values."""
        if forbidden.intersection(options):
            raise ValueError("OpenAI request options conflict with catalog policy.")

    @classmethod
    def sanitize_sampling_fields(
        cls, *, options: Mapping[str, object], forbid_sampling: bool
    ) -> dict[str, object]:
        """Copy constructor fields without broadening legacy validation.

        Args:
            options: One caller-owned surface; nested identities are retained.
            forbid_sampling: Whether effective reasoning forbids sampling.

        Returns:
            Detached surface with only the four sampling fields removed if required.
        """
        if not forbid_sampling:
            return dict(options)
        return {key: value for key, value in options.items() if key not in cls._SAMPLING_KEYS}

    @classmethod
    def sanitize(cls, *, options: Mapping[str, object], forbid_sampling: bool) -> dict[str, object]:
        """Copy strict top-level and late-body surfaces before SDK transport.

        Args:
            options: Structurally validated request fields, never mutated.
            forbid_sampling: Effective enabled reasoning restriction.

        Returns:
            Detached request fields with copied and filtered include lists.

        Raises:
            ValueError: Invalid include/body shape or disabled Responses logprobs.
        """
        result = cls._sanitize_level(options=options, forbid_sampling=forbid_sampling)
        extra = options.get("extra_body")
        if extra is not None:
            result["extra_body"] = cls._sanitize_level(
                options=cls._extra_mapping(value=extra), forbid_sampling=forbid_sampling
            )
        return result

    @classmethod
    def _sanitize_level(cls, *, options: Mapping[str, object], forbid_sampling: bool) -> dict[str, object]:
        """Sanitize one strict surface for the request policy's two merge passes."""
        if not forbid_sampling and "logprobs" in options:
            raise ValueError("Use Responses include for logprobs.")
        result = cls.sanitize_sampling_fields(options=options, forbid_sampling=forbid_sampling)
        if "include" in result:
            result["include"] = cls._include(value=result["include"], forbid_sampling=forbid_sampling)
        return result

    @staticmethod
    def _extra_mapping(*, value: object) -> dict[str, object]:
        """Validate and detach extra_body for strict sanitation without echoing values."""
        if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
            raise ValueError("Invalid OpenAI extra_body options.")
        return dict(value)

    @classmethod
    def _include(cls, *, value: object, forbid_sampling: bool) -> Optional[list[str]]:
        """Copy valid include lists and remove only the enabled logprobs request."""
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("Invalid OpenAI include options.")
        return [item for item in value if not forbid_sampling or item != cls._LOGPROBS_INCLUDE]


class OpenAIPlatformChatOpenAI(ChatOpenAI):
    """Apply lifetime-pinned catalog policy at the existing SDK payload boundary."""

    _policy_model_name: Optional[str] = PrivateAttr(default=None)
    _policy_reasoning: Optional[ResolvedReasoningConfigDAO] = PrivateAttr(default=None)
    _policy_forbid_sampling: bool = PrivateAttr(default=False)

    def configure_request_policy(
        self, *, model_name: str, reasoning: ResolvedReasoningConfigDAO, forbid_sampling: bool
    ) -> None:
        """Pin factory policy once before tool binding for this client's lifetime.

        Args:
            model_name: Exact admitted API identity.
            reasoning: Resolved configuration copied before retention.
            forbid_sampling: Effective enabled profile restriction.

        Raises:
            ValueError: This client already has a policy.
        """
        if self._policy_reasoning is not None:
            raise ValueError("OpenAI request policy is already configured.")
        self._policy_reasoning = reasoning.model_copy(deep=True)
        self._policy_model_name = model_name
        self._policy_forbid_sampling = forbid_sampling

    def _require_request_policy(self) -> ResolvedReasoningConfigDAO:
        """Reject unconfigured adapter use before the SDK can construct a request."""
        if self._policy_reasoning is None or self._policy_model_name is None:
            raise ValueError("OpenAI request policy is not configured.")
        return self._policy_reasoning

    def _get_request_payload(
        self, input_: LanguageModelInput, *, stop: Optional[list[str]] = None, **kwargs: object
    ) -> dict[str, object]:
        """Protect merged options while delegating tool conversion to LangChain.

        Args:
            input_: SDK messages or prompt.
            stop: Existing optional stop input.
            kwargs: Bound/call options before SDK conversion.

        Returns:
            Detached Responses payload for the inherited transport.

        Raises:
            ValueError: Missing policy or invalid/conflicting caller options.
        """
        reasoning = self._require_request_policy()
        OpenAIRequestPolicy.validate_caller_options(options=kwargs)
        normalized = OpenAIRequestPolicy.normalize_output_override(options=kwargs)
        sanitized = OpenAIRequestPolicy.sanitize(
            options=normalized, forbid_sampling=self._policy_forbid_sampling
        )
        payload = super()._get_request_payload(input_=input_, stop=stop, **sanitized)
        result = OpenAIRequestPolicy.sanitize(options=payload, forbid_sampling=self._policy_forbid_sampling)
        result["model"] = self._policy_model_name
        result.pop("reasoning_effort", None)
        result["reasoning"] = openai_reasoning_payload(reasoning=reasoning)
        return result
