"""Priority-ordered, cooldown-aware, switchable LLM router (28.a.3 / 37.a.2)."""

from __future__ import annotations

import time
from typing import (
    Any,
    AsyncIterator,
    Callable,
    List,
    Optional,
    Sequence,
    cast,
)

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableBinding
from pydantic import BaseModel, Field

from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorClassifier,
    ProviderErrorKind,
    ProviderErrorSignalDAO,
    should_switch,
)
from src.auth.credential_dao import ProviderName

__all__ = [
    "ModelPool",
    "ModelPoolDAO",
    "ModelPoolEntryDAO",
    "RouteSwitchRecordDAO",
]


class ModelPoolEntryDAO(BaseModel):
    """Configuration for a single model slot in the pool.

    Attributes:
        model_name (str): Fully qualified model name (e.g. ``claude-sonnet-4-6``).
        provider (ProviderName): Provider that owns this model's credentials.
        priority (int): Routing order; lower values are tried first.
        cooldown_seconds (int): How long to ban this entry after credit exhaustion.
        rate_limit_cooldown_seconds (int): Shorter ban duration applied after a
            rate-limit (429) or transient server failure (500/502/503/529).
            Defaults to 60s.
    """

    model_name: str
    provider: ProviderName
    priority: int = 0
    cooldown_seconds: int = 300
    rate_limit_cooldown_seconds: int = 60


class ModelPoolDAO(BaseModel):
    """Validated list of pool entries; requires at least two entries.

    Attributes:
        entries (List[ModelPoolEntryDAO]): Pool members, unsorted on input.
    """

    entries: List[ModelPoolEntryDAO] = Field(min_length=2)


class RouteSwitchRecordDAO(BaseModel):
    """One recorded ModelPool route switch, drained by the session for history.

    Attributes:
        from_model_name (str): Member that failed and was cooled.
        to_model_name (str): Member selected for the replayed request, or the
            empty string when the switch exhausted the pool.
        kind (str): ``ProviderErrorKind`` name that triggered the switch.
        error_text (str): Truncated stringified provider exception.
    """

    from_model_name: str
    to_model_name: str
    kind: str
    error_text: str
    provider: ProviderName
    signal: ProviderErrorSignalDAO


RequestAdapter = Callable[
    [BaseChatModel, List[BaseMessage], dict[str, Any]],
    tuple[List[BaseMessage], dict[str, Any]],
]
"""Re-shapes (messages, kwargs) for whichever inner model the pool selects.

Default is the identity adapter. 37.a.3 injects a ChatGPT-backend adapter so a
mid-call switch between provider lanes re-derives the correct request shape.
"""


def _identity_request_adapter(
    model: BaseChatModel,
    messages: List[BaseMessage],
    kwargs: dict[str, Any],
) -> tuple[List[BaseMessage], dict[str, Any]]:
    """Return ``(messages, kwargs)`` unchanged.

    The default adapter used when no provider-specific request shaping is needed.

    Args:
        model (BaseChatModel): The selected inner model (ignored).
        messages (List[BaseMessage]): Request messages.
        kwargs (dict[str, Any]): Invocation kwargs.

    Returns:
        tuple[List[BaseMessage], dict[str, Any]]: The inputs, unchanged.
    """
    return messages, kwargs


class ModelPool(BaseChatModel):
    """Priority-ordered, cooldown-aware, switchable LLM router.

    Wraps multiple :class:`BaseChatModel` instances. On each call the pool
    selects the highest-priority non-cooled member and delegates to it. If the
    member raises a *switchable* provider error (credit exhaustion, rate limit,
    or transient server failure — see ``should_switch``), the member is cooled,
    the switch is recorded, and the same request is replayed through the next
    available member. A non-switchable (``OTHER``) error propagates unchanged.
    When every member is cooling, ``AllModelsExhaustedError`` propagates to the
    caller (and ultimately to the screen).

    Extends ``BaseChatModel`` so it is a drop-in replacement everywhere a single
    model is used — including LangGraph tool-binding.

    Attributes:
        _entries (List[ModelPoolEntryDAO]): Priority-sorted pool entries.
        _models (dict[str, BaseChatModel]): Model name → constructed LLM.
        _cooldowns (dict[str, float]): Model name → monotonic ban-expiry timestamp.
        _pool_dao (ModelPoolDAO): The validated config (held for repr / clone).
        _request_adapter (RequestAdapter): Per-member request shaper.
        _entry_by_name (dict[str, ModelPoolEntryDAO]): Entry lookup by model name.
        _route_switch_log (list[RouteSwitchRecordDAO]): In-memory switch audit log.
    """

    def __init__(
        self,
        *,
        pool_dao: ModelPoolDAO,
        models: dict[str, BaseChatModel],
        cooldowns: Optional[dict[str, float]] = None,
        request_adapter: Optional[RequestAdapter] = None,
    ) -> None:
        """Initialise the pool.

        Args:
            pool_dao (ModelPoolDAO): Validated pool configuration.
            models (dict[str, BaseChatModel]): Pre-constructed model instances
                keyed by model_name. Must include every entry in pool_dao.
            cooldowns (Optional[dict[str, float]]): Initial cooldown timestamps.
                Defaults to an empty dict. Pass a copy when constructing a
                bound-tools clone so active cooldowns are preserved.
            request_adapter (Optional[RequestAdapter]): Per-member request shaper.
                Defaults to the identity adapter.
        """
        super().__init__()
        self._pool_dao: ModelPoolDAO = pool_dao
        self._entries: List[ModelPoolEntryDAO] = sorted(pool_dao.entries, key=lambda e: e.priority)
        self._models: dict[str, BaseChatModel] = models
        self._cooldowns: dict[str, float] = cooldowns or {}
        self._request_adapter: RequestAdapter = request_adapter or _identity_request_adapter
        self._entry_by_name: dict[str, ModelPoolEntryDAO] = {
            entry.model_name: entry for entry in self._entries
        }
        self._route_switch_log: list[RouteSwitchRecordDAO] = []

    # ------------------------------------------------------------------
    # BaseChatModel interface
    # ------------------------------------------------------------------

    @property
    def _llm_type(self) -> str:
        """LangChain type identifier.

        Returns:
            str: Always ``"model-pool"``.
        """
        return "model-pool"

    # ------------------------------------------------------------------
    # Introspection surface (37.a.2) — read by builder / agent / session
    # ------------------------------------------------------------------

    @property
    def llm(self) -> "ModelPool":
        """Return self so the pool fits the shared ``LLMBuildProduct.llm`` slot.

        ``build_slo_agent`` reads ``build_product.llm`` and binds tools on it.
        Returning ``self`` (never the first raw member) keeps the router in the
        graph path and preserves fallback through ``bind_tools``.

        Returns:
            ModelPool: ``self``.
        """
        return self

    @property
    def active_llm(self) -> BaseChatModel:
        """Return the inner model the pool would route to next.

        Used by the graph's ``_uses_chatgpt_backend_responses`` to inspect the
        live member, and by request adaptation.

        Returns:
            BaseChatModel: The currently-selected member (or the first member
                when all are cooling).
        """
        return self._models[self.active_model_name]

    @property
    def active_provider(self) -> ProviderName:
        """Return the provider of the member the pool would route to next.

        Returns:
            ProviderName: Provider owning ``active_model_name``.
        """
        return self._entry_by_name[self.active_model_name].provider

    @property
    def supports_explicit_caching(self) -> bool:
        """Return whether the active route requires explicit cache_control markers.

        Mirrors ``LLMBuildResult.supports_explicit_caching`` for the single-model
        path: only Anthropic requires explicit ``cache_control``.

        Returns:
            bool: ``True`` when the active provider is Anthropic.
        """
        return self.active_provider is ProviderName.ANTHROPIC

    # ------------------------------------------------------------------
    # Routing — generation (sync), generation (async), streaming (async)
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Route one synchronous call, switching on switchable errors.

        Iterates members in priority order, skipping cooled ones. On a
        switchable provider error, cools the member and replays the same request
        through the next member. On ``OTHER``, re-raises. When every member is
        cooling, ``_select_model`` raises ``AllModelsExhaustedError`` which
        propagates to the caller.

        Args:
            messages (List[BaseMessage]): Chat history to send.
            stop (Optional[List[str]]): Stop sequences forwarded to the member.
            run_manager (Optional[CallbackManagerForLLMRun]): LangChain callback.
            **kwargs: Additional kwargs forwarded to the selected member.

        Returns:
            ChatResult: Response from the first member that succeeds.

        Raises:
            AllModelsExhaustedError: When every member is cooling.
            Exception: Any non-switchable (OTHER) member error.
        """
        while True:
            _name, model, entry = self._select_model()
            shaped_messages, shaped_kwargs = self._request_adapter(model, messages, dict(kwargs))
            underlying, merged_kwargs = self._unwrap_member(model=model, kwargs=shaped_kwargs)
            try:
                return underlying._generate(
                    messages=shaped_messages,
                    stop=stop,
                    run_manager=run_manager,
                    **merged_kwargs,
                )
            except Exception as exc:
                if not self._should_switch_after(entry=entry, exc=exc):
                    raise
                continue

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Route one non-streaming async call, switching on switchable errors.

        Iterates members in priority order, skipping cooled ones. On a
        switchable provider error, cools the member and replays the same request
        through the next member. On ``OTHER``, re-raises. When every member is
        cooling, ``_select_model`` raises ``AllModelsExhaustedError`` which
        propagates to the caller (and ultimately to the screen).

        Args:
            messages (List[BaseMessage]): Chat history to send.
            stop (Optional[List[str]]): Stop sequences forwarded to the member.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): LangChain callback.
            **kwargs: Additional kwargs forwarded to the selected member.

        Returns:
            ChatResult: Response from the first member that succeeds.

        Raises:
            AllModelsExhaustedError: When every member is cooling.
            Exception: Any non-switchable (OTHER) member error.
        """
        while True:
            _name, model, entry = self._select_model()
            shaped_messages, shaped_kwargs = self._request_adapter(model, messages, dict(kwargs))
            underlying, merged_kwargs = self._unwrap_member(model=model, kwargs=shaped_kwargs)
            try:
                return await underlying._agenerate(
                    messages=shaped_messages,
                    stop=stop,
                    run_manager=run_manager,
                    **merged_kwargs,
                )
            except Exception as exc:
                if not self._should_switch_after(entry=entry, exc=exc):
                    raise
                continue

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Route one streaming async call, switching only before the first chunk.

        Once the selected member yields any chunk, the response is bound to that
        member: a later failure propagates rather than switching, because
        switching mid-stream would corrupt or duplicate transcript. A switchable
        error *before* the first chunk cools the member and replays through the
        next one.

        Args:
            messages (List[BaseMessage]): Chat history to send.
            stop (Optional[List[str]]): Stop sequences forwarded to the member.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): LangChain callback.
            **kwargs: Additional kwargs forwarded to the selected member.

        Yields:
            ChatGenerationChunk: Streamed chunks from the first member that streams.

        Raises:
            AllModelsExhaustedError: When every member is cooling.
            Exception: Any mid-stream error, or any non-switchable (OTHER) error.
        """
        while True:
            _name, model, entry = self._select_model()
            shaped_messages, shaped_kwargs = self._request_adapter(model, messages, dict(kwargs))
            underlying, merged_kwargs = self._unwrap_member(model=model, kwargs=shaped_kwargs)
            first_chunk_seen: bool = False
            try:
                async for chunk in underlying._astream(
                    shaped_messages,
                    stop=stop,
                    run_manager=run_manager,
                    **merged_kwargs,
                ):
                    first_chunk_seen = True
                    yield chunk
                return
            except Exception as exc:
                if first_chunk_seen:
                    raise
                if not self._should_switch_after(entry=entry, exc=exc):
                    raise
                continue

    # ------------------------------------------------------------------
    # Pool routing helpers
    # ------------------------------------------------------------------

    def _select_model(self) -> tuple[str, BaseChatModel, ModelPoolEntryDAO]:
        """Return the highest-priority non-cooled (model_name, model, entry) triple.

        Returns:
            tuple[str, BaseChatModel, ModelPoolEntryDAO]: The selected triple.

        Raises:
            AllModelsExhaustedError: When every entry is in cooldown.
        """
        now: float = time.monotonic()
        for entry in self._entries:
            cool_until: float = self._cooldowns.get(entry.model_name, 0.0)
            if cool_until <= now:
                return entry.model_name, self._models[entry.model_name], entry
        raise AllModelsExhaustedError(cooled_models=[e.model_name for e in self._entries])

    def _unwrap_member(
        self,
        *,
        model: BaseChatModel,
        kwargs: dict[str, Any],
    ) -> tuple[BaseChatModel, dict[str, Any]]:
        """Unwrap a tool-bound member and merge its bound kwargs into ``kwargs``.

        ``bind_tools`` on a real provider model returns a ``RunnableBinding``
        whose underlying chat model is on ``.bound`` and whose bound kwargs
        (e.g. ``tools``) live on ``.kwargs``. Those kwargs are applied by the
        binding's *public* ``ainvoke``/``astream`` but NOT by the low-level
        ``_agenerate``/``_astream`` the pool delegates to. We therefore unwrap
        to the underlying model and fold the binding's kwargs in, so a pooled,
        tool-bound member still sees its tools (matching the single-model path,
        which reaches ``_agenerate`` through ``ainvoke`` and keeps the tools).

        A non-bound member (e.g. ``FauxChatModel`` or a raw model) is returned
        unchanged. The check is an explicit ``isinstance(RunnableBinding)`` rather
        than a ``getattr(model, "bound")`` probe so it never misfires on mocks or
        models that happen to expose a ``bound`` attribute.

        Args:
            model (BaseChatModel): The selected member (possibly a RunnableBinding).
            kwargs (dict[str, Any]): Call kwargs (after request adaptation).

        Returns:
            tuple[BaseChatModel, dict[str, Any]]: ``(underlying_model, merged_kwargs)``.
        """
        if not isinstance(model, RunnableBinding):
            return model, kwargs
        binding_kwargs: dict[str, Any] = dict(model.kwargs or {})
        binding_kwargs.update(kwargs)
        return cast(BaseChatModel, model.bound), binding_kwargs

    def _should_switch_after(self, *, entry: ModelPoolEntryDAO, exc: Exception) -> bool:
        """Classify ``exc`` and decide whether to cool ``entry`` and switch.

        Records the switch and cools the entry as a side effect when switching,
        so callers only branch on the boolean. Called by every routing method —
        the single place the switch-vs-propagate decision lives.

        Args:
            entry (ModelPoolEntryDAO): The member that raised.
            exc (Exception): The raised provider exception.

        Returns:
            bool: ``True`` when the pool should select the next member and replay.
        """
        signal: ProviderErrorSignalDAO = ProviderErrorClassifier.inspect(
            error=exc,
            provider=entry.provider,
        )
        if not should_switch(kind=signal.kind):
            return False
        self._cool_entry(entry=entry, kind=signal.kind)
        self._record_route_switch(from_entry=entry, signal=signal, error=exc)
        return True

    def _cool_entry(self, *, entry: ModelPoolEntryDAO, kind: ProviderErrorKind) -> None:
        """Record a cooldown for a switched-away member.

        Credit exhaustion uses the long ``entry.cooldown_seconds`` (default 300s);
        rate limits and transient provider failures use the short
        ``entry.rate_limit_cooldown_seconds`` (default 60s) so the pool retries
        the lane sooner after a recoverable blip.

        Args:
            entry (ModelPoolEntryDAO): The member to cool.
            kind (ProviderErrorKind): Determines which cooldown duration applies.
        """
        short_cooldown_kinds = (
            ProviderErrorKind.RATE_LIMITED,
            ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE,
            ProviderErrorKind.STREAM_DISCONNECTED,
        )
        seconds: int = (
            entry.rate_limit_cooldown_seconds if kind in short_cooldown_kinds else entry.cooldown_seconds
        )
        self._cooldowns[entry.model_name] = time.monotonic() + seconds

    def _record_route_switch(
        self,
        *,
        from_entry: ModelPoolEntryDAO,
        signal: ProviderErrorSignalDAO,
        error: Exception,
    ) -> None:
        """Append one route-switch record to the in-memory audit log.

        The session drains this log after each turn and persists
        ``route_switched`` history events (37.a.6). ``to_model_name`` is
        resolved best-effort from the next available member, or empty when the
        pool is now exhausted.

        Args:
            from_entry (ModelPoolEntryDAO): The cooled member.
            kind (ProviderErrorKind): Classified switch reason.
            error (Exception): The triggering exception (truncated when recorded).
        """
        try:
            to_model_name, _, _ = self._select_model()
        except AllModelsExhaustedError:
            to_model_name = ""
        self._route_switch_log.append(
            RouteSwitchRecordDAO(
                from_model_name=from_entry.model_name,
                to_model_name=to_model_name,
                kind=signal.kind.name,
                error_text=self._safe_route_switch_error_text(kind=signal.kind, error=error),
                provider=from_entry.provider,
                signal=signal,
            )
        )

    def _safe_route_switch_error_text(self, *, kind: ProviderErrorKind, error: Exception) -> str:
        """Return a route-switch audit value safe for the classified failure kind.

        Args:
            kind (ProviderErrorKind): Shared classification that caused the route switch.
            error (Exception): Original exception retained only for existing failure kinds.

        Returns:
            str: Stable stream-disconnection code or the legacy bounded error text.
        """
        if kind is ProviderErrorKind.STREAM_DISCONNECTED:
            return "provider_stream_disconnected"
        return str(error)[:500]

    def drain_route_switch_log(self) -> list[RouteSwitchRecordDAO]:
        """Return and clear the accumulated route-switch records.

        Called by the session after each turn to persist switches to history.

        Returns:
            list[RouteSwitchRecordDAO]: Records since the last drain, in order.
        """
        drained: list[RouteSwitchRecordDAO] = list(self._route_switch_log)
        self._route_switch_log.clear()
        return drained

    # ------------------------------------------------------------------
    # Tool binding
    # ------------------------------------------------------------------

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> "ModelPool":
        """Return a new pool with tools bound on every inner model.

        Preserves active cooldowns from the current pool so a tool-binding event
        at graph compile time does not reset cooldown state, and forwards the
        request adapter so mid-call lane re-shaping survives binding. The clone
        starts with a fresh route-switch log: the clone is the long-lived object
        the graph holds and the session drains.

        Args:
            tools (Sequence[Any]): Tools to bind (same contract as BaseChatModel).
            **kwargs: Forwarded to each inner model's ``bind_tools``.

        Returns:
            ModelPool: New pool instance with bound members, copied cooldowns,
                and the same request adapter.
        """
        bound_models: dict[str, BaseChatModel] = {
            name: cast(BaseChatModel, model.bind_tools(tools, **kwargs))
            for name, model in self._models.items()
        }
        return ModelPool(
            pool_dao=self._pool_dao,
            models=bound_models,
            cooldowns=dict(self._cooldowns),
            request_adapter=self._request_adapter,
        )

    # ------------------------------------------------------------------
    # Status bar integration
    # ------------------------------------------------------------------

    @property
    def active_model_name(self) -> str:
        """Return the model name that would be selected next.

        Duck-typed by ``SloAgentSession._resolve_active_model_name()`` to drive
        the TUI status bar and the routed-model identity surfaces.

        Returns:
            str: Model name of the highest-priority non-cooled entry, or the
                first entry's name when all are cooled.
        """
        try:
            name, _, _ = self._select_model()
            return name
        except AllModelsExhaustedError:
            return self._entries[0].model_name if self._entries else "unknown"
