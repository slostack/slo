"""LLM factory (01.b, extended by 01.n; rewired in 02.b.2).

This module is the single point of LLM construction in slo. Every agent
goes through ``LLMFactory.create(model_name=..., ...)``; tests bypass it
by injecting a ``FauxChatModel`` directly.

02.b.2 factors credential lookup out of this file. The factory now
delegates to ``src.auth.credential_resolver.CredentialResolver.require``
for both providers; that resolver owns the env > store > legacy-Claude
precedence chain. ``LLMFactory`` retains the model-name → provider-class
dispatch and the ``MODEL_DEFAULTS`` fallback chain.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeAlias, runtime_checkable

import httpx

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

if TYPE_CHECKING:
    from src.agents.providers.model_pool import ModelPool, ModelPoolDAO

from config.ai_model_config import MODEL_DEFAULTS, defaults_for_model
from src.agents.model_catalog.dao import ModelCatalogEntryDAO, ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.providers.anthropic_claude_code import (
    _ThinkingPatchedChatAnthropic,
    anthropic_thinking_payload,
    build_claude_code_backed_chat_anthropic,
)
from src.agents.providers.openai_codex import (
    build_chatgpt_backed_chat_openai,
    openai_reasoning_payload,
)
from src.agents.providers.openrouter import OpenRouterChatOpenAI, OpenRouterRequestPolicy
from src.agents.reasoning_capabilities import (
    ModelReasoningCapabilityDAO,
    ReasoningLevel,
    ResolvedReasoningConfigDAO,
    capability_for_model,
    resolve_reasoning_config,
)
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import (
    ANTHROPIC_PREFIXES,
    KIMI_FOR_CODING_PREFIXES,
    OPENAI_PREFIXES,
    provider_for_model,
)

__all__ = [
    "ANTHROPIC_PREFIXES",
    "KIMI_FOR_CODING_PREFIXES",
    "LLM",
    "LLMBuildProduct",
    "LLMBuildResult",
    "LLMFactory",
    "OPENAI_PREFIXES",
]


LLM: TypeAlias = BaseChatModel
"""All chat models the harness supports.

We type this as the LangChain base so test code can pass the FauxChatModel
through the same parameter slots without a structural type bend.
"""


@runtime_checkable
class LLMBuildProduct(Protocol):
    """Structural contract shared by single-model and pooled build results.

    ``build_slo_agent`` consumes ``.llm`` and ``.supports_explicit_caching`` from
    whichever product the factory returns, so it branches only at construction.
    ``LLMBuildResult`` (single model) and ``ModelPool`` (pool) both satisfy it.
    """

    @property
    def llm(self) -> BaseChatModel:
        """Return the constructed chat model (single model or pool)."""
        ...

    @property
    def supports_explicit_caching(self) -> bool:
        """Return whether the provider needs explicit ``cache_control`` markers."""
        ...


@dataclasses.dataclass(frozen=True)
class LLMBuildResult:
    """Wraps a constructed LLM with provider-capability metadata.

    Decouples ``LLMFactory`` from the agent so ``SloAgent`` can make
    provider-aware decisions (e.g., annotating ``SystemMessage`` with
    ``cache_control`` for Anthropic) without importing provider-specific code.

    Attributes:
        llm (LLM): The constructed chat model instance.
        supports_explicit_caching (bool): ``True`` when the provider requires
            explicit ``cache_control`` markers (Anthropic). ``False`` for
            OpenAI/others whose caching is either automatic or unsupported.
    """

    llm: LLM
    supports_explicit_caching: bool


# Compatibility re-exports. Route ownership lives in ``provider_for_model``.

KIMI_FOR_CODING_API_URL: str = "https://api.kimi.com/coding/v1"
"""Base URL for the Kimi For Coding REST API (OpenAI-compatible)."""

KIMI_FOR_CODING_USER_AGENT: str = "KimiCLI/1.5"
"""User-Agent sent on every Kimi For Coding request.

Kimi's ToS requires callers to maintain their real tool identity via
User-Agent and prohibits tampering with this value.
"""


class LLMFactory:
    """Factory for LangChain chat models, selected by ``model_name`` prefix."""

    _ANTHROPIC_PREFIXES: tuple[str, ...] = ANTHROPIC_PREFIXES
    _OPENAI_PREFIXES: tuple[str, ...] = OPENAI_PREFIXES
    _KIMI_FOR_CODING_PREFIXES: tuple[str, ...] = KIMI_FOR_CODING_PREFIXES

    @classmethod
    def create(
        cls,
        *,
        model_name: str,
        temperature: Optional[float] = None,
        streaming: Optional[bool] = None,
        max_retries: int = 3,
        max_tokens: Optional[int] = None,
        model_kwargs: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
        reasoning_level: ReasoningLevel = "off",
        http_async_client: Optional[httpx.AsyncClient] = None,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> LLMBuildResult:
        """Create a LangChain chat model from a model name.

        Dispatches by ``model_name`` prefix; delegates credential resolution
        to ``CredentialResolver.require``. See ``CredentialResolver`` for
        the precedence order.

        Args:
            model_name (str): Identifier; selects the provider class.
            temperature (Optional[float]): Falls back to MODEL_DEFAULTS then 0.1.
            streaming (Optional[bool]): Falls back to MODEL_DEFAULTS then True.
            max_retries (int): SDK-level retries. Defaults to 3.
            max_tokens (Optional[int]): Falls back to MODEL_DEFAULTS then 4096.
            model_kwargs (Optional[dict[str, Any]]): Provider extras
                forwarded verbatim.
            session_id (Optional[str]): Active ``SloAgentSession.session_id``.
                Threaded through to the ChatGPT-backend headers when the
                resolved OpenAI credential is OAuth (feature 07). Ignored
                otherwise.
            reasoning_level (ReasoningLevel): Canonical active reasoning
                level forwarded into provider-native payload translation.
            http_async_client (Optional[httpx.AsyncClient]): Optional OpenAI
                async HTTP client. Test callers inject a local transport here;
                ``None`` preserves the SDK-created production client.

        Returns:
            LLMBuildResult: A configured LangChain chat model wrapped with
                provider-capability metadata.

        Raises:
            ValueError: When ``model_name`` matches no supported prefix, or
                when ``CredentialResolver.require`` cannot resolve a credential.
        """
        provider: ProviderName = (
            ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot).provider
            if snapshot is not None
            else cls._provider_for(model_name=model_name)
        )
        if provider is ProviderName.OPENROUTER:
            return cls._create_openrouter(
                model_name=model_name,
                temperature=temperature,
                streaming=streaming,
                max_retries=max_retries,
                max_tokens=max_tokens,
                model_kwargs=model_kwargs,
                session_id=session_id,
                reasoning_level=reasoning_level,
                http_async_client=http_async_client,
                snapshot=snapshot,
            )
        resolved: dict[str, Any] = cls._resolved_defaults(
            model_name=model_name,
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
            session_id=session_id,
            reasoning_level=reasoning_level,
            http_async_client=http_async_client,
            snapshot=snapshot,
        )
        provider = (
            ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot).provider
            if snapshot is not None
            else cls._provider_for(model_name=model_name)
        )
        if provider is ProviderName.ANTHROPIC:
            llm: LLM = cls._build_anthropic(model_name=model_name, resolved=resolved)
            return LLMBuildResult(llm=llm, supports_explicit_caching=True)
        if provider is ProviderName.OPENAI:
            llm = cls._build_openai(model_name=model_name, resolved=resolved)
            return LLMBuildResult(llm=llm, supports_explicit_caching=False)
        if provider is ProviderName.KIMI_FOR_CODING:
            llm = cls._build_kimi_for_coding_chat_openai(model_name=model_name, resolved=resolved)
            return LLMBuildResult(llm=llm, supports_explicit_caching=False)
        raise ValueError(f"Provider '{provider.value}' has no configured LLM builder.")

    @classmethod
    def _create_openrouter(
        cls,
        *,
        model_name: str,
        temperature: Optional[float],
        streaming: Optional[bool],
        max_retries: int,
        max_tokens: Optional[int],
        model_kwargs: Optional[dict[str, Any]],
        session_id: Optional[str],
        reasoning_level: ReasoningLevel,
        http_async_client: Optional[httpx.AsyncClient],
        snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> LLMBuildResult:
        """Build one OpenRouter adapter from an exact prepared catalog route.

        Called by :meth:`create` before generic default resolution because an
        unknown dynamic route must fail as missing preparation, rather than
        attempting global/default direct-provider policy.

        Args:
            model_name (str): Exact canonical OpenRouter route.
            temperature (Optional[float]): Caller sampling override.
            streaming (Optional[bool]): Caller streaming override.
            max_retries (int): SDK retry input; OpenRouter overrides it to zero.
            max_tokens (Optional[int]): Caller output-cap override.
            model_kwargs (Optional[dict[str, Any]]): Caller extras.
            session_id (Optional[str]): Session identity, unused by this adapter.
            reasoning_level (ReasoningLevel): Canonical requested reasoning level.
            http_async_client (Optional[httpx.AsyncClient]): Injected local test transport.
            snapshot (Optional[ModelCatalogSnapshotDAO]): Required prepared route view.

        Returns:
            LLMBuildResult: OpenRouter adapter with explicit caching disabled.
        """
        entry = cls._prepared_openrouter_entry(model_name=model_name, snapshot=snapshot)
        resolved: dict[str, Any] = cls._resolved_defaults_from_entry(
            entry=entry,
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
            session_id=session_id,
            reasoning_level=reasoning_level,
            http_async_client=http_async_client,
            snapshot=snapshot,
        )
        llm = cls._build_openrouter(model_name=model_name, resolved=resolved, entry=entry)
        return LLMBuildResult(llm=llm, supports_explicit_caching=False)

    @classmethod
    def _resolved_defaults_from_entry(
        cls,
        *,
        entry: "ModelCatalogEntryDAO",
        temperature: Optional[float],
        streaming: Optional[bool],
        max_retries: int,
        max_tokens: Optional[int],
        model_kwargs: Optional[dict[str, Any]],
        session_id: Optional[str],
        reasoning_level: ReasoningLevel,
        http_async_client: Optional[httpx.AsyncClient],
        snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> dict[str, Any]:
        """Resolve OpenRouter construction defaults from one prepared entry.

        Args:
            entry (ModelCatalogEntryDAO): Exact prepared route profile.
            temperature (Optional[float]): Caller sampling override.
            streaming (Optional[bool]): Caller streaming override.
            max_retries (int): Caller retry setting retained for diagnostic parity.
            max_tokens (Optional[int]): Caller output-cap override.
            model_kwargs (Optional[dict[str, Any]]): Caller extras.
            session_id (Optional[str): Active session identifier.
            reasoning_level (ReasoningLevel): Requested canonical reasoning level.
            http_async_client (Optional[httpx.AsyncClient]): Injected local test transport.
            snapshot (Optional[ModelCatalogSnapshotDAO]): Exact catalog generation.

        Returns:
            dict[str, Any]: Builder inputs resolved without a global catalog read.
        """
        profile = entry.runtime_profile
        output_ceiling: int = cls._openrouter_output_ceiling(entry=entry)
        return {
            "temperature": temperature if temperature is not None else None,
            "streaming": streaming if streaming is not None else profile.streaming,
            "max_retries": max_retries,
            "max_tokens": max_tokens if max_tokens is not None else min(profile.max_tokens, output_ceiling),
            "model_kwargs": model_kwargs or {},
            "session_id": session_id,
            "reasoning_level": reasoning_level,
            "http_async_client": http_async_client,
            "snapshot": snapshot,
        }

    @classmethod
    def _resolved_defaults(
        cls,
        *,
        model_name: str,
        temperature: Optional[float],
        streaming: Optional[bool],
        max_retries: int,
        max_tokens: Optional[int],
        model_kwargs: Optional[dict[str, Any]],
        session_id: Optional[str] = None,
        reasoning_level: ReasoningLevel = "off",
        http_async_client: Optional[httpx.AsyncClient] = None,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> dict[str, Any]:
        """Resolve constructor kwargs by layering callers over MODEL_DEFAULTS.

        Args:
            model_name (str): Used to look up MODEL_DEFAULTS.
            temperature (Optional[float]): Caller override; None defers to defaults.
            streaming (Optional[bool]): Caller override; None defers to defaults.
            max_retries (int): SDK-level retries; passed through unchanged.
            max_tokens (Optional[int]): Caller override; None defers to defaults.
            model_kwargs (Optional[dict[str, Any]]): Caller extras;
                ``None`` becomes ``{}``.
            session_id (Optional[str]): Threaded through for OAuth-mode
                OpenAI builds.
            reasoning_level (ReasoningLevel): Canonical active reasoning
                level forwarded into provider translation.
            http_async_client (Optional[httpx.AsyncClient]): Optional OpenAI
                async HTTP client forwarded without creating one.

        Returns:
            dict[str, Any]: Keys ``temperature``, ``streaming``, ``max_retries``,
                ``max_tokens``, ``model_kwargs``, ``session_id``, ``reasoning_level``.
        """
        defaults = (
            defaults_for_model(model_name=model_name, snapshot=snapshot)
            if snapshot is not None
            else MODEL_DEFAULTS.get(model_name, {})
        )
        return {
            "temperature": (temperature if temperature is not None else defaults.get("temperature", 0.1)),
            "streaming": (streaming if streaming is not None else defaults.get("streaming", True)),
            "max_retries": max_retries,
            "max_tokens": (max_tokens if max_tokens is not None else defaults.get("max_tokens", 4096)),
            "model_kwargs": model_kwargs or {},
            "session_id": session_id,
            "reasoning_level": reasoning_level,
            "http_async_client": http_async_client,
            "snapshot": snapshot,
        }

    @classmethod
    def _anthropic_max_tokens(
        cls,
        *,
        base_max_tokens: int,
        resolved_reasoning: ResolvedReasoningConfigDAO,
    ) -> int:
        """Return the Anthropic ``max_tokens`` request value for one resolved config.

        ``max_tokens`` is the Anthropic API's hard ceiling on *total* output
        tokens. For adaptive thinking the thinking tokens are counted within it;
        for explicit-budget models ``budget_tokens`` must be strictly less than
        it. We therefore treat ``base_max_tokens`` as the total cap and never add
        the thinking budget on top of it — doing so would push the request past
        the model ceiling and return a 400. This corrects the earlier
        ``base + budget`` behavior (and the stale ``KB/slo/agent-core.md`` note
        about "expanding ``max_tokens`` by the thinking budget").

        For the current adaptive models (``provider_budget_tokens is None``) the
        returned value is exactly the ceiling. Any explicit budget lives inside
        the ceiling via the thinking payload, so the request value is still the
        ceiling and never exceeds it.

        Args:
            base_max_tokens (int): The model's resolved total output ceiling
                (from ``MODEL_DEFAULTS`` or a caller override).
            resolved_reasoning (ResolvedReasoningConfigDAO): Final resolved
                reasoning config for this request.

        Returns:
            int: The ``max_tokens`` value to send to Anthropic — always
                ``<= base_max_tokens``.
        """
        return base_max_tokens

    @classmethod
    def _build_anthropic(
        cls,
        *,
        model_name: str,
        resolved: dict[str, Any],
    ) -> ChatAnthropic:
        """Build a ChatAnthropic for ``model_name`` using the resolver.

        The canonical ``model_name`` keys ``MODEL_DEFAULTS``, reasoning
        resolution, session kwargs, and logging. The provider call itself
        receives the API model name resolved through
        ``ModelCatalogService.api_model_name_for`` (identity when the entry
        carries no override). Both lanes — API-key and Claude Code OAuth —
        share the same resolution.

        Args:
            model_name (str): Canonical Anthropic model identifier.
            resolved (dict[str, Any]): Output of :meth:`_resolved_defaults`.

        Returns:
            ChatAnthropic: Configured chat model with the resolver's credential.
        """
        cred: CredentialDAO = CredentialResolver.require(provider=ProviderName.ANTHROPIC)
        api_model_name: str = ModelCatalogService.api_model_name_for(
            model_name=model_name,
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        resolved_reasoning: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name=model_name,
            requested_level=resolved["reasoning_level"],
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        thinking: Optional[dict[str, Any]] = anthropic_thinking_payload(
            reasoning=resolved_reasoning,
        )
        max_tokens: int = cls._anthropic_max_tokens(
            base_max_tokens=resolved["max_tokens"],
            resolved_reasoning=resolved_reasoning,
        )
        if cred.auth_type == AuthType.OAUTH:
            return build_claude_code_backed_chat_anthropic(
                model_name=api_model_name,
                cred=cred,
                temperature=resolved["temperature"],
                reasoning=resolved_reasoning,
                streaming=resolved["streaming"],
                max_retries=resolved["max_retries"],
                max_tokens=max_tokens,
                model_kwargs=resolved["model_kwargs"],
            )
        merged_model_kwargs: dict[str, Any] = dict(resolved["model_kwargs"])
        if thinking is not None and resolved_reasoning.provider_effort is not None:
            merged_model_kwargs["output_config"] = {"effort": resolved_reasoning.provider_effort}
        anthropic_kwargs: dict[str, Any] = {
            "model": api_model_name,
            "streaming": resolved["streaming"],
            "max_retries": resolved["max_retries"],
            "max_tokens": max_tokens,
            "anthropic_api_key": cred.access_token,
            "model_kwargs": merged_model_kwargs,
        }
        if thinking is not None:
            anthropic_kwargs["thinking"] = thinking
        elif resolved["temperature"] is not None:
            anthropic_kwargs["temperature"] = resolved["temperature"]
        return _ThinkingPatchedChatAnthropic(**anthropic_kwargs)

    @classmethod
    def _build_openai(
        cls,
        *,
        model_name: str,
        resolved: dict[str, Any],
    ) -> ChatOpenAI:
        """Build a ChatOpenAI for ``model_name`` using the resolver.

        Two lanes (feature 07):

        - ``auth_type == OAUTH`` → route through the ChatGPT backend
          (``chatgpt.com/backend-api/codex/responses``) with the
          identity headers the ChatGPT subscription quota requires.
        - ``auth_type == API_KEY`` → stock ``ChatOpenAI`` against the
          Platform API (unchanged behaviour).

        OAuth credential refresh happens at the async session seam
        (``SloAgentSession._ensure_agent_ready``) immediately before the
        lazy build. Keeping refresh out of this synchronous factory
        avoids illegal ``asyncio.run()`` calls inside the running TUI
        event loop while preserving the same user-facing behaviour.

        Args:
            model_name (str): OpenAI model identifier.
            resolved (dict[str, Any]): Output of :meth:`_resolved_defaults`.

        Returns:
            ChatOpenAI: Configured chat model on the appropriate lane.
        """
        cred: CredentialDAO = CredentialResolver.require(provider=ProviderName.OPENAI)
        api_model_name: str = ModelCatalogService.api_model_name_for(
            model_name=model_name,
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        resolved_reasoning: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name=model_name,
            requested_level=resolved["reasoning_level"],
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        sanitized_temperature, sanitized_model_kwargs = cls._resolve_openai_request_policy(
            model_name=model_name,
            resolved_reasoning=resolved_reasoning,
            temperature=resolved["temperature"],
            model_kwargs=resolved["model_kwargs"],
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        if cred.auth_type == AuthType.OAUTH:
            return build_chatgpt_backed_chat_openai(
                model_name=api_model_name,
                cred=cred,
                session_id=resolved["session_id"] or model_name,
                temperature=sanitized_temperature,
                reasoning=resolved_reasoning,
                model_kwargs=sanitized_model_kwargs,
                streaming=resolved["streaming"],
                http_async_client=resolved["http_async_client"],
            )
        openai_kwargs: dict[str, Any] = {
            "model": api_model_name,
            "streaming": resolved["streaming"],
            "max_retries": resolved["max_retries"],
            "max_tokens": resolved["max_tokens"],
            "api_key": cred.access_token,
            "model_kwargs": sanitized_model_kwargs,
            "http_async_client": resolved["http_async_client"],
        }
        openai_reasoning: Optional[dict[str, str]] = openai_reasoning_payload(
            reasoning=resolved_reasoning,
        )
        if openai_reasoning is not None:
            openai_kwargs["reasoning"] = openai_reasoning
            openai_kwargs["use_responses_api"] = True
            openai_kwargs["output_version"] = "responses/v1"
        elif sanitized_temperature is not None:
            openai_kwargs["temperature"] = sanitized_temperature
        return ChatOpenAI(**openai_kwargs)

    @classmethod
    def _resolve_openai_request_policy(
        cls,
        *,
        model_name: str,
        resolved_reasoning: ResolvedReasoningConfigDAO,
        temperature: Optional[float],
        model_kwargs: dict[str, Any],
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> tuple[Optional[float], dict[str, Any]]:
        """Return copied OpenAI constructor inputs permitted by the catalog profile.

        Called by ``_build_openai`` after canonical reasoning resolution and
        before OAuth/API-key construction. It consults the generic capability
        projection, never a model-name conditional, and removes only the
        sampling values forbidden for enabled reasoning (``temperature``,
        ``top_p``, ``top_logprobs``, ``logprobs``). Caller mappings are never
        mutated.

        Args:
            model_name (str): Canonical model name used for capability lookup.
            resolved_reasoning (ResolvedReasoningConfigDAO): Resolved reasoning
                config for the active model.
            temperature (Optional[float]): Resolved caller temperature.
            model_kwargs (dict[str, Any]): Resolved caller extra kwargs.

        Returns:
            tuple[Optional[float], dict[str, Any]]: Sanitized temperature and a
                newly copied extras mapping.
        """
        sanitized_model_kwargs: dict[str, Any] = dict(model_kwargs)
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name=model_name, snapshot=snapshot
        )
        if not (resolved_reasoning.enabled and capability.forbid_sampling_parameters_when_enabled):
            return temperature, sanitized_model_kwargs
        for forbidden_key in ("temperature", "top_p", "top_logprobs", "logprobs"):
            sanitized_model_kwargs.pop(forbidden_key, None)
        return None, sanitized_model_kwargs

    @classmethod
    def _build_openrouter(
        cls,
        *,
        model_name: str,
        resolved: dict[str, Any],
        entry: "ModelCatalogEntryDAO",
    ) -> OpenRouterChatOpenAI:
        """Build the fixed OpenRouter Chat Completions adapter for one exact route.

        Called by :meth:`create` after canonical provider dispatch. The route
        prefix remains Slo-only; the outbound model is its exact remote suffix.
        This bounded construction path intentionally avoids catalog lifecycle
        decisions until the a.2 prepared-snapshot integration is available.

        Args:
            model_name (str): Canonical ``openrouter:<remote-id>`` route.
            resolved (dict[str, Any]): Factory defaults and injected local test transport.

        Returns:
            OpenRouterChatOpenAI: No-SDK-retry gateway Chat Completions adapter.
        """
        OpenRouterRequestPolicy.validate_output_cap(
            max_tokens=resolved["max_tokens"],
            ceiling=cls._openrouter_output_ceiling(entry=entry),
        )
        capabilities = entry.capabilities
        if capabilities is None:
            raise ValueError("OpenRouter prepared catalog entry has no capability evidence.")
        sampling = dict(resolved["model_kwargs"])
        if resolved["temperature"] is not None:
            sampling["temperature"] = resolved["temperature"]
        OpenRouterRequestPolicy.validate_controls(
            options=sampling, supported=capabilities.supported_parameters
        )
        credential: CredentialDAO = CredentialResolver.require(provider=ProviderName.OPENROUTER)
        resolved_reasoning: ResolvedReasoningConfigDAO = resolve_reasoning_config(
            model_name=model_name,
            requested_level=resolved["reasoning_level"],
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        capabilities = entry.capabilities
        if capabilities is None:
            raise ValueError("OpenRouter prepared catalog entry has no capability evidence.")
        request_policy: dict[str, object] = OpenRouterRequestPolicy.build(
            max_tokens=resolved["max_tokens"],
            reasoning_effort=resolved_reasoning.provider_effort if resolved_reasoning.enabled else None,
            controls_available=(
                capabilities.reasoning_controls_available or capabilities.reasoning_disable_available
            ),
            disable_available=capabilities.reasoning_disable_available,
        )
        return OpenRouterChatOpenAI(
            slo_model_name=model_name,
            slo_capabilities=capabilities,
            slo_output_ceiling=cls._openrouter_output_ceiling(entry=entry),
            model=entry.api_model_name or entry.model_name.removeprefix("openrouter:"),
            base_url="https://openrouter.ai/api/v1",
            api_key=credential.access_token,
            streaming=resolved["streaming"],
            max_retries=0,
            use_responses_api=False,
            stream_usage=True,
            **sampling,
            default_headers={
                "X-OpenRouter-Title": "Slo",
                "X-OpenRouter-Categories": "cli-agent",
            },
            http_async_client=resolved["http_async_client"],
            **request_policy,
        )

    @staticmethod
    def _openrouter_output_ceiling(*, entry: "ModelCatalogEntryDAO") -> int:
        """Return the immutable OpenRouter ceiling for construction and invocation.

        Args:
            entry (ModelCatalogEntryDAO): Prepared OpenRouter catalog record.

        Returns:
            int: The lesser reported-or-local output bound and half the effective context window.
        """
        capabilities = entry.capabilities
        reported_or_local: int = (
            capabilities.reported_output_ceiling
            if capabilities is not None and capabilities.reported_output_ceiling is not None
            else 4096
        )
        return min(reported_or_local, entry.runtime_profile.context_window // 2)

    @classmethod
    def _prepared_openrouter_entry(
        cls,
        *,
        model_name: str,
        snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> "ModelCatalogEntryDAO":
        """Require the supplied immutable catalog snapshot for an OpenRouter build.

        Called only by :meth:`_build_openrouter` after structural provider dispatch.
        OpenRouter routes are dynamically discovered, so the factory must reject a
        missing snapshot or an absent/ineligible entry before resolving credentials
        or constructing a direct-family fallback.

        Args:
            model_name (str): Exact canonical OpenRouter route.
            snapshot (Optional[ModelCatalogSnapshotDAO]): Immutable prepared catalog view.

        Returns:
            ModelCatalogEntryDAO: The prepared exact-route entry.

        Raises:
            ValueError: The route lacks a prepared eligible OpenRouter catalog entry.
        """
        if snapshot is None:
            raise ValueError("OpenRouter model construction requires a prepared catalog entry and snapshot.")
        entry: ModelCatalogEntryDAO = ModelCatalogService.entry_for_model(
            model_name=model_name,
            snapshot=snapshot,
        )
        if entry.provider is not ProviderName.OPENROUTER or entry.availability != "available":
            raise ValueError("OpenRouter model construction requires an eligible prepared catalog entry.")
        return entry

    @classmethod
    def _build_kimi_for_coding_chat_openai(
        cls,
        *,
        model_name: str,
        resolved: dict[str, Any],
    ) -> ChatOpenAI:
        """Build a Kimi chat-completions model with optional K3 provider effort.

        ``LLMFactory.create`` invokes this builder after the session selects a
        canonical reasoning level. Enabled K3 resolved reasoning supplies a
        top-level provider effort; disabled K2 resolved reasoning leaves the
        legacy request shape unchanged. This builder never emits Kimi
        ``thinking`` or OpenAI Responses-API fields.

        Args:
            model_name (str): Kimi catalog model identifier.
            resolved (dict[str, Any]): Factory defaults including the requested reasoning level.

        Returns:
            ChatOpenAI: Kimi chat-completions model with the permitted K3 request field.
        """
        cred: CredentialDAO = CredentialResolver.require(provider=ProviderName.KIMI_FOR_CODING)
        resolved_reasoning: ResolvedReasoningConfigDAO = cls._resolve_kimi_reasoning_config(
            model_name=model_name,
            requested_level=resolved["reasoning_level"],
            **({"snapshot": resolved["snapshot"]} if resolved.get("snapshot") is not None else {}),
        )
        kimi_kwargs: dict[str, Any] = {
            "base_url": KIMI_FOR_CODING_API_URL,
            "api_key": cred.access_token,
            "model": model_name,
            "temperature": resolved["temperature"],
            "max_tokens": resolved["max_tokens"],
            "streaming": resolved["streaming"],
            "max_retries": 0,
            "model_kwargs": resolved["model_kwargs"],
            "default_headers": {"User-Agent": KIMI_FOR_CODING_USER_AGENT},
        }
        cls._add_kimi_provider_effort(
            kimi_kwargs=kimi_kwargs,
            resolved_reasoning=resolved_reasoning,
        )
        return ChatOpenAI(**kimi_kwargs)  # type: ignore[call-arg]

    @staticmethod
    def _resolve_kimi_reasoning_config(
        *,
        model_name: str,
        requested_level: ReasoningLevel,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> ResolvedReasoningConfigDAO:
        """Resolve catalog reasoning only for known Kimi models.

        Prefix-dispatched legacy or discovered Kimi identifiers can lack a
        catalog profile. Those identifiers retain the legacy disabled request
        shape rather than failing provider dispatch.

        Args:
            model_name (str): Kimi model identifier.
            requested_level (ReasoningLevel): Requested canonical reasoning level.

        Returns:
            ResolvedReasoningConfigDAO: Catalog result or a disabled legacy result.
        """
        try:
            return resolve_reasoning_config(
                model_name=model_name,
                requested_level=requested_level,
                snapshot=snapshot,
            )
        except ValueError:
            try:
                entry = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
            except ValueError:
                return ResolvedReasoningConfigDAO(
                    enabled=False,
                    requested_level=requested_level,
                    active_level="off",
                )
            if entry.provider is ProviderName.KIMI_FOR_CODING:
                raise
            return ResolvedReasoningConfigDAO(
                enabled=False,
                requested_level=requested_level,
                active_level="off",
            )

    @staticmethod
    def _add_kimi_provider_effort(
        *,
        kimi_kwargs: dict[str, Any],
        resolved_reasoning: ResolvedReasoningConfigDAO,
    ) -> None:
        """Add the permitted K3 effort field when resolved reasoning enables it.

        The Kimi builder calls this after creating the base chat-completions
        request. Disabled K2 reasoning preserves the legacy request; enabled
        K3 reasoning writes only top-level ``reasoning_effort``.

        Args:
            kimi_kwargs (dict[str, Any]): Mutable ChatOpenAI constructor kwargs.
            resolved_reasoning (ResolvedReasoningConfigDAO): Catalog-derived final reasoning selection.

        Raises:
            ValueError: If enabled resolved reasoning has no provider effort.
        """
        if not resolved_reasoning.enabled:
            return
        if resolved_reasoning.provider_effort is None:
            raise ValueError("Enabled Kimi resolved reasoning requires a provider effort.")
        kimi_kwargs["reasoning_effort"] = resolved_reasoning.provider_effort

    @classmethod
    def _provider_for(cls, *, model_name: str) -> ProviderName:
        """Return the ``ProviderName`` that owns ``model_name``.

        Args:
            model_name (str): A model identifier.

        Returns:
            ProviderName: The owning provider.

        Raises:
            ValueError: When ``model_name`` matches no known prefix.
        """
        return provider_for_model(model_name=model_name)

    @classmethod
    def create_pool(
        cls,
        *,
        pool_dao: "ModelPoolDAO",
        temperature: Optional[float] = None,
        streaming: Optional[bool] = None,
        max_retries: int = 3,
        max_tokens: Optional[int] = None,
        model_kwargs: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
        reasoning_level: ReasoningLevel = "off",
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> "ModelPool":
        """Build a ModelPool, forwarding every build knob to every member.

        Constructs one ``BaseChatModel`` per entry with the same options the
        single-model path uses, so a pooled session is behaviorally equivalent to
        a single-model session (streaming, retries, session attribution,
        reasoning). Injects ``adapt_chatgpt_backend_request`` as the pool's
        per-member request adapter so a mid-call switch between provider lanes
        re-shapes the request correctly. Fails fast if any member lacks a
        credential.

        Uses local imports of ``ModelPool`` and ``adapt_chatgpt_backend_request``
        to avoid circular imports (``model_pool`` and ``graph`` both import
        ``base``).

        Args:
            pool_dao (ModelPoolDAO): Validated pool config with >= 2 entries.
            temperature (Optional[float]): Forwarded to each member.
            streaming (Optional[bool]): Forwarded to each member.
            max_retries (int): SDK-level retries per member. Defaults to 3.
            max_tokens (Optional[int]): Forwarded to each member.
            model_kwargs (Optional[dict[str, Any]]): Provider extras per member.
            session_id (Optional[str]): Active session id for ChatGPT-backend headers.
            reasoning_level (ReasoningLevel): Canonical reasoning level per member.
            snapshot (Optional[ModelCatalogSnapshotDAO]): Caller-supplied immutable
                view for every member; None preserves global catalog reads. This
                constructor does not capture or prepare a runtime generation.

        Returns:
            ModelPool: Ready-to-use pool with all members constructed.

        Raises:
            ValueError: If any member's credential is absent or model name is unknown.
        """
        from src.agents.providers.model_pool import ModelPool
        from src.agents.slo_agent.graph import adapt_chatgpt_backend_request

        models: dict[str, BaseChatModel] = {}
        for entry in pool_dao.entries:
            build_result: LLMBuildResult = cls.create(
                model_name=entry.model_name,
                temperature=temperature,
                streaming=streaming,
                max_retries=max_retries,
                max_tokens=max_tokens,
                model_kwargs=model_kwargs,
                session_id=session_id,
                reasoning_level=reasoning_level,
                snapshot=snapshot,
            )
            models[entry.model_name] = build_result.llm
        return ModelPool(
            pool_dao=pool_dao,
            models=models,
            request_adapter=adapt_chatgpt_backend_request,
            snapshot=snapshot,
        )
