"""OpenRouter Chat Completions payload policy and LangChain adapter."""

from __future__ import annotations

import json
import logging
import math
from contextvars import ContextVar
from typing import Any, AsyncIterator, ClassVar, Iterator, Optional, Sequence, cast

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.prompt_values import PromptValue

from src.agents.providers.message_extension import (
    PROVIDER_MESSAGE_EXTENSION_KEY,
    ProviderMessageExtensionDAO,
)
from src.auth.credential_dao import ProviderName
from src.agents.model_catalog.dao import ModelCapabilitiesDAO
from langchain_openai import ChatOpenAI
from pydantic import Field, JsonValue

from src.integrations.openrouter.exceptions import OpenRouterAPIError

_OPENAI_SDK_LOGGER_NAME: str = "openai._base_client"
_OPENROUTER_PRIVATE_REQUEST_LOG_DEPTH: ContextVar[int] = ContextVar(
    "openrouter_private_request_log_depth",
    default=0,
)


class _OpenRouterPrivateRequestLogFilter(logging.Filter):
    """Protect private SDK request options and transport exception diagnostics."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Project SDK diagnostics inside the active adapter request only.

        The SDK emits raw transport tracebacks before adapter normalization.
        Retain their fixed labels but clear traceback data; unrelated records
        and direct-provider contexts are unchanged.

        Args:
            record (logging.LogRecord): SDK record before handler formatting.

        Returns:
            bool: False only for private request options, True for safe diagnostics.
        """
        if _OPENROUTER_PRIVATE_REQUEST_LOG_DEPTH.get() == 0 or record.name != _OPENAI_SDK_LOGGER_NAME:
            return True
        if record.msg == "Request options: %s":
            return False
        # SDK transport diagnostics attach raw exceptions before our normalizer
        # runs. Preserve their fixed diagnostic label, not the private traceback.
        if record.msg in {
            "Encountered Exception",
            "Encountered httpx.TimeoutException",
            "Encountered httpx.HTTPStatusError",
        }:
            record.exc_info = None
            record.exc_text = None
        return True


class _OpenRouterPrivateRequestLogScope:
    """Own the temporary OpenAI SDK filter and ContextVar scope for one adapter request."""

    def __enter__(self) -> "_OpenRouterPrivateRequestLogScope":
        """Install the owned filter immediately before the SDK builds a private request.

        Returns:
            _OpenRouterPrivateRequestLogScope: Active request scope.
        """
        self._logger: logging.Logger = logging.getLogger(_OPENAI_SDK_LOGGER_NAME)
        # Each scope owns its filter: another task/thread or nested request may
        # exit first without removing this request's protection.
        self._filter = _OpenRouterPrivateRequestLogFilter()
        self._logger.addFilter(self._filter)
        current_depth = _OPENROUTER_PRIVATE_REQUEST_LOG_DEPTH.get()
        self._token = _OPENROUTER_PRIVATE_REQUEST_LOG_DEPTH.set(current_depth + 1)
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        """Restore the task-local depth and remove the owned filter after the SDK request."""
        _OPENROUTER_PRIVATE_REQUEST_LOG_DEPTH.reset(self._token)
        self._logger.removeFilter(self._filter)


class OpenRouterReasoningPolicy:
    """Translate verified OpenRouter reasoning metadata into gateway fields."""

    @classmethod
    def build(
        cls, *, controls_available: bool, reasoning_effort: Optional[str], disable_available: bool = False
    ) -> dict[str, object]:
        """Return a known reasoning control or no request control.

        Args:
            controls_available (bool): Catalog evidence that the provider exposes controls.
            reasoning_effort (Optional[str]): Catalog-clamped provider effort.

        Returns:
            dict[str, object]: Gateway reasoning object or an empty mapping.
        """
        if not controls_available:
            return {}
        if reasoning_effort is None:
            return {"reasoning": {"enabled": False}} if disable_available else {}
        return {"reasoning": {"effort": reasoning_effort}}


class OpenRouterRequestPolicy:
    """Build the narrow Chat Completions-only fields accepted by OpenRouter."""

    @staticmethod
    def output_ceiling(*, entry: object) -> int:
        """Return the immutable prepared output cap for one OpenRouter catalog entry.

        Args:
            entry (object): Prepared entry whose capabilities and runtime profile
                are read only through the catalog's stable attribute contract.

        Returns:
            int: The lower reported-or-local cap and half-context bound.
        """
        capabilities: object | None = getattr(entry, "capabilities", None)
        reported_ceiling: object | None = getattr(capabilities, "reported_output_ceiling", None)
        runtime_profile: object | None = getattr(entry, "runtime_profile", None)
        context_window: object | None = getattr(runtime_profile, "context_window", None)
        if type(reported_ceiling) is not int or reported_ceiling <= 0:
            reported_ceiling = 4096
        if type(context_window) is not int or context_window <= 0:
            return reported_ceiling
        return min(reported_ceiling, context_window // 2)

    @staticmethod
    def validate_output_cap(*, max_tokens: object, ceiling: int) -> None:
        """Reject invalid output limits before the factory resolves credentials.

        Args:
            max_tokens (object): Untrusted explicit or prepared request limit.
            ceiling (int): Pinned effective catalog output policy.

        Raises:
            ValueError: The request exceeds or violates the prepared output cap.
        """
        if type(max_tokens) is not int or not 0 < max_tokens <= ceiling:
            raise ValueError("OpenRouter output cap must be a positive integer within the prepared limit.")

    @staticmethod
    def validate_sampling(*, options: dict[str, object], supported: tuple[str, ...]) -> None:
        """Validate explicit sampling before credential/client construction or HTTP.

        Args:
            options: Caller-provided sampling fields only.
            supported: Parameters advertised by the pinned catalog entry.

        Raises:
            ValueError: A field is unsupported, nonnumeric, nonfinite or out of range.
        """
        bounds = {"temperature": (0.0, 2.0), "top_p": (0.0, 1.0)}
        for name, value in options.items():
            if name not in bounds or name not in supported:
                raise ValueError("OpenRouter unsupported request parameter.")
            if type(value) not in {int, float} or not isinstance(value, (int, float)):
                raise ValueError("OpenRouter sampling parameter must be numeric.")
            lower, upper = bounds[name]
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError("OpenRouter sampling parameter is out of range.")

    @classmethod
    def validate_controls(cls, *, options: dict[str, object], supported: tuple[str, ...]) -> None:
        """Validate caller controls before factory construction or SDK serialization.

        Args:
            options: Explicit optional controls, including serialized function tools.
            supported: Parameter evidence from the pinned catalog.

        Raises:
            ValueError: A control lacks advertised support or has an invalid value.
        """
        for name, value in options.items():
            if name not in supported:
                raise ValueError("OpenRouter unsupported request parameter.")
            cls._validate_control(name=name, value=value, options=options, supported=supported)

    @classmethod
    def _validate_control(
        cls, *, name: str, value: object, options: dict[str, object], supported: tuple[str, ...]
    ) -> None:
        """Dispatch one advertised control to its strict wire-shape validator."""
        if name in {"temperature", "top_p"}:
            cls.validate_sampling(options={name: value}, supported=supported)
            return
        if name == "stop":
            cls._validate_stop(value=value)
            return
        if name == "tools":
            cls._validate_tools(value=value, supported=supported)
            return
        if name == "tool_choice":
            cls._validate_tool_choice(value=value, tools=options.get("tools"))
            return
        if name == "parallel_tool_calls" and type(value) is bool:
            return
        if name == "seed" and type(value) is int and value >= 0:
            return
        if name in {"frequency_penalty", "presence_penalty"}:
            cls._validate_penalty(value=value)
            return
        if name == "logprobs" and type(value) is bool:
            return
        if name == "top_logprobs":
            cls._validate_top_logprobs(value=value, logprobs=options.get("logprobs"))
            return
        raise ValueError("OpenRouter invalid request parameter.")

    @staticmethod
    def _validate_penalty(*, value: object) -> None:
        """Require a finite frequency or presence penalty in the gateway range."""
        if type(value) not in {int, float} or not isinstance(value, (int, float)):
            raise ValueError("OpenRouter invalid penalty parameter.")
        if not math.isfinite(value) or not -2.0 <= value <= 2.0:
            raise ValueError("OpenRouter invalid penalty parameter.")

    @staticmethod
    def _validate_top_logprobs(*, value: object, logprobs: object) -> None:
        """Require an enabled logprobs flag and an integer count from zero through twenty."""
        if logprobs is not True or type(value) is not int or not 0 <= value <= 20:
            raise ValueError("OpenRouter invalid top_logprobs parameter.")

    @staticmethod
    def _validate_stop(*, value: object) -> None:
        """Require a nonempty stop string or a nonempty list of nonempty strings."""
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not values:
            raise ValueError("OpenRouter invalid stop parameter.")
        if not all(isinstance(item, str) and item for item in values):
            raise ValueError("OpenRouter invalid stop parameter.")

    @staticmethod
    def _validate_tools(*, value: object, supported: tuple[str, ...]) -> None:
        """Reject non-function tools and unadvertised or malformed nested strict controls."""
        if not isinstance(value, list):
            raise ValueError("OpenRouter invalid tools parameter.")
        for tool in value:
            if not isinstance(tool, dict) or tool.get("type") != "function":
                raise ValueError("OpenRouter invalid function tool.")
            function = tool.get("function")
            if (
                not isinstance(function, dict)
                or not isinstance(function.get("name"), str)
                or not function["name"]
            ):
                raise ValueError("OpenRouter invalid function tool.")
            if "parameters" in function and not isinstance(function["parameters"], dict):
                raise ValueError("OpenRouter invalid function tool.")
            if "strict" in function and ("strict" not in supported or type(function["strict"]) is not bool):
                raise ValueError("OpenRouter invalid strict parameter.")

    @staticmethod
    def _validate_tool_choice(*, value: object, tools: object) -> None:
        """Accept gateway choice literals or an exact name from the bound function tools."""
        if isinstance(value, str) and value in {"auto", "none"}:
            return
        if value == "required" and isinstance(tools, list) and tools:
            return
        if not isinstance(value, dict) or set(value) != {"type", "function"}:
            raise ValueError("OpenRouter invalid tool_choice parameter.")
        function = value.get("function")
        if value["type"] != "function" or not isinstance(function, dict) or set(function) != {"name"}:
            raise ValueError("OpenRouter invalid tool_choice parameter.")
        names = (
            [tool.get("function", {}).get("name") for tool in tools if isinstance(tool, dict)]
            if isinstance(tools, list)
            else []
        )
        if not isinstance(function["name"], str) or function["name"] not in names:
            raise ValueError("OpenRouter unknown tool_choice function.")

    @classmethod
    def build(
        cls,
        *,
        max_tokens: int,
        reasoning_effort: Optional[str],
        controls_available: bool,
        disable_available: bool = False,
    ) -> dict[str, object]:
        """Build request kwargs with fixed gateway routing requirements.

        Args:
            max_tokens (int): Prepared catalog output cap.
            reasoning_effort (Optional[str]): Catalog-clamped provider effort.
            controls_available (bool): Whether catalog metadata proved reasoning controls.

        Returns:
            dict[str, object]: Safe ChatOpenAI construction kwargs.
        """
        extra_body: dict[str, object] = {"provider": {"require_parameters": True}}
        extra_body.update(
            OpenRouterReasoningPolicy.build(
                controls_available=controls_available,
                disable_available=disable_available,
                reasoning_effort=reasoning_effort,
            )
        )
        return {"max_tokens": max_tokens, "extra_body": extra_body}


class OpenRouterMessageCodec:
    """Invocation-local assembly of bounded opaque continuation metadata."""

    def __init__(self, *, model_name: str) -> None:
        """Start empty metadata for one adapter stream, discarded on exit.

        Args:
            model_name (str): Exact canonical source route.
        """
        self.model_name = model_name
        self.details: list[dict[str, JsonValue]] = []
        self.indexed: dict[int, dict[str, JsonValue]] = {}
        self.reasoning: Optional[str] = None

    def append(self, *, extension: ProviderMessageExtensionDAO) -> None:
        """Merge a validated delta before any private metadata is yielded.

        Args:
            extension (ProviderMessageExtensionDAO): One gateway delta.

        Raises:
            OpenRouterAPIError: Conflicting or oversized metadata.
        """
        for detail in extension.reasoning_details:
            self._append_detail(detail=detail)
        if extension.reasoning is not None:
            self.reasoning = (self.reasoning or "") + extension.reasoning
        self.build()

    def _append_detail(self, *, detail: object) -> None:
        """Merge one JSON object, retaining indexed fragments in first-seen order."""
        validated_detail = self._validated_detail(detail=detail)
        index = validated_detail.get("index")
        if index is None:
            self.details.append(validated_detail)
            return
        if type(index) is not int or index < 0:
            raise OpenRouterAPIError(error_type="invalid_request")
        target = self._indexed_target(index=index)
        for key, value in validated_detail.items():
            self._merge_field(target=target, key=key, value=value)

    @staticmethod
    def _validated_detail(*, detail: object) -> dict[str, JsonValue]:
        """Validate one opaque gateway detail as a JSON object before retaining it."""
        if not isinstance(detail, dict):
            raise OpenRouterAPIError(error_type="invalid_request")
        try:
            return cast(dict[str, JsonValue], json.loads(json.dumps(detail, allow_nan=False)))
        except (TypeError, ValueError):
            raise OpenRouterAPIError(error_type="invalid_request") from None

    def _indexed_target(self, *, index: int) -> dict[str, JsonValue]:
        """Return the stable accumulator mapping for one validated detail index."""
        if index not in self.indexed:
            self.indexed[index] = {}
            self.details.append(self.indexed[index])
        return self.indexed[index]

    @staticmethod
    def _merge_field(*, target: dict[str, JsonValue], key: str, value: JsonValue) -> None:
        """Concatenate text fragments while requiring stable values to agree."""
        if key in {"text", "summary", "data"}:
            if not isinstance(value, str):
                raise OpenRouterAPIError(error_type="invalid_request")
            existing: JsonValue | None = target.get(key)
            if existing is not None and not isinstance(existing, str):
                raise OpenRouterAPIError(error_type="invalid_request")
            target[key] = (existing or "") + value
            return
        if key in target and target[key] != value:
            raise OpenRouterAPIError(error_type="invalid_request")
        target[key] = value

    def build(self) -> ProviderMessageExtensionDAO:
        """Return the validated complete extension for the final metadata-only chunk."""
        details: list[JsonValue] = list(self.details)
        extension = ProviderMessageExtensionDAO(
            provider=ProviderName.OPENROUTER,
            source_model_name=self.model_name,
            reasoning=self.reasoning,
            reasoning_details=details,
        )
        self.validate(extension=extension)
        return extension

    @staticmethod
    def validate(*, extension: ProviderMessageExtensionDAO) -> None:
        """Reject non-JSON and greater-than-8MiB metadata without retaining error text."""
        try:
            encoded = json.dumps(extension.model_dump(), allow_nan=False, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise OpenRouterAPIError(error_type="invalid_request") from None
        if len(encoded) > 8 * 1024 * 1024:
            raise OpenRouterAPIError(error_type="invalid_request")


class OpenRouterChatOpenAI(ChatOpenAI):
    """A ChatOpenAI adapter pinned to OpenRouter Chat Completions semantics."""

    slo_model_name: str = Field(
        exclude=True,
        description="Canonical OpenRouter route used only for private continuation matching.",
    )
    slo_capabilities: Optional[ModelCapabilitiesDAO] = Field(
        default=None,
        exclude=True,
        description="Prepared immutable input and request-control evidence for this route.",
    )
    slo_output_ceiling: Optional[int] = Field(
        default=None,
        exclude=True,
        description="Prepared maximum output tokens enforced before the SDK sends a request.",
    )
    _stream_reasoning_extension: ClassVar[ContextVar[Optional[OpenRouterMessageCodec]]] = ContextVar(
        "openrouter_stream_reasoning_extension",
        default=None,
    )

    def __init__(self, *, slo_model_name: str, **kwargs: Any) -> None:
        """Create a no-retry, Chat-Completions-only gateway adapter.

        Args:
            slo_model_name (str): Canonical Slo route retained outside provider wire payloads.
            **kwargs (object): Validated base ChatOpenAI construction arguments.
        """
        super().__init__(slo_model_name=slo_model_name, **kwargs)  # type: ignore[call-arg]

    def cap_compaction_summary_kwargs(self, *, kwargs: dict[str, object]) -> dict[str, object]:
        """Clamp one internal compaction request to this adapter's pinned output ceiling.

        WHAT: Produces a detached kwargs mapping with this concrete route's
            immutable cap, so ModelPool fallback never inherits a larger lane's
            summary budget.
        WHO: ModelPool calls this only after selecting this member.
        WHEN: During compaction's internal marked summary request, before SDK
            request construction and without affecting ordinary caller caps.

        Args:
            kwargs (dict[str, object]): Marker-free summary request kwargs.

        Returns:
            dict[str, object]: Summary kwargs bounded by this route's output ceiling.
        """
        requested = kwargs.get("max_tokens")
        if type(requested) is not int:
            return kwargs
        ceiling = self.slo_output_ceiling or self.max_tokens or 4096
        return {**kwargs, "max_tokens": min(requested, ceiling)}

    def _get_request_payload(
        self,
        input_: (
            PromptValue | str | Sequence[BaseMessage | list[str] | tuple[str, str] | str | dict[str, Any]]
        ),
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build an exact Chat Completions gateway body before the SDK sends it.

        Called by LangChain for every OpenRouter invocation. The adapter keeps
        normal message/tool conversion in the base implementation. Gateway
        controls stay in ``extra_body`` until the SDK merges them into HTTP JSON;
        promoting them here would pass unsupported keywords to SDK create().

        Args:
            input_ (object): LangChain messages accepted by the base converter.
            **kwargs (Any): Per-invocation LangChain keyword arguments.

        Returns:
            dict[str, Any]: Chat Completions payload with gateway requirements.
        """
        self._validate_invocation_options(options=kwargs)
        messages = self._convert_input(input_).to_messages()
        outbound_messages = self._outbound_messages_without_visible_reasoning(messages=messages)
        self._validate_message_modalities(messages=outbound_messages)
        payload: dict[str, Any] = super()._get_request_payload(input_=outbound_messages, **kwargs)
        self._validate_payload_controls(payload=payload)
        self._attach_same_route_extensions(payload=payload, input_=input_)
        if payload.get("stream"):
            payload["stream_options"] = {"include_usage": True}
        else:
            payload.pop("stream_options", None)
        return payload

    @staticmethod
    def _outbound_messages_without_visible_reasoning(*, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Build detached wire messages without adapter-generated visible reasoning blocks.

        WHAT: Removes only ``type='reasoning'`` blocks generated by this adapter
            from assistant content before a tool continuation reaches Chat
            Completions.
        WHO: ``_get_request_payload`` calls this before validating and converting
            messages for every OpenRouter request.
        WHEN: A live assistant response can contain visible plaintext reasoning
            and a tool call; its next request must retain ordinary content, tool
            calls, and private same-route metadata without sending that display-only
            block as an unsupported input modality.

        Args:
            messages (list[BaseMessage]): Immutable caller messages normalized by LangChain.

        Returns:
            list[BaseMessage]: Original messages except cloned assistant messages
            whose content omits adapter-generated visible reasoning blocks.
        """
        return [
            OpenRouterChatOpenAI._outbound_message_without_visible_reasoning(message=message)
            for message in messages
        ]

    @staticmethod
    def _outbound_message_without_visible_reasoning(*, message: BaseMessage) -> BaseMessage:
        """Clone one assistant message only when it contains visible reasoning blocks.

        Args:
            message (BaseMessage): One normalized LangChain request message.

        Returns:
            BaseMessage: The untouched source message or a detached assistant clone.
        """
        if not isinstance(message, AIMessage):
            return message
        content = message.content
        if not isinstance(content, list):
            return message
        outbound_content = [
            block for block in content if not (isinstance(block, dict) and block.get("type") == "reasoning")
        ]
        if len(outbound_content) == len(content):
            return message
        return message.model_copy(update={"content": outbound_content})

    def _validate_message_modalities(self, *, messages: list[BaseMessage]) -> None:
        """Check user, tool and replay content before LangChain wire conversion.

        The prepared route's input modalities are the sole admission evidence:
        a supported image block reaches the base Chat Completions converter
        unchanged, while every other structured block fails before HTTP.

        Args:
            messages (list[BaseMessage]): Original normalized messages for this request.

        Raises:
            OpenRouterAPIError: Non-text input lacks explicit image capability.
        """
        for message in messages:
            self._validate_message_content(content=message.content)

    def _validate_message_content(self, *, content: object) -> None:
        """Validate one normalized message content value against prepared input capabilities.

        Called by :meth:`_validate_message_modalities` once for each history
        message before the SDK converter runs. It preserves supported image
        blocks for that converter and rejects malformed structured content at
        the provider compatibility boundary.

        Args:
            content (object): One LangChain message content value.

        Raises:
            OpenRouterAPIError: The content has an unsupported or malformed block.
        """
        if isinstance(content, str):
            return
        if not isinstance(content, list):
            raise OpenRouterAPIError(error_type="invalid_request")
        for block in content:
            self._validate_message_block(block=block)

    def _validate_message_block(self, *, block: object) -> None:
        """Accept text and explicitly supported image blocks only.

        Called for each structured block in one outbound message. The catalog
        capability is immutable for this adapter instance, so callers cannot
        widen input modality support at invocation time.

        Args:
            block (object): One structured LangChain content block.

        Raises:
            OpenRouterAPIError: The block is malformed or uses an unsupported modality.
        """
        if isinstance(block, str):
            return
        if not isinstance(block, dict):
            raise OpenRouterAPIError(error_type="invalid_request")
        kind: object | None = block.get("type")
        if kind == "text":
            return
        modalities: tuple[str, ...] = self.slo_capabilities.input_modalities if self.slo_capabilities else ()
        if kind in {"image", "image_url"} and "image" in modalities:
            return
        raise OpenRouterAPIError(error_type="invalid_request")

    def _validate_invocation_options(self, *, options: dict[str, object]) -> None:
        """Reject request overrides before the SDK creates an HTTP request.

        The factory supplies immutable capability evidence and the effective cap.
        Internal stop/stream controls remain LangChain-owned; routing and gateway
        body overrides are never caller-owned.

        Args:
            options: Invocation arguments before base payload conversion.

        Raises:
            OpenRouterAPIError: An unsupported or invalid override is present.
        """
        allowed = {"stream", "max_tokens", "max_completion_tokens"}
        controls = {
            "stop",
            "tools",
            "temperature",
            "top_p",
            "parallel_tool_calls",
            "tool_choice",
            "seed",
            "frequency_penalty",
            "presence_penalty",
            "logprobs",
            "top_logprobs",
        }
        supported = self.slo_capabilities.supported_parameters if self.slo_capabilities else ()
        for name, value in options.items():
            if name == "stream_options" and value == {"include_usage": True}:
                continue
            if name in {"max_tokens", "max_completion_tokens"}:
                ceiling = self.slo_output_ceiling or self.max_tokens or 4096
                try:
                    OpenRouterRequestPolicy.validate_output_cap(max_tokens=value, ceiling=ceiling)
                except ValueError:
                    raise OpenRouterAPIError(error_type="invalid_request") from None
                continue
            if name in controls:
                if name == "stop" and value is None:
                    continue  # LangChain passes its absent stop sentinel explicitly.
                try:
                    OpenRouterRequestPolicy.validate_controls(
                        options={
                            key: item
                            for key, item in options.items()
                            if key in controls and not (key == "stop" and item is None)
                        },
                        supported=supported,
                    )
                except ValueError:
                    raise OpenRouterAPIError(error_type="invalid_request") from None
                continue
            if name not in allowed:
                raise OpenRouterAPIError(error_type="invalid_request")

    def _validate_payload_controls(self, *, payload: dict[str, object]) -> None:
        """Recheck merged constructor/bound controls immediately before the SDK boundary."""
        controls = {
            "stop",
            "tools",
            "temperature",
            "top_p",
            "parallel_tool_calls",
            "tool_choice",
            "seed",
            "frequency_penalty",
            "presence_penalty",
            "logprobs",
            "top_logprobs",
        }
        supported = self.slo_capabilities.supported_parameters if self.slo_capabilities else ()
        try:
            OpenRouterRequestPolicy.validate_controls(
                options={key: value for key, value in payload.items() if key in controls},
                supported=supported,
            )
        except ValueError:
            raise OpenRouterAPIError(error_type="invalid_request") from None

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        """Run one non-streaming request with private SDK request-option logging suppressed.

        Called by LangChain's synchronous invoke path after the adapter has
        added replay-only continuation metadata. The temporary filter is scoped
        to this call and leaves unrelated SDK DEBUG records intact.

        Returns:
            ChatResult: The base ChatOpenAI result.
        """
        try:
            with self._private_request_log_redaction():
                return super()._generate(*args, **kwargs)
        except Exception as error:
            raise OpenRouterErrorNormalizer.normalize(error=error) from None

    async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
        """Run one asynchronous request with private SDK request-option logging suppressed.

        Called by LangChain's async invoke path after the adapter has added
        replay-only continuation metadata. The temporary filter is scoped to
        this task's request and restores logging state before returning.

        Returns:
            ChatResult: The base ChatOpenAI result.
        """
        try:
            with self._private_request_log_redaction():
                return await super()._agenerate(*args, **kwargs)
        except Exception as error:
            raise OpenRouterErrorNormalizer.normalize(error=error) from None

    def _private_request_log_redaction(self) -> "_OpenRouterPrivateRequestLogScope":
        """Create the one-request OpenAI SDK logging redaction scope.

        Returns:
            _OpenRouterPrivateRequestLogScope: Scope that filters only private request options.
        """
        return _OpenRouterPrivateRequestLogScope()

    def _attach_same_route_extensions(
        self,
        *,
        payload: dict[str, Any],
        input_: (
            PromptValue | str | Sequence[BaseMessage | list[str] | tuple[str, str] | str | dict[str, Any]]
        ),
    ) -> None:
        """Attach opaque continuation fields after the base message converter runs.

        Called only by :meth:`_get_request_payload` for the outgoing message
        list. It rejects malformed private metadata by treating it as absent,
        and it never forwards metadata across a provider or canonical-route
        boundary.

        Args:
            payload (dict[str, Any]): Base Chat Completions payload to amend.
            input_ (object): Original LangChain message sequence.
        """
        if not isinstance(input_, Sequence):
            return
        messages: object | None = payload.get("messages")
        if not isinstance(messages, list):
            return
        for source_message, wire_message in zip(input_, messages):
            self._attach_message_extension(source_message=source_message, wire_message=wire_message)

    def _attach_message_extension(self, *, source_message: object, wire_message: object) -> None:
        """Apply one same-route assistant extension to its converted wire message.

        Args:
            source_message (object): Original LangChain message carrying private metadata.
            wire_message (object): Converted Chat Completions message mapping.
        """
        if not isinstance(source_message, BaseMessage) or not isinstance(wire_message, dict):
            return
        if wire_message.get("role") != "assistant":
            return
        extension_data: object | None = source_message.additional_kwargs.get(PROVIDER_MESSAGE_EXTENSION_KEY)
        try:
            extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO.model_validate(
                extension_data
            )
        except ValueError:
            return
        if extension.provider is not ProviderName.OPENROUTER:
            return
        if extension.source_model_name != self.slo_model_name:
            return
        if extension.reasoning_details:
            wire_message["reasoning_details"] = extension.reasoning_details
            return
        if extension.reasoning is not None:
            wire_message["reasoning"] = extension.reasoning

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        """Yield normalized gateway chunks from a synchronous Chat Completions stream.

        Called by LangChain after request construction. It preserves the base
        SDK stream and converts every provider failure at the adapter boundary.

        Args:
            *args (Any): Base ChatOpenAI positional stream arguments.
            **kwargs (Any): Base ChatOpenAI keyword stream arguments.

        Yields:
            ChatGenerationChunk: A standard normalized LangChain generation chunk.
        """
        token = self._stream_reasoning_extension.set(OpenRouterMessageCodec(model_name=self.slo_model_name))
        committed = False
        try:
            with self._private_request_log_redaction():
                for chunk in super()._stream(*args, **kwargs):
                    committed = True
                    yield chunk
            yield from self._final_extension_chunks()
        except Exception as error:
            normalized = OpenRouterErrorNormalizer.normalize(error=error)
            normalized.partial_output_committed = committed
            raise normalized from None
        finally:
            self._stream_reasoning_extension.reset(token)

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        """Yield normalized gateway chunks from an asynchronous Chat Completions stream.

        Called by LangChain for every asynchronous stream. A failure after an
        already-yielded chunk remains an exception and is never converted into
        an empty successful result.

        Args:
            *args (Any): Base ChatOpenAI positional stream arguments.
            **kwargs (Any): Base ChatOpenAI keyword stream arguments.

        Yields:
            ChatGenerationChunk: A standard normalized LangChain generation chunk.
        """
        token = self._stream_reasoning_extension.set(OpenRouterMessageCodec(model_name=self.slo_model_name))
        committed = False
        try:
            with self._private_request_log_redaction():
                async for chunk in super()._astream(*args, **kwargs):
                    committed = True
                    yield chunk
            for chunk in self._final_extension_chunks():
                yield chunk
        except Exception as error:
            normalized = OpenRouterErrorNormalizer.normalize(error=error)
            normalized.partial_output_committed = committed
            raise normalized from None
        finally:
            self._stream_reasoning_extension.reset(token)

    def _final_extension_chunks(self) -> Iterator[ChatGenerationChunk]:
        """Emit complete private metadata exactly once after successful stream exhaustion."""
        codec = self._stream_reasoning_extension.get()
        if codec is None:
            return
        extension = codec.build()
        if extension.reasoning is not None or extension.reasoning_details:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    additional_kwargs={PROVIDER_MESSAGE_EXTENSION_KEY: extension.model_dump(mode="json")},
                )
            )

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type[AIMessageChunk],
        base_generation_info: Optional[dict[str, Any]],
    ) -> Optional[ChatGenerationChunk]:
        """Attach gateway reasoning metadata to the streamed assistant chunk.

        Called by LangChain once per parsed SSE frame. The extension is held in
        invocation-local context until the normal chunk combiner returns its
        final assistant message, avoiding mutable adapter instance state.

        Args:
            chunk (dict[str, Any]): Parsed Chat Completions SSE frame.
            default_chunk_class (type[AIMessageChunk]): LangChain chunk class.
            base_generation_info (Optional[dict[str, Any]]): Base stream metadata.

        Returns:
            Optional[ChatGenerationChunk]: Converted chunk with private metadata.
        """
        OpenRouterErrorNormalizer.raise_for_payload(payload=chunk)
        chunk = self._project_refusal(payload=chunk, message_key="delta")
        chunk = self._project_visible_reasoning(payload=chunk, message_key="delta")
        generation: Optional[ChatGenerationChunk] = super()._convert_chunk_to_generation_chunk(
            chunk=chunk,
            default_chunk_class=default_chunk_class,
            base_generation_info=base_generation_info,
        )
        extension: Optional[ProviderMessageExtensionDAO] = self._extension_from_stream_chunk(chunk=chunk)
        codec = self._stream_reasoning_extension.get()
        if extension is not None and codec is not None:
            codec.append(extension=extension)
        if generation is not None and (generation.generation_info or {}).get("finish_reason") == "length":
            self._append_output_limit_notice(message=generation.message)
        return generation

    def _extension_from_stream_chunk(self, *, chunk: dict[str, Any]) -> Optional[ProviderMessageExtensionDAO]:
        """Extract one gateway extension from an SSE choice delta.

        Args:
            chunk (dict[str, Any]): Parsed Chat Completions SSE frame.

        Returns:
            Optional[ProviderMessageExtensionDAO]: Metadata carried by this delta.
        """
        choices: object | None = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first_choice: object = choices[0]
        if not isinstance(first_choice, dict):
            return None
        delta: object | None = first_choice.get("delta")
        if not isinstance(delta, dict):
            return None
        return self._extension_from_gateway_message(message=delta)

    def _create_chat_result(
        self,
        response: dict[str, Any] | Any,
        generation_info: Optional[dict[str, Any]] = None,
    ) -> ChatResult:
        """Attach same-route continuation metadata to a completed nonstream response.

        Called by LangChain after its ordinary Chat Completions converter has
        reconstructed tool calls. OpenRouter-specific reasoning fields are
        copied only to the corresponding assistant result, where the existing
        outbound codec can preserve them for a same-route tool continuation.

        Args:
            response (dict[str, Any] | Any): OpenAI SDK or mapping response.
            generation_info (Optional[dict[str, Any]]): Base generation metadata.

        Returns:
            ChatResult: Standard LangChain result with private replay metadata.
        """
        payload: object = (
            response if isinstance(response, dict) else self._model_dump_response(response=response)
        )
        if isinstance(payload, dict):
            OpenRouterErrorNormalizer.raise_for_payload(payload=payload)
            choices = payload.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise OpenRouterAPIError(error_type="invalid_request")
        if isinstance(payload, dict):
            response = self._project_refusal(payload=payload, message_key="message")
            response = self._project_visible_reasoning(payload=response, message_key="message")
        result: ChatResult = super()._create_chat_result(
            response=response,
            generation_info=generation_info,
        )
        self._attach_result_extension(result=result, response=response)
        self._mark_length_completion(result=result, payload=payload)
        return result

    @staticmethod
    def _project_visible_reasoning(*, payload: dict[str, Any], message_key: str) -> dict[str, Any]:
        """Copy only plaintext reasoning summaries into the existing visible thinking path.

        Args:
            payload (dict[str, Any]): Successful gateway response or stream frame.
            message_key (str): The transport's message or delta field.

        Returns:
            dict[str, Any]: Detached payload with visible reasoning blocks and opaque details untouched.
        """
        choices: object | None = payload.get("choices")
        if not isinstance(choices, list):
            return payload
        projected: list[object] = []
        for choice in choices:
            message: object | None = choice.get(message_key) if isinstance(choice, dict) else None
            if not isinstance(message, dict):
                projected.append(choice)
                continue
            visible_content: list[dict[str, str]] = []
            reasoning: object | None = message.get("reasoning", message.get("reasoning_content"))
            if isinstance(reasoning, str) and reasoning:
                visible_content.append({"type": "reasoning", "text": reasoning})
            details: object | None = message.get("reasoning_details")
            if isinstance(details, list):
                for detail in details:
                    if isinstance(detail, dict) and isinstance(detail.get("summary"), str):
                        visible_content.append({"type": "reasoning", "summary": detail["summary"]})
            if visible_content:
                message = {
                    **message,
                    "content": visible_content + OpenRouterChatOpenAI._content_blocks(message=message),
                }
                choice = {**choice, message_key: message}
            projected.append(choice)
        return {**payload, "choices": projected}

    @staticmethod
    def _content_blocks(*, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize ordinary visible assistant content after prepended reasoning blocks.

        Args:
            message (dict[str, Any]): Gateway assistant message or delta.

        Returns:
            list[dict[str, Any]]: Existing visible content expressed as standard text blocks.
        """
        content: object | None = message.get("content")
        if isinstance(content, str) and content:
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return [block for block in content if isinstance(block, dict)]
        return []

    @staticmethod
    def _project_refusal(*, payload: dict[str, Any], message_key: str) -> dict[str, Any]:
        """Copy visible refusal text into standard content before SDK conversion.

        Args:
            payload: Validated successful response or stream frame.
            message_key: The transport's message or delta field.

        Returns:
            dict[str, Any]: Detached response preserving normal content and metadata.
        """
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return payload
        projected = []
        for choice in choices:
            message = choice.get(message_key) if isinstance(choice, dict) else None
            if isinstance(message, dict) and isinstance(message.get("refusal"), str):
                choice = {
                    **choice,
                    message_key: {**message, "content": (message.get("content") or "") + message["refusal"]},
                }
            projected.append(choice)
        return {**payload, "choices": projected}

    @staticmethod
    def _mark_length_completion(*, result: ChatResult, payload: object) -> None:
        """Give a reasoning-only length completion its visible terminal text.

        Args:
            result (ChatResult): Converted result to update when no answer text exists.
            payload (object): Original gateway response carrying the finish reason.
        """
        if not isinstance(payload, dict) or not result.generations:
            return
        choices: object | None = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return
        if choices[0].get("finish_reason") != "length":
            return
        message: BaseMessage = result.generations[0].message
        OpenRouterChatOpenAI._append_output_limit_notice(message=message)

    @staticmethod
    def _append_output_limit_notice(*, message: BaseMessage) -> None:
        """Append successful truncation text without replacing visible reasoning or answers.

        Called at the terminal length frame/result only; it neither raises a
        retryable error nor owns any retry mechanism.

        Args:
            message: Converted terminal message whose content is preserved.
        """
        notice = "Output limit reached"
        if isinstance(message.content, str):
            message.content += ("\n\n" if message.content else "") + notice
            return
        prefix = "\n\n" if message.text() else ""
        message.content = [*message.content, {"type": "text", "text": prefix + notice}]

    def _attach_result_extension(self, *, result: ChatResult, response: object) -> None:
        """Copy recognized gateway reasoning fields onto the first assistant message.

        Args:
            result (ChatResult): LangChain-converted response result.
            response (object): Original gateway response before conversion.
        """
        payload: object = (
            response if isinstance(response, dict) else self._model_dump_response(response=response)
        )
        if not isinstance(payload, dict):
            return
        choices: object | None = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        first_choice: object = choices[0]
        if not isinstance(first_choice, dict):
            return
        message: object | None = first_choice.get("message")
        if not isinstance(message, dict):
            return
        extension: Optional[ProviderMessageExtensionDAO] = self._extension_from_gateway_message(
            message=message
        )
        if extension is None or not result.generations:
            return
        generated_message: BaseMessage = result.generations[0].message
        if not isinstance(generated_message, AIMessage):
            return
        generated_message.additional_kwargs[PROVIDER_MESSAGE_EXTENSION_KEY] = extension.model_dump(
            mode="json"
        )

    @staticmethod
    def _model_dump_response(*, response: object) -> object:
        """Convert an SDK response model to a mapping when it exposes the expected seam.

        Args:
            response (object): Provider SDK response object.

        Returns:
            object: Mapping-compatible model dump or the original opaque object.
        """
        model_dump: object | None = getattr(response, "model_dump", None)
        if not callable(model_dump):
            return response
        return model_dump()

    def _extension_from_gateway_message(
        self, *, message: dict[str, Any]
    ) -> Optional[ProviderMessageExtensionDAO]:
        """Build private replay metadata from one inbound Chat Completions assistant message.

        Args:
            message (dict[str, Any]): Gateway assistant message mapping.

        Returns:
            Optional[ProviderMessageExtensionDAO]: Same-route metadata when present.
        """
        details: object | None = message.get("reasoning_details")
        reasoning: object | None = message.get("reasoning", message.get("reasoning_content"))
        if details is None and reasoning is None:
            return None
        if details is not None and not isinstance(details, list):
            raise OpenRouterAPIError(error_type="invalid_request")
        if reasoning is not None and not isinstance(reasoning, str):
            raise OpenRouterAPIError(error_type="invalid_request")
        try:
            extension = ProviderMessageExtensionDAO(
                provider=ProviderName.OPENROUTER,
                source_model_name=self.slo_model_name,
                reasoning=reasoning,
                reasoning_details=details or [],
            )
        except ValueError:
            raise OpenRouterAPIError(error_type="invalid_request") from None
        OpenRouterMessageCodec.validate(extension=extension)
        return extension


class OpenRouterErrorNormalizer:
    """Convert OpenRouter SDK and gateway error shapes to safe shared exceptions."""

    @classmethod
    def normalize(cls, *, error: BaseException) -> OpenRouterAPIError:
        """Return a safe exception retaining only allowlisted error facts.

        Called at each adapter transport boundary before an SDK exception can
        reach ModelPool, history, or terminal rendering.

        Args:
            error (BaseException): Raw SDK or transport exception.

        Returns:
            OpenRouterAPIError: Sanitized OpenRouter exception.
        """
        if isinstance(error, OpenRouterAPIError):
            return error
        status_code: Optional[int] = cls._status_code_from_error(error=error)
        payload: object = getattr(error, "body", None)
        normalized = cls._from_payload(payload=payload, status_code=status_code)
        if status_code is None and normalized.error_type is None:
            import openai
            import httpx
            from src.agents.providers.stream_recovery.service import StreamRecoveryService

            if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException)):
                normalized.error_type = "timeout"
            elif isinstance(
                error, openai.APIConnectionError
            ) or StreamRecoveryService.is_stream_disconnection(exc=error):
                normalized.error_type = "provider_unavailable"
        from src.agents.providers.credit_exhaustion_policy import _extract_headers, _positive_retry_after

        advice = _positive_retry_after(headers=_extract_headers(error=error))
        if advice is not None:
            normalized.retry_after_seconds = advice
        return normalized

    @classmethod
    def raise_for_payload(cls, *, payload: dict[str, Any]) -> None:
        """Raise a safe exception when a successful HTTP payload carries an error.

        Called before LangChain result/chunk conversion so a top-level error,
        nested choice error, or error finish reason cannot become success.

        Args:
            payload (dict[str, Any]): Parsed Chat Completions response or SSE frame.
        """
        error_payload: object | None = cls._error_payload(payload=payload)
        if error_payload is None:
            return
        raise cls._from_payload(payload=error_payload, status_code=None)

    @classmethod
    def _error_payload(cls, *, payload: dict[str, Any]) -> object | None:
        """Return one recognized gateway error shape from a parsed payload."""
        top_level_error: object | None = payload.get("error")
        if top_level_error is not None:
            return top_level_error
        choices: object | None = payload.get("choices")
        if not isinstance(choices, list):
            return None
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            nested_error: object | None = choice.get("error")
            if nested_error is not None:
                return nested_error
            if choice.get("finish_reason") == "error":
                return nested_error if nested_error is not None else {"type": "invalid_request"}
        return None

    @classmethod
    def _from_payload(cls, *, payload: object, status_code: Optional[int]) -> OpenRouterAPIError:
        """Build a safe exception from an opaque SDK body without retaining it."""
        error_type: Optional[str] = None
        limit_source: Optional[str] = None
        retry_after_seconds: Optional[int] = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            payload = payload["error"]
        if isinstance(payload, dict):
            code = payload.get("code")
            if status_code is None and type(code) is int and 400 <= code <= 599:
                status_code = code
            candidate_type: object | None = payload.get("type")
            error_type = candidate_type if isinstance(candidate_type, str) else None
            metadata = payload.get("metadata")
            safe_metadata = metadata if isinstance(metadata, dict) else {}
            candidate_limit_source: object | None = payload.get(
                "limit_source", safe_metadata.get("limit_source")
            )
            limit_source = candidate_limit_source if isinstance(candidate_limit_source, str) else None
            candidate_retry_after: object | None = payload.get("retry_after_seconds")
            if isinstance(candidate_retry_after, int) and not isinstance(candidate_retry_after, bool):
                retry_after_seconds = candidate_retry_after
        return OpenRouterAPIError(
            status_code=status_code,
            error_type=error_type,
            limit_source=limit_source,
            retry_after_seconds=retry_after_seconds,
        )

    @staticmethod
    def _status_code_from_error(*, error: BaseException) -> Optional[int]:
        """Extract an integer HTTP status only from the SDK's public seam."""
        candidate_status: object | None = getattr(error, "status_code", None)
        if isinstance(candidate_status, int) and not isinstance(candidate_status, bool):
            return candidate_status
        return None
