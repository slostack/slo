"""``SloAgentSession`` — in-process wrapper around ``SloAgent`` (sub-spec 02.a.1, extended in 05.c).

Owns exactly one ``SloAgent`` instance plus the subscriber list the TUI
and tests register against. Mirrors pi's ``AgentSession`` at
``pi/packages/coding-agent/src/core/agent-session.ts:962``.

Sub-spec 05.c makes the session the orchestrator of persistent
history. Each accepted prompt now:

1. ensures the on-disk session directory exists,
2. loads prior projected ``BaseMessage`` history,
3. persists ``run_started`` and ``user_message`` events before the
   agent runs,
4. forwards full-fidelity runtime trace events into the canonical
   store via an injected trace handler,
5. appends the terminal ``run_completed`` / ``run_aborted`` /
   ``run_failed`` event before clearing the running flag.

Unlike render subscribers, history writes are not best-effort:
persistence failures propagate so runtime state cannot silently
diverge from disk.

Canonical location: sessions/service.py (spec 04 structural refactoring).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional, TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from config.ai_model_config import MODEL_DEFAULTS, defaults_for_model
from config.cfg import cfg
from config.logger import log_error, log_info, log_warning
from config.timeout_resolver import positive_int_env
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.providers.stream_recovery.dao import (
    ProviderStreamFailure,
    StreamRecoveryAction,
    StreamRecoveryDecisionDAO,
)
from src.agents.providers.stream_recovery.service import provider_stream_continuation_max_attempts
from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    ProviderErrorClassifier,
    ProviderErrorKind,
    ProviderErrorSignalDAO,
    ProviderLimitObservationDAO,
)
from src.agents.providers.model_pool import ModelPoolDAO, ModelPoolEntryDAO, RouteSwitchRecordDAO
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease
from src.agents.slo_agent.herdr.visualizer import HerdrVisualizerLauncher
from src.agents.slo_agent.herdr.editor import HerdrEditorLauncher
from src.agents.slo_agent.herdr.dao import HerdrVisualizerRequestDAO, VisualizerLaunchOutcomeDAO
from src.agents.slo_agent.orchestrator.context_reader import OrchestratorContextReader
import shutil
from src.agents.slo_agent.herdr.reporter import HerdrReporter
from src.agents.slo_agent.herdr.service import (
    HerdrEnvironmentGate,
    HerdrTaskJoin,
    HerdrSnapshotProjector,
    NullHerdrReporter,
)
from src.agents.slo_agent.herdr.dao import (
    HerdrReporterProtocol,
    HerdrDestination,
    HerdrReporterCloseOutcomeDAO,
    HerdrPublicationDAO,
    HerdrReporterConfigDAO,
    HerdrRestoreCaptureDAO,
    HerdrRestoreConfigDAO,
    HerdrRestorePoolDAO,
    HerdrRestorePoolEntryDAO,
)
from src.agents.slo_agent.sessions.identity import is_canonical_uuid_session_id
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.workspace.dao import WorkspaceFolderDAO
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    default_history_root,
)
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.compaction.compaction_checker import CompactionChecker
from src.agents.slo_agent.compaction.compacter import Compacter
from src.agents.slo_agent.compaction.context_window import (
    ContextWindowSnapshotDAO,
    ContextWindowSnapshotService,
)
from src.agents.slo_agent.compaction.compacted_session_updater import CompactedSessionUpdater
from src.agents.slo_agent.rate_limit.service import int_or_none
from src.agents.slo_agent.rate_limit.dao import (
    ModelRateLimitPolicyDAO,
    RateLimitRetryPlanDAO,
)
from src.agents.slo_agent.rate_limit.service import (
    IterationRetryPolicy,
    estimate_request_tokens,
    policy_for_model,
    retry_plan_from_error,
)
from src.agents.slo_agent.recovery.dao import RecoveryDecisionDAO
from src.agents.slo_agent.recovery.service import (
    IterationRecoveryPolicy,
    RecoveryPolicy,
)
from src.agents.slo_agent.events.runtime import (
    AgentRuntimeEventDAO,
    AgentRuntimeHandler,
)
from src.agents.slo_agent.runtime import SloRuntimeContext
from src.agents.slo_agent.sessions.dao import (
    AgentEventSubscriber,
    HerdrOrchestratorProvenanceDAO,
    OperatorAttentionDAO,
    OperatorAttentionReason,
    SessionReportingStateDAO,
    ManualCompactionResultDAO,
    PreflightBypassNoticeDAO,
    PreflightDecisionDAO,
    SessionConfigDAO,
)
from src.agents.slo_agent.sessions.usage import (
    SessionUsageSnapshotDAO,
    TokenUsageTotalsDAO,
)
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.reasoning_capabilities import (
    ReasoningLevel,
    clamp_reasoning_level,
    default_reasoning_level_for_model,
    resolve_reasoning_config,
)
from src.agents.tools.bundles import create_extended_tools
from src.auth.credential_dao import CredentialDAO, ProviderName
from src.integrations.openrouter.dao import credential_fingerprint
from src.auth.credential_refresher import refresh_if_stale
from src.auth.credential_resolver import CredentialResolver
from src.auth.credential_store import CredentialStore
from src.auth.provider_for_model import provider_for_model

from src.agents.slo_agent.history.transcript import ReplayEntryProjector

if TYPE_CHECKING:
    from src.agents.providers.model_pool import ModelPoolDAO
    from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
    from src.agents.slo_agent.orchestrator.dao import (
        AttachedDispatchSnapshotDAO,
        ChildAbortOutcomeDAO,
        ChildAbortRequestDAO,
        ChildControlCapabilityDAO,
    )
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

from src.agents.slo_agent.plugins.dao import PluginHealthDAO, PluginRegistrationDAO
from src.agents.slo_agent.plugins.dispatcher import PluginDispatcher
from src.agents.slo_agent.plugins.registry import PluginRegistry
from src.agents.slo_agent.plugins.trust import PluginTrustStore

__all__ = ["SloAgentSession"]


_DISPATCH_AUDIT_KEYS: tuple[str, ...] = ("dispatch_id", "dispatch_sequence", "execution_id")
"""Pool lifecycle metadata copied into the existing sub-agent audit records (feature 94 a.2)."""

_RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS: int = 8192
"""Realistic per-turn output estimate for the local TPM pre-flight check.

Deliberately decoupled from ``MODEL_DEFAULTS[...]["max_tokens"]``, which is the
model's *hard output ceiling* (64K/128K after spec 02). Feeding that ceiling into
the local token-window estimator would assume every turn emits the full ceiling and
trip artificial multi-second waits after a few back-to-back turns. A typical turn
emits far less; 8192 (the historical pre-02 value) keeps the local rate-limit
behavior stable. The TUI usage snapshot still surfaces the true ceiling separately.
"""

_COMPACTION_ADVISORY_DEFAULT_TOKENS: int = 256_000
"""Default projector-faithful context estimate that triggers the latency advisory.

The advisory only asks the user to run ``/compact``; it never compacts. Override
with the positive integer environment variable ``SLO_COMPACTION_ADVISORY_TOKENS``.
"""

_COMPACTION_REDACTED_PLACEHOLDER: str = "<redacted>"
"""Deterministic replacement applied to every matched secret fragment."""

_COMPACTION_FAILURE_MESSAGE_LIMIT: int = 300
"""Maximum length of a redacted compaction failure message before truncation."""

_COMPACTION_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        _COMPACTION_REDACTED_PLACEHOLDER,
    ),
    (
        re.compile(r"sk-ant-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]+"),
        _COMPACTION_REDACTED_PLACEHOLDER,
    ),
    (
        re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s,;\"'}]+"),
        f"Authorization={_COMPACTION_REDACTED_PLACEHOLDER}",
    ),
    (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
        f"Bearer {_COMPACTION_REDACTED_PLACEHOLDER}",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|secret|password)"
            r"\b\s*[:=]\s*[\"']?[^\s,;\"'}]+"
        ),
        rf"\1={_COMPACTION_REDACTED_PLACEHOLDER}",
    ),
    (
        re.compile(
            r"(?i)([?&](?:(?:x-amz-)?(?:signature|credential|security-token)|"
            r"sig|token|access_token|api[_-]?key|key)=)[^&\s]+"
        ),
        rf"\1{_COMPACTION_REDACTED_PLACEHOLDER}",
    ),
    (
        re.compile(r"://[^/\s:@]+:[^/\s@]+@"),
        f"://{_COMPACTION_REDACTED_PLACEHOLDER}@",
    ),
)
"""Ordered local redaction rules applied before any compaction failure text is surfaced."""

_DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS: float = 10800.0
"""Maximum silence tolerated from the main agent stream before it is treated as hung.

This mirrors the sub-agent child-process inactivity guard: if the model/tool lane
stops producing events entirely after a prompt has started, the TUI should fail the
turn rather than spin forever.
"""


def _stream_inactivity_timeout_seconds() -> float:
    """Return the configured main-stream inactivity timeout.

    ``SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS`` accepts any positive float value.
    Invalid or non-positive values fall back to the built-in default.

    Returns:
        float: Seconds of tolerated silence before the stream is treated as hung.
    """
    raw_value: object = cfg(key="SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS")
    try:
        parsed: float = (
            float(raw_value)  # type: ignore[arg-type]  # intentional broad coercion
            if raw_value is not None
            else _DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        return _DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS
    if parsed <= 0:
        return _DEFAULT_STREAM_INACTIVITY_TIMEOUT_SECONDS
    return parsed


class PromptAttemptPlanDAO(BaseModel):
    """Plan describing how to run one attempt for one user prompt.

    A prompt submission may involve more than one attempt. An initial attempt
    runs the prompt normally. A future overflow-retry attempt would run the
    same prompt again after compaction. This value object records the policy
    for a single attempt.

    Attributes:
        attempt_kind (Literal["initial", "overflow_retry", "stream_reconnect"]): Whether this
            is the first attempt or a same-prompt retry after a failure.
        text (str): The user prompt text to send to the agent.
        persist_user_message (bool): Whether this attempt should write a
            ``user_message`` event to durable history. The initial attempt
            always writes one. A retry of the same prompt does not.
        excluded_turn_ids (frozenset[str]): Completed turn ids that must be
            ignored when rebuilding replay history for this attempt only.
            Used so a retry does not immediately replay the turn that just
            failed. Durable history is never changed; the exclusion is local
            to this one history rebuild.
        preflight_compaction_mode (Literal["respect_dirty_flag", "skip"]):
            Controls whether the attempt runs the one-shot preflight
            compaction check. ``"respect_dirty_flag"`` runs the check when
            the active model/context window may have changed.
            ``"skip"`` bypasses it, which is useful for retry attempts that
            already performed a forced compaction.
        source_failed_turn_id (Optional[str]): When this attempt is a retry,
            the turn id of the failed attempt that produced it. ``None`` for
            the initial attempt.
    """

    model_config = ConfigDict(frozen=True)

    attempt_kind: Literal["initial", "overflow_retry", "stream_reconnect", "stream_continuation"] = Field(
        description="Whether this is the first attempt or a same-prompt retry after a failure."
    )
    text: str = Field(description="The user prompt text to send to the agent.")
    persist_user_message: bool = Field(
        default=True,
        description="Whether this attempt should write a user_message event to durable history.",
    )
    excluded_turn_ids: frozenset[str] = Field(
        default_factory=frozenset,
        description="Completed turn ids ignored when rebuilding replay history for this attempt.",
    )
    preflight_compaction_mode: Literal["respect_dirty_flag", "skip"] = Field(
        default="respect_dirty_flag",
        description="Controls whether the attempt runs the one-shot preflight compaction check.",
    )
    source_failed_turn_id: Optional[str] = Field(
        default=None,
        description="Turn id of the failed attempt that produced this retry, or None for initial.",
    )
    submission_attempt_number: int = Field(
        default=1,
        ge=1,
        description="One-indexed session attempt number for the original prompt.",
    )
    max_submission_attempts: int = Field(
        default=5,
        ge=1,
        description="Maximum total session attempts for the original prompt.",
    )
    original_text: str = Field(
        default="",
        description="Original user prompt retained for a safe continuation request.",
    )


class PreparedPromptAttemptDAO(BaseModel):
    """Resolved runtime collaborators needed to execute one attempt.

    This object is built from a ``PromptAttemptPlanDAO`` and contains every
    dependency the execution phase needs: the turn id, the replay history,
    the history trace handler, and the rate policy.

    Attributes:
        plan (PromptAttemptPlanDAO): The original attempt plan.
        turn_id (str): UUID4 identifier for this attempt's turn.
        message_history (list[BaseMessage]): Prior conversation messages to
            pass into the agent's ``message_history`` argument.
        runtime_handler (Optional[AgentRuntimeHandler]): Handler that maps
            runtime agent trace events into canonical history events.
        policy (ModelRateLimitPolicyDAO): Rate policy for the currently
            routed model, used to derive the per-iteration retry plan.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    plan: PromptAttemptPlanDAO = Field(description="The original attempt plan.")
    turn_id: str = Field(description="UUID4 identifier for this attempt's turn.")
    message_history: list[BaseMessage] = Field(
        default_factory=list,
        description="Prior conversation messages to pass into the agent.",
    )
    runtime_handler: Optional[AgentRuntimeHandler] = Field(
        default=None,
        description="Handler that maps runtime agent trace events into canonical history events.",
    )
    policy: ModelRateLimitPolicyDAO = Field(
        description="Rate policy for the currently routed model.",
    )


class PromptAttemptTrackerDAO(BaseModel):
    """Mutable accumulator for one attempt while it streams.

    The tracker is updated as events are yielded from the agent stream. After
    the attempt finishes, its state is frozen into a
    ``PromptAttemptResultDAO``.

    Attributes:
        turn_id (str): Turn id this tracker is watching.
        final_response (str): Assistant text when the attempt ends with
            ``run_completed``; ``"<aborted>"`` when it ends with
            ``run_aborted``; empty string otherwise.
        aborted (bool): True when the attempt ended in ``run_aborted``.
        terminal_kind (Optional[Literal["run_completed", "run_aborted",
            "run_failed"]]): Terminal outcome once known.
        error (Optional[BaseException]): Captured exception when the attempt
            failed.
        terminal_event_appended (bool): Whether a terminal event has already
            been written to durable history.
        overflow_recovery_eligible (bool): True when the terminal failure was
            a recognized provider context overflow. Used by
            ``_derive_next_attempt_plan`` to decide whether a one-shot
            recovery retry is warranted.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    turn_id: str = Field(description="Turn id this tracker is watching.")
    final_response: str = Field(default="", description="Final assistant response text.")
    aborted: bool = Field(default=False, description="True when the attempt ended in run_aborted.")
    terminal_kind: Optional[Literal["run_completed", "run_aborted", "run_failed"]] = Field(
        default=None,
        description="Terminal outcome once known.",
    )
    error: Optional[BaseException] = Field(
        default=None,
        description="Captured exception when the attempt failed.",
    )
    terminal_event_appended: bool = Field(
        default=False,
        description="Whether a terminal event has already been written to durable history.",
    )
    overflow_recovery_eligible: bool = Field(
        default=False,
        description=(
            "True when the terminal failure was an initial recognized provider context overflow. "
            "Set in _finalize_failed_attempt; read by _derive_next_attempt_plan."
        ),
    )
    committed_visible_output: bool = Field(
        default=False,
        description="Whether this provider attempt crossed the agent output commit boundary.",
    )
    provider_signal: Optional[ProviderErrorSignalDAO] = Field(
        default=None,
        description="Typed inspection result for an escaped provider rejection.",
    )
    preflight_decision: Optional[PreflightDecisionDAO] = Field(
        default=None,
        description="Successful local preflight decision for this provider attempt.",
    )
    stream_failure: Optional[ProviderStreamFailure] = Field(
        default=None,
        description="Typed redacted provider stream failure eligible for one reconnect.",
    )


class PromptAttemptResultDAO(BaseModel):
    """Frozen terminal summary of one prompt attempt.

    This object is produced from a ``PromptAttemptTrackerDAO`` after the
    attempt lifecycle completes. It is the only artifact the top-level
    orchestrator uses to decide whether the submission is finished or needs
    a follow-up attempt.

    Attributes:
        turn_id (str): Turn id of the attempt.
        terminal_kind (Literal["run_completed", "run_aborted", "run_failed"]):
            Final outcome of the attempt.
        final_response (str): Response text or ``"<aborted>"`` surrogate.
        aborted (bool): True when the attempt ended in ``run_aborted``.
        error (Optional[BaseException]): Captured terminal exception.
        overflow_recovery_eligible (bool): True when the failure was a
            recognized provider context overflow on an initial attempt.
            ``_derive_next_attempt_plan`` reads this to decide whether to
            attempt same-submission overflow recovery.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    turn_id: str = Field(description="Turn id of the attempt.")
    terminal_kind: Literal["run_completed", "run_aborted", "run_failed"] = Field(
        description="Final outcome of the attempt."
    )
    final_response: str = Field(description="Response text or '<aborted>' surrogate.")
    aborted: bool = Field(description="True when the attempt ended in run_aborted.")
    error: Optional[BaseException] = Field(
        default=None,
        description="Captured terminal exception.",
    )
    overflow_recovery_eligible: bool = Field(
        default=False,
        description="True when the failure was a recognized provider context overflow.",
    )
    committed_visible_output: bool = Field(
        default=False,
        description="Whether this provider attempt crossed the agent output commit boundary.",
    )
    stream_failure: Optional[ProviderStreamFailure] = Field(
        default=None,
        description="Typed redacted provider stream failure from the agent attempt.",
    )
    provider_signal: Optional[ProviderErrorSignalDAO] = Field(
        default=None,
        description="Typed inspection result for an escaped provider rejection.",
    )
    preflight_decision: Optional[PreflightDecisionDAO] = Field(
        default=None,
        description="Successful local preflight decision for this provider attempt.",
    )
    originating_provider: Optional[ProviderName] = Field(
        default=None,
        description="Provider that owned the failed attempt before any later route selection.",
    )


class HerdrPolicySourcesDAO(BaseModel):
    """Private immutable commit comparison; never persisted or publicly projected."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")
    model_name: Optional[str] = Field(repr=False, description="Configured model source.")
    configured_reasoning: Optional[ReasoningLevel] = Field(
        repr=False, description="Original reasoning input."
    )
    history_enabled: bool = Field(repr=False, description="Configured persistence policy.")
    effective_reasoning: ReasoningLevel = Field(repr=False, description="Committed effective reasoning.")
    paths: tuple[object, ...] = Field(repr=False, description="Copied lexical path sources.")
    pool: Optional[HerdrRestorePoolDAO] = Field(repr=False, description="Validated immutable pool scalars.")

    def permits_commit(
        self, *, previous: HerdrPolicySourcesDAO, model_selection: bool, reasoning_commit: bool
    ) -> bool:
        """Permit a new capture commit only when all unowned policy sources are unchanged.

        WHAT: Compares this freshly sampled source snapshot against the previous
            committed snapshot. ``configured_reasoning``, ``history_enabled`` and
            ``paths`` are never owned by any gateway and must always match.
        WHO: ``SloAgentSession._adopt_herdr_capture`` calls it before advancing
            the configuration generation; an inequality invalidates the capture
            instead of committing.
        WHEN: At every capture-adoption point (history ensure, model selection,
            prepared/reasoning commit, startup).

        Args:
            previous (HerdrPolicySourcesDAO): Previously committed source snapshot.
            model_selection (bool): Authority of the model-selection gateway;
                permits ``model_name`` and ``pool`` to change (and transitively
                ``effective_reasoning``).
            reasoning_commit (bool): Authority of a prepared/reasoning commit
                gateway; permits ``effective_reasoning`` alone to change.

        Returns:
            bool: True when every field not permitted by the named authorities
                is unchanged, so the new capture may commit.
        """
        return (
            self.configured_reasoning == previous.configured_reasoning
            and self.history_enabled == previous.history_enabled
            and self.paths == previous.paths
            and (model_selection or (self.model_name == previous.model_name and self.pool == previous.pool))
            and (
                model_selection
                or reasoning_commit
                or self.effective_reasoning == previous.effective_reasoning
            )
        )


class SloAgentSession:
    """One ``SloAgent`` per process, one in-flight prompt at a time."""

    def __init__(
        self,
        *,
        workdir: Path,
        session_id: str,
        config: Optional[SessionConfigDAO] = None,
        agent: Optional[SloAgent] = None,
        history_store: Optional[SessionHistoryStoreProtocol] = None,
        history_projector: Optional[SessionHistoryProjector] = None,
        enable_history: Optional[bool] = None,
        plugin_paths: Optional[list[Path]] = None,
        plugin_loader_kwargs: Optional[dict[str, Path]] = None,
        catalog_snapshot: Optional[ModelCatalogSnapshotDAO] = None,
        pending_preparation: bool = False,
    ) -> None:
        """Compose a session around a config (lazy) or a pre-built agent.

        Args:
            pending_preparation (bool): Defer capabilities and expose unknown usage
                until the mounted TUI completes catalog preparation.
            catalog_snapshot (Optional[ModelCatalogSnapshotDAO]): Caller-supplied
                initialization/build view. Configured OpenRouter prompts revalidate
                through the catalog gateway and pin its result until run exit.
            workdir (Path): Absolute workdir the agent operates in.
            session_id (str): Stable session identifier (UUID4 or
                caller-supplied for resume).
            config (Optional[SessionConfigDAO]): Stored for the lazy
                build path. Required when ``agent`` is ``None``.
            agent (Optional[SloAgent]): A pre-built agent. When
                supplied, no lazy construction happens.
            history_store (Optional[SessionHistoryStoreProtocol]):
                Optional explicit store collaborator (sub-spec 05.c).
                When ``None`` and ``enable_history`` is ``True`` a
                default ``TreeBasedFileSystemSessionHistoryStore`` is
                constructed. Pass a ``FilesystemSessionHistoryStore``
                explicitly to use the legacy flat-JSONL layout.
            history_projector (Optional[SessionHistoryProjector]):
                Optional explicit projector collaborator.
            enable_history (bool): Persist history when ``True``. Tests
                that inject a pre-built agent typically pass ``False``
                to keep the workdir clean.

        Raises:
            ValueError: When neither ``config`` nor ``agent`` is given.
        """
        if config is None and agent is None:
            raise ValueError(
                "SloAgentSession requires either a SessionConfigDAO (for lazy "
                "agent construction) or a pre-built SloAgent."
            )
        self._workdir: Path = workdir.resolve()
        self._session_id: str = session_id
        self._config: Optional[SessionConfigDAO] = config
        self._preparation_status: Literal["pending", "ready", "failed"] = (
            "pending" if pending_preparation else "ready"
        )
        self._preparation_lock: asyncio.Lock = asyncio.Lock()
        self._catalog_snapshot: Optional[ModelCatalogSnapshotDAO] = catalog_snapshot
        self._admitted_run_snapshot: Optional[ModelCatalogSnapshotDAO] = None
        self._admitted_openrouter_credential: Optional[CredentialDAO] = None
        self._agent_openrouter_fingerprint: Optional[str] = None
        self._agent: Optional[SloAgent] = agent
        self._agent_is_injected: bool = agent is not None
        self._herdr_reporter: HerdrReporterProtocol = NullHerdrReporter(destination="platform")
        self._herdr_start_task: Optional[asyncio.Task[None]] = None
        self._herdr_close_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._herdr_retired_drain_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._herdr_finish_cleanup_task: Optional[asyncio.Task[HerdrReporterCloseOutcomeDAO]] = None
        self._candidate_pool_cleanup_task: Optional[asyncio.Task[None]] = None
        self._herdr_closing = self._herdr_suppressed = self._herdr_close_uncertain = False
        self._herdr_reporting_started = False
        self._herdr_metadata_profile: Literal["compact", "detail"] = "compact"
        self._operator_attention: Optional[OperatorAttentionDAO] = None
        self._attention_serial = self._operation_serial = 0
        self._reporting_operations: set[int] = set()
        self._suspended_reporting_operation: Optional[int] = None
        self._herdr_destination: HerdrDestination = "platform"
        self._herdr_visualizer: Optional[HerdrVisualizerLauncher] = None
        self._herdr_editor: Optional[HerdrEditorLauncher] = None
        self._herdr_viewer_drain_failed = False
        self._herdr_interactive: bool = False
        self._herdr_default_history: bool = False
        self._herdr_history_persisted: bool = False
        self._herdr_workspace_file: Optional[Path] = None
        self._herdr_workdir: Path = self._workdir
        self._herdr_plugin_paths: tuple[Path, ...] = ()
        self._herdr_path_sources: Optional[tuple[object, ...]] = None
        self._herdr_policy_sources: Optional[HerdrPolicySourcesDAO] = None
        self._herdr_policy_invalidated: bool = False
        self._herdr_pristine_origin: bool = config is not None and (
            config.system_prompt is None
            and config.append_system_prompt is None
            and not config.extra_tools
            and config.should_stop_after_turn_hook is None
        )
        self._herdr_capture: Optional[HerdrRestoreCaptureDAO] = None
        self._herdr_capture_session_id: str = session_id
        self._herdr_configuration_generation: int = 0
        self._standard_orchestrator_attachment: Optional[HerdrOrchestratorProvenanceDAO] = None
        self._agent_catalog_snapshot: Optional[ModelCatalogSnapshotDAO] = catalog_snapshot
        configured_plugin_paths: list[Path] = list(config.plugin_paths) if config is not None else []
        self._plugin_paths: list[Path] = list(plugin_paths or configured_plugin_paths)
        self._plugin_loader_kwargs: dict[str, Path] = dict(plugin_loader_kwargs or {})
        self._plugin_registry: Optional["PluginRegistry"] = None
        self._plugin_dispatcher: Optional["PluginDispatcher"] = None
        self._plugin_trust_store: Optional["PluginTrustStore"] = None
        self._subscribers: list[AgentEventSubscriber] = []
        self._is_running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        # Default policy: persistent history is on by default for the
        # production lazy-config path; tests that inject a pre-built
        # agent (config=None) get history disabled by default so the
        # workdir-scoped tests do not touch ``~/.slo``. An explicit
        # ``enable_history`` argument always wins.
        if enable_history is None:
            self._enable_history: bool = config is not None
        else:
            self._enable_history = enable_history
        # Register the internal history subscriber for sub-agent lifecycle
        # events when history is enabled. This subscriber runs alongside
        # external TUI/test subscribers and persists parent↔child links.
        self._subscribers.append(self._on_herdr_event)
        if self._enable_history:
            self._subscribers.append(self._on_stream_event_for_history)
        self._sub_agent_pool: Optional["SubAgentPool"] = None
        self._history_store: Optional[SessionHistoryStoreProtocol] = history_store
        if self._enable_history and self._history_store is None:
            self._history_store = TreeBasedFilesystemSessionHistoryStore(
                root=(config.resolved_history_root() if config is not None else None),
            )
        self._history_projector: SessionHistoryProjector = history_projector or SessionHistoryProjector()
        self._history_session_ensured: bool = False
        self._load_plugins()
        # Marks that the effective context window may have shrunk or has not yet
        # been validated for the active model — set on every model switch and
        # initialized True so the first turn after build/resume runs one
        # pre-flight compaction check. Cleared after that check; steady-state
        # turns rely solely on the post-turn check.
        self._context_window_dirty: bool = True
        self._active_model_name: Optional[str] = (
            config.model_name or cfg("DEFAULT_MODEL_NAME")
            if config is not None
            else cfg("DEFAULT_MODEL_NAME")
        )
        self._startup_fallback_notice: Optional[str] = config.fallback_notice if config is not None else None
        self._active_reasoning_level: ReasoningLevel = self._seed_active_reasoning_level(
            config=config,
        )
        self._herdr_policy_sources = self._snapshot_herdr_policy_sources()
        self._allows_model_switching: bool = config is not None
        self._session_usage_totals: TokenUsageTotalsDAO = TokenUsageTotalsDAO()
        self._recent_request_times: deque[float] = deque()
        self._recent_request_token_estimates: deque[tuple[float, int]] = deque()
        self._preflight_decisions_by_turn: dict[str, PreflightDecisionDAO] = {}
        self._cooldown_until: Optional[float] = None
        self._cooldown_seconds_remaining: Optional[int] = None
        self._startup_notice_shown_in_memory: bool = False
        self._context_window_snapshot: Optional[ContextWindowSnapshotDAO] = None
        self._compaction_advisory_armed: bool = True
        self._usage_snapshot: SessionUsageSnapshotDAO = self._build_usage_snapshot()
        self._orchestrator_context_written: bool = False
        # Idempotency cache for record_workflow_update (spec 57.a.4): inbox
        # message ids whose workflow_update event is already persisted. Seeded
        # lazily from the event log on the first record call.
        self._workflow_message_ids_seen: Optional[set[str]] = None
        self.runtime_context: "SloRuntimeContext" = self._build_runtime_context()
        log_info(msg=f"SloAgentSession built session_id={session_id[:8]} workdir={self._workdir}")

    @classmethod
    def build(
        cls,
        *,
        config: SessionConfigDAO,
        catalog_snapshot: Optional[ModelCatalogSnapshotDAO] = None,
        allow_pending_preparation: bool = False,
    ) -> "SloAgentSession":
        """Build a lazily initialized session from an already prepared config.

        WHAT: Refuses an unprepared direct OpenRouter route before synchronous
            reasoning or usage initialization can construct/invoke it.
        WHO: Cached/direct callers use this; headless callers use ``prepare``.
        WHEN: Runs before the first prompt and never performs catalog HTTP.

        Args:
            config (SessionConfigDAO): Validated session configuration.
            allow_pending_preparation (bool): TUI-only opt-in to deferred startup;
                strict programmatic and headless construction remains the default.
            catalog_snapshot (Optional[ModelCatalogSnapshotDAO]): Prepared immutable
                catalog generation, if the configured route needs one.

        Returns:
            SloAgentSession: A fresh session ready for lazy agent construction.

        Raises:
            ModelPreparationRequiredError: The direct OpenRouter route lacks a
                prepared catalog generation.
        """
        pending_preparation: bool = False
        try:
            cls._require_prepared_openrouter_route(config=config, snapshot=catalog_snapshot)
        except ModelPreparationRequiredError:
            if not allow_pending_preparation:
                raise
            pending_preparation = True
        session_id: str = config.session_id or str(uuid4())
        return cls(
            workdir=config.workdir,
            session_id=session_id,
            config=config,
            enable_history=config.enable_history,
            catalog_snapshot=catalog_snapshot,
            pending_preparation=pending_preparation,
        )

    @property
    def preparation_status(self) -> Literal["pending", "ready", "failed"]:
        """Return transient startup readiness, never persisted to history or preferences."""
        return self._preparation_status

    async def prepare_startup(self) -> None:
        """Adopt one prepared catalog on the mounted session without replacing its identity.

        The TUI owns task cancellation; this session serializes duplicate callers.
        All fallible capability/usage derivation completes before the no-await commit.
        Failure retains the route and unknown limits for explicit retry or authentication.

        Raises:
            ModelPreparationRequiredError: Preparation failed with safe recovery guidance.
            asyncio.CancelledError: The owning TUI was closed.
        """
        async with self._preparation_lock:
            if self._preparation_status == "ready":
                return
            async with self._startup_reporting_scope():
                await self._prepare_startup_locked()

    async def _prepare_startup_locked(self) -> None:
        """Derive and atomically adopt startup capabilities under the preparation lock."""
        self._preparation_status = "pending"
        assert self._config is not None
        startup_config = self._config
        try:
            snapshot = await ModelCatalogService.prepare_models(
                model_names=self._configured_model_names(config=self._config)
            )
            if self._config is not startup_config:
                return
            self._require_prepared_openrouter_route(config=self._config, snapshot=snapshot)
            reasoning = clamp_reasoning_level(
                model_name=self.active_model_name,
                requested_level=self.active_reasoning_level,
                snapshot=snapshot,
            )
            usage = self._build_usage_snapshot(snapshot=snapshot, reasoning_level=reasoning)
        except BaseException as error:
            if self._config is not startup_config:
                if isinstance(error, asyncio.CancelledError):
                    raise
                return
            self._preparation_status = "failed"
            if isinstance(error, asyncio.CancelledError):
                raise
            if not isinstance(error, Exception):
                raise
            raise ModelPreparationRequiredError(
                "Model preparation failed; use /auth or /model refresh to retry."
            ) from None
        self._withdraw_stale_herdr_capture()
        self._catalog_snapshot = snapshot
        self._active_reasoning_level = reasoning
        self._usage_snapshot = usage
        self._preparation_status = "ready"
        self._adopt_herdr_capture(capture=self._capture_herdr_restore(), reasoning_commit=True)
        self._publish_herdr_snapshot()

    @asynccontextmanager
    async def _startup_reporting_scope(self) -> AsyncIterator[None]:
        """Track startup work and clear only its captured preparation requirement."""
        attention = self._operator_attention
        config = self._config
        token = self._begin_reporting_operation()
        try:
            yield
            if self._preparation_status == "ready" and attention is not None:
                if attention.reason == "Model preparation required":
                    self.clear_operator_attention(token=attention.token)
        except Exception:
            if self._config is config and self._operator_attention is attention:
                self.set_operator_attention(reason="Model preparation required")
            raise
        finally:
            self._refresh_final_reporting_usage()
            self._end_reporting_operation(token=token)

    @classmethod
    async def prepare(cls, *, config: SessionConfigDAO) -> "SloAgentSession":
        """Prepare configured routes before constructing a strict runtime session.

        WHAT: Captures one catalog generation through the existing preparation
            seam, then constructs the lazy session from that exact snapshot.
        WHO: Headless and programmatic dynamic-route callers use this gateway.
        WHEN: Before inference; construction itself remains network-free.

        Args:
            config (SessionConfigDAO): Resolved direct route or configured pool.

        Returns:
            SloAgentSession: Session initialized from the prepared generation.

        Raises:
            ModelPreparationRequiredError: A configured route remains unavailable.
        """
        model_names: tuple[str, ...] = cls._configured_model_names(config=config)
        snapshot: ModelCatalogSnapshotDAO = await ModelCatalogService.prepare_models(model_names=model_names)
        return cls.build(config=config, catalog_snapshot=snapshot)

    @staticmethod
    def _configured_model_names(*, config: SessionConfigDAO) -> tuple[str, ...]:
        """Return every exact configured route requiring one admission decision.

        WHAT: Projects the direct selection or ordered pool without rereading
            defaults or environment configuration.
        WHO: ``prepare`` calls this before the catalog gateway.
        WHEN: Once for each explicit async session preparation.

        Args:
            config (SessionConfigDAO): Session selection and optional pool.

        Returns:
            tuple[str, ...]: Direct configured name or all ordered pool names.
        """
        if config.model_pool_dao is not None:
            return tuple(entry.model_name for entry in config.model_pool_dao.entries)
        if config.model_name is not None:
            return (config.model_name,)
        return (str(cfg("DEFAULT_MODEL_NAME")),)

    @staticmethod
    def _require_prepared_openrouter_route(
        *,
        config: SessionConfigDAO,
        snapshot: Optional[ModelCatalogSnapshotDAO],
    ) -> None:
        """Reject a direct qualified route that lacks prepared snapshot evidence.

        WHAT: Prevents synchronous session initialization from resolving unknown
            OpenRouter reasoning/usage or reaching a lazy factory.
        WHO: ``build`` calls this before constructing a configured session.
        WHEN: Only at strict construction; injected prebuilt agents bypass it.

        Args:
            config (SessionConfigDAO): Requested model selection.
            snapshot (Optional[ModelCatalogSnapshotDAO]): Candidate prepared view.

        Raises:
            ModelPreparationRequiredError: A qualified route is missing or invalid.
        """
        model_names: tuple[str, ...] = SloAgentSession._configured_model_names(config=config)
        if not any(model_name.startswith("openrouter:") for model_name in model_names):
            return
        if snapshot is None:
            raise ModelPreparationRequiredError("Catalog preparation required for OpenRouter routes.")
        for model_name in model_names:
            if not model_name.startswith("openrouter:"):
                continue
            try:
                entry = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
                ModelCatalogService._validate_admission(entry=entry, now=datetime.now(tz=timezone.utc))
            except ValueError as error:
                raise ModelPreparationRequiredError(
                    f"Catalog preparation required for '{model_name}'; refresh OpenRouter models."
                ) from error

    async def hydrate_transcript_entries(self) -> list["TranscriptEntryDAO"]:
        """Load replay transcript entries for the session (sub-spec 05.e; feature 15).

        Returns:
            list[TranscriptEntryDAO]: Completed transcript entries in order,
                or empty when history is disabled or the session has no
                canonical events.
        """
        if not self._enable_history or self._history_store is None:
            return []
        if not await self._history_store.session_exists(session_id=self._session_id):
            return []
        events = await self._history_store.load_events(session_id=self._session_id)
        return ReplayEntryProjector.build_entries(events=events)

    def _build_agent(self) -> SloAgent:
        """Construct the ``SloAgent`` from the stored config.

        Threads ``session_id`` through so the ChatGPT-backend Responses
        lane (feature 07) can attribute prompt-cache hits per session.

        When ``config.extra_tools`` is non-empty, merges those tools into the
        standard extended bundle so orchestrator sessions carry the
        ``spawn_sub_agents`` tool alongside the default 9-tool set.
        """
        if self._config is None:
            raise RuntimeError("SloAgentSession has no config to build a SloAgent from.")
        resolved_workspace_file: Optional[Path] = self._resolve_workspace_file_for_agent()
        extra_tools: list[BaseTool] = list(self._config.extra_tools or [])
        plugin_tools: list[BaseTool] = self._plugin_registry.all_tools() if self._plugin_registry else []
        extension_tools: list[BaseTool] = extra_tools + plugin_tools
        all_tools: list[BaseTool] | None = (
            create_extended_tools() + extension_tools if extension_tools else None
        )
        return SloAgent(
            model_name=self.active_model_name,
            model_pool_dao=self._config.model_pool_dao,
            reasoning_level=self.active_reasoning_level,
            system_prompt=self._config.system_prompt,
            should_stop_after_turn_hook=self._config.resolved_stop_hook(),
            cwd=str(self._config.workdir),
            workspace_file=resolved_workspace_file,
            session_id=self._session_id,
            tools=all_tools,
            append_system_prompt=self._config.append_system_prompt,
            plugin_dispatcher=self._plugin_dispatcher,
            snapshot=self.catalog_snapshot,
        )

    def _load_plugins(self) -> None:
        """Load registered plugins and merge their safe contributions.

        WHAT: Builds the loader, registry, and dispatcher once for this session.
        WHO: The session constructor calls it before the first agent prompt.
        WHEN: During session construction and after an explicit plugin reload.
        """
        from src.agents.slo_agent.plugins.loader import PluginLoader

        trust_store = PluginTrustStore(store_path=self._plugin_loader_kwargs.get("trust_store_path"))
        managed_root: Path = self._plugin_loader_kwargs.get(
            "managed_root", Path.home() / ".slo" / "plugins" / "plugins"
        )
        status_map: dict[str, str] = {}
        result = PluginLoader.load(
            managed_root=managed_root,
            project_dir=self._workdir,
            trust_store=trust_store,
            cli_paths=self._plugin_paths,
            status_setter=lambda key, text: self._set_plugin_status(
                status_map=status_map,
                key=key,
                text=text,
            ),
        )
        builtin_tools: frozenset[str] = frozenset(tool.name for tool in create_extended_tools())
        registry = PluginRegistry(registrations=result.registrations, builtin_tool_names=builtin_tools)
        registry.merge_all()
        dispatcher = PluginDispatcher(registry=registry)
        for key, text in status_map.items():
            dispatcher.set_status(key=key, text=text)
        for registration in registry.registrations():
            for handler in registration.before_tool_call_handlers:
                dispatcher.register_before_tool_call_handler(owner=registration.plugin_id, handler=handler)
            for handler in registration.after_tool_result_handlers:
                dispatcher.register_after_tool_result_handler(owner=registration.plugin_id, handler=handler)
            for handler in registration.before_agent_turn_handlers:
                dispatcher.register_before_agent_turn_handler(owner=registration.plugin_id, handler=handler)
        self._plugin_trust_store = trust_store
        self._plugin_registry = registry
        self._plugin_dispatcher = dispatcher
        from src.tui.event_renderer import EventRenderer

        EventRenderer.set_renderer_overrides(renderers=registry.all_renderers())
        self._register_plugin_slash_commands(registry=registry)

    def _register_plugin_slash_commands(self, *, registry: "PluginRegistry") -> None:
        """Register accepted plugin commands through the one TUI metadata owner.

        Args:
            registry (PluginRegistry): Merged plugin contributions in load order.
        """
        from src.tui.slash_command_registry import SlashCommandSpecDAO
        from src.tui.slash_router import SlashRouter

        for command_name in list(registry.all_commands()):
            try:
                SlashRouter.registry().register(
                    command=SlashCommandSpecDAO(
                        name=command_name,
                        description="plugin command",
                        argument_mode="free_text",
                        usage=f"/{command_name} [arguments]",
                        display_order=500,
                    )
                )
            except ValueError as exc:
                registration = self._plugin_registration_owning_command(
                    registry=registry,
                    command_name=command_name,
                )
                if registration is not None:
                    registration.commands.pop(command_name, None)
                    registry.remove_command(name=command_name)
                    registration.health.load_error = (
                        str(exc)
                        if registration.health.load_error is None
                        else f"{registration.health.load_error}; {exc}"
                    )

    @staticmethod
    def _plugin_registration_owning_command(
        *,
        registry: "PluginRegistry",
        command_name: str,
    ) -> PluginRegistrationDAO | None:
        """Find the registration that declared one command token.

        Args:
            registry (PluginRegistry): Loaded plugin registrations.
            command_name (str): Canonical plugin command token.

        Returns:
            PluginRegistrationDAO | None: Registration that declared the command, when present.
        """
        for registration in registry.registrations():
            if command_name in registration.commands:
                return registration
        return None

    def plugin_command_handler(self, *, command_name: str) -> Callable[..., Any] | None:
        """Return one accepted plugin command handler for the TUI router.

        Args:
            command_name (str): Canonical slash token resolved by the registry.

        Returns:
            Callable[..., Any] | None: Plugin callback when accepted, otherwise ``None``.
        """
        if self._plugin_registry is None:
            return None
        return self._plugin_registry.all_commands().get(command_name)

    @staticmethod
    def _set_plugin_status(*, status_map: dict[str, str], key: str, text: str) -> None:
        """Update the load-time status seed without coupling PluginAPI to the TUI.

        Args:
            status_map (dict[str, str]): Session-owned temporary load-time map.
            key (str): Plugin-derived status key.
            text (str): Status text, or empty text to clear it.
        """
        if text:
            status_map[key] = text
            return
        status_map.pop(key, None)

    def plugin_status_map(self) -> dict[str, str]:
        """Return the current dispatcher-owned plugin footer statuses.

        Returns:
            dict[str, str]: Plugin status entries keyed by stable derived key.
        """
        if self._plugin_dispatcher is None:
            return {}
        return self._plugin_dispatcher.status_map()

    def _build_runtime_context(self) -> SloRuntimeContext:
        """Build the session-owned, live runtime context.

        WHAT: Binds read-only accessors to current session state.
        WHO: Plugins and introspection tools receive this public context seam.
        WHEN: The session constructs its extension and introspection surfaces.
        """
        history_root: Path = self._history_root_for_runtime_context()
        return SloRuntimeContext(
            session_id=self._session_id,
            workdir=self._workdir,
            history_root=history_root,
            live_fleet=lambda: [],
            usage_snapshot=self.usage_snapshot,
            loaded_skills=lambda: [],
            tool_names=self._runtime_tool_names,
        )

    def _history_root_for_runtime_context(self) -> Path:
        """Resolve an injected history store's root without relaxing its contract.

        WHAT: Uses a concrete ``Path`` root when an injected store exposes one;
        otherwise falls back to the session workdir for read-only runtime context.
        WHO: ``_build_runtime_context`` calls it during session construction.
        WHEN: Tests or alternate integrations provide protocol-compatible stores.

        Returns:
            Path: Resolved history root or the session workdir fallback.
        """
        if self._history_store is None:
            return self._workdir
        candidate: object = getattr(self._history_store, "root", self._workdir)
        if isinstance(candidate, Path):
            return candidate.resolve()
        return self._workdir

    def _runtime_tool_names(self) -> list[str]:
        """Return the visible tool names in the active agent bundle.

        WHAT: Projects the live tool bundle to its public names.
        WHO: Runtime context and plugin integration checks call it.
        WHEN: A consumer needs a current read-only tool inventory.
        """
        built_tools: list[BaseTool] = (
            self._agent.tools if self._agent is not None else create_extended_tools()
        )
        plugin_tools: list[BaseTool] = self._plugin_registry.all_tools() if self._plugin_registry else []
        return [tool.name for tool in built_tools + plugin_tools]

    def plugin_health_reports(self) -> list[PluginHealthDAO]:
        """Return health records for every discovered plugin.

        WHAT: Exposes the registry's operator-visible plugin health view.
        WHO: The `/plugins` command and integration tests call it.
        WHEN: After session construction or a plugin reload.
        """
        if self._plugin_registry is None:
            return []
        return self._plugin_registry.health_reports()

    async def reload_plugins(self) -> None:
        """Reload plugins from their configured discovery tiers.

        WHAT: Replaces registrations after an operator requests `/plugins reload`.
        WHO: The slash-command router calls it.
        WHEN: After plugin source files or trust decisions change.
        """
        self._load_plugins()

    async def trust_project_plugins(self) -> None:
        """Trust this session's project then refresh its plugin registrations.

        WHAT: Records project trust before loading local plugin source.
        WHO: The `/plugins trust` command calls it.
        WHEN: An operator explicitly authorizes the current workdir.
        """
        if self._plugin_trust_store is None:
            return
        self._plugin_trust_store.trust(project_dir=self._workdir)
        self._load_plugins()

    def _resolve_workspace_file_for_agent(self) -> Optional[Path]:
        """Return the workspace file to use for the lazy-built agent.

        Prefers the explicit config value from the current invocation. When
        resuming a persisted session without an explicit workspace file,
        falls back to the value stored in ``session.json`` so workspace
        context survives across restarts.

        Returns:
            Optional[Path]: Resolved workspace file path, or ``None`` when no
                workspace file should be used.
        """
        if self._config is None:
            return None
        if self._config.workspace_file is not None:
            return self._config.workspace_file
        if not self._enable_history or self._history_store is None:
            return None
        session_json = self._history_store.root / self._session_id / "session.json"
        if not session_json.exists():
            return None
        try:
            metadata: SessionHistoryMetadataDAO = SessionHistoryMetadataDAO.model_validate(
                json.loads(session_json.read_text(encoding="utf-8"))
            )
        except (FileNotFoundError, ValueError):
            return None
        return metadata.workspace_file

    def _seed_active_reasoning_level(
        self,
        *,
        config: Optional[SessionConfigDAO],
    ) -> ReasoningLevel:
        """Resolve the initial active reasoning level for this session.

        Args:
            config (Optional[SessionConfigDAO]): Optional build-time
                config that may carry a startup override.

        Returns:
            ReasoningLevel: Seeded canonical reasoning level.
        """
        if self._preparation_status != "ready":
            return config.reasoning_level or "off" if config is not None else "off"
        if config is not None and config.reasoning_level is not None:
            return clamp_reasoning_level(
                model_name=self.active_model_name,
                requested_level=config.reasoning_level,
                snapshot=self.catalog_snapshot,
            )
        return default_reasoning_level_for_model(
            model_name=self.active_model_name, snapshot=self.catalog_snapshot
        )

    def _build_usage_snapshot(
        self,
        *,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
        reasoning_level: Optional[ReasoningLevel] = None,
    ) -> SessionUsageSnapshotDAO:
        """Build the current TUI-facing usage snapshot.

        Reads the **routed** model name (the pool member currently active, or the
        configured name when single-model / not yet built) so usage, reasoning,
        defaults, and the rate policy all track the model that actually ran.

        Args:
            snapshot (Optional[ModelCatalogSnapshotDAO]): Candidate startup view;
                defaults to the current admitted view.
            reasoning_level (Optional[ReasoningLevel]): Candidate clamped level;
                defaults to the active level.

        Returns:
            SessionUsageSnapshotDAO: Current runtime usage snapshot.
        """
        if self._preparation_status != "ready" and snapshot is None:
            return SessionUsageSnapshotDAO(
                active_model_name=self.active_model_name,
                active_reasoning_level=self.active_reasoning_level,
            )
        snapshot = snapshot or self.catalog_snapshot
        reasoning_level = reasoning_level or self.active_reasoning_level
        routed_model_name: str = self._resolve_active_model_name() or self.active_model_name
        resolved_reasoning = resolve_reasoning_config(
            model_name=routed_model_name,
            requested_level=reasoning_level,
            snapshot=snapshot,
        )
        model_defaults: dict[str, object] = dict(
            defaults_for_model(model_name=routed_model_name, snapshot=snapshot)
            if snapshot is not None
            else MODEL_DEFAULTS.get(routed_model_name, {})
        )
        policy: ModelRateLimitPolicyDAO = policy_for_model(model_name=routed_model_name, snapshot=snapshot)
        latest_turn: TokenUsageTotalsDAO = self._latest_turn_usage_totals()
        return SessionUsageSnapshotDAO(
            active_model_name=routed_model_name,
            active_reasoning_level=reasoning_level,
            provider_effort=resolved_reasoning.provider_effort,
            provider_budget_tokens=resolved_reasoning.provider_budget_tokens,
            output_cap_tokens=int_or_none(value=model_defaults.get("max_tokens")),
            requests_per_minute_limit=policy.requests_per_minute,
            tokens_per_minute_limit=policy.tokens_per_minute,
            cooldown_seconds_remaining=self._cooldown_seconds_remaining,
            latest_turn=latest_turn,
            session_totals=self._session_usage_totals,
            usage_available=self._usage_is_available(latest_turn=latest_turn),
            context_window_snapshot=self._context_window_snapshot_for_model(
                routed_model_name=routed_model_name,
            ),
        )

    def _context_window_snapshot_for_model(
        self,
        *,
        routed_model_name: str,
    ) -> Optional[ContextWindowSnapshotDAO]:
        """Return the cached snapshot only when it matches the routed model.

        Args:
            routed_model_name (str): Current routed model identity.

        Returns:
            Optional[ContextWindowSnapshotDAO]: Matching snapshot, if any.
        """
        if self._context_window_snapshot is None:
            return None
        routed_identity: str = ContextWindowSnapshotService.resolve_model_identity(
            model_name=routed_model_name,
            snapshot=self.catalog_snapshot,
        )
        if self._context_window_snapshot.model_name != routed_identity:
            return None
        return self._context_window_snapshot

    @staticmethod
    def _usage_is_available(*, latest_turn: TokenUsageTotalsDAO) -> bool:
        """Return True when the latest turn has real token counts.

        Args:
            latest_turn (TokenUsageTotalsDAO): Latest completed-turn totals.

        Returns:
            bool: True when any provider-supplied token count is known.
        """
        return any(
            value is not None
            for value in (
                latest_turn.input_tokens,
                latest_turn.output_tokens,
                latest_turn.total_tokens,
            )
        )

    def _sync_usage_snapshot_commit(self) -> None:
        """Drain completed usage once, including updates with no public event."""
        if self._agent is None:
            return
        self._session_usage_totals = self._session_usage_totals.add(
            other=self._agent.consume_completed_usage(),
        )

    def _rebuild_usage_snapshot(self) -> SessionUsageSnapshotDAO:
        """Recompute and store the session usage snapshot.

        Returns:
            SessionUsageSnapshotDAO: Freshly rebuilt usage snapshot.
        """
        self._usage_snapshot = self._build_usage_snapshot()
        self._publish_herdr_snapshot()
        return self._usage_snapshot

    def _latest_turn_usage_totals(self) -> TokenUsageTotalsDAO:
        """Return the latest captured turn usage without forcing agent build.

        Returns:
            TokenUsageTotalsDAO: Latest captured usage totals, or empty totals.
        """
        if self._agent is None:
            return TokenUsageTotalsDAO()
        return self._agent.last_usage_totals

    def _estimated_request_tokens(
        self,
        *,
        text: str,
        message_history: Sequence[BaseMessage] = (),
    ) -> int:
        """Return the history-aware local token estimate for the next attempt.

        Counts the replayed ``message_history`` (including tool outputs) in
        addition to the new prompt, so a resumed session's true request size —
        dominated by replayed history — drives the preflight wait (spec 36/37).

        Args:
            text (str): User prompt text.
            message_history (Sequence[BaseMessage]): Replayed history for this
                turn. Defaults to empty (single-shot prompts).

        Returns:
            int: Conservative request-window token estimate including history.
        """
        resolved_reasoning = resolve_reasoning_config(
            model_name=self._resolve_active_model_name() or self.active_model_name,
            requested_level=self.active_reasoning_level,
        )
        # Use a realistic per-turn output estimate, NOT the model's hard ceiling
        # (``MODEL_DEFAULTS[...]["max_tokens"]`` is 64K/128K after spec 02). Feeding
        # the ceiling here would make the local TPM estimator assume every turn emits
        # the full cap and inject artificial waits during normal tool turns.
        return estimate_request_tokens(
            prompt_text=text,
            message_history=message_history,
            output_cap_tokens=_RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS,
            reasoning_budget_tokens=resolved_reasoning.provider_budget_tokens,
        )

    def _prune_rate_window(self, *, now_seconds: float) -> None:
        """Drop request-window entries older than sixty seconds.

        Args:
            now_seconds (float): Current monotonic timestamp.
        """
        cutoff: float = now_seconds - 60.0
        while self._recent_request_times and self._recent_request_times[0] <= cutoff:
            self._recent_request_times.popleft()
        while self._recent_request_token_estimates and self._recent_request_token_estimates[0][0] <= cutoff:
            self._recent_request_token_estimates.popleft()

    def _preflight_wait_seconds(
        self,
        *,
        policy: ModelRateLimitPolicyDAO,
        now_seconds: float,
    ) -> int:
        """Return the advisory local RPM wait before the next attempt.

        Args:
            policy (ModelRateLimitPolicyDAO): Active model policy.
            now_seconds (float): Current monotonic timestamp.

        Returns:
            int: Seconds to wait before attempting the provider call.
        """
        self._prune_rate_window(now_seconds=now_seconds)
        return self._request_window_wait_seconds(
            policy=policy,
            now_seconds=now_seconds,
        )

    def _request_window_wait_seconds(
        self,
        *,
        policy: ModelRateLimitPolicyDAO,
        now_seconds: float,
    ) -> int:
        """Return the local RPM wait for the next attempt.

        Args:
            policy (ModelRateLimitPolicyDAO): Active model policy.
            now_seconds (float): Current monotonic timestamp.

        Returns:
            int: Seconds to wait for request-window capacity.
        """
        if policy.requests_per_minute is None:
            return 0
        if len(self._recent_request_times) < policy.requests_per_minute:
            return 0
        oldest_request_seconds: float = self._recent_request_times[0]
        return max(1, round((oldest_request_seconds + 60.0) - now_seconds))

    def _record_request_attempt(self, *, estimated_tokens: int, now_seconds: float) -> None:
        """Record one local request-window attempt.

        Args:
            estimated_tokens (int): Estimated token pressure for the attempt.
            now_seconds (float): Current monotonic timestamp.
        """
        self._recent_request_times.append(now_seconds)
        self._recent_request_token_estimates.append((now_seconds, estimated_tokens))

    def _set_retry_cooldown(self, *, wait_seconds: int) -> None:
        """Store cooldown state for the usage status surface.

        Args:
            wait_seconds (int): Seconds remaining until the next attempt.
        """
        self._cooldown_until = time.monotonic() + wait_seconds
        self._cooldown_seconds_remaining = wait_seconds
        self._rebuild_usage_snapshot()

    def _clear_retry_cooldown(self) -> None:
        """Clear any active retry cooldown state."""
        self._cooldown_until = None
        self._cooldown_seconds_remaining = None
        self._rebuild_usage_snapshot()

    def _cooldown_wait_seconds(self) -> int:
        """Return the active retry cooldown remaining in whole seconds.

        Returns:
            int: Remaining wait, or ``0`` when there is no active cooldown.
        """
        if self._cooldown_until is None:
            return 0
        remaining_seconds: float = self._cooldown_until - time.monotonic()
        if remaining_seconds <= 0:
            return 0
        return max(1, round(remaining_seconds))

    # ---- Public surface ---------------------------------------------------

    @property
    def catalog_snapshot(self) -> Optional[ModelCatalogSnapshotDAO]:
        """Return the session's prepared catalog generation without exposing mutation.

        Returns:
            Optional[ModelCatalogSnapshotDAO]: Prepared session generation, if any.
        """
        return self._admitted_run_snapshot or self._catalog_snapshot

    @property
    def agent(self) -> SloAgent:
        """Return the underlying ``SloAgent``, building it on first access."""
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    @property
    def active_model_name(self) -> str:
        """Return the current active model name for this session.

        Returns:
            str: Active model name for title rendering and lazy agent builds.

        Raises:
            RuntimeError: If the session has no active model configured.
        """
        if not self._active_model_name:
            raise RuntimeError("SloAgentSession has no active model configured.")
        return self._active_model_name

    def _resolve_active_model_name(self) -> str:
        """Return the name of the model the pool is currently routing to.

        Falls back to ``_active_model_name`` when no pool is in use or when
        the session's agent is not yet built. Uses duck typing
        (``hasattr(llm, "active_model_name")``) to detect a ``ModelPool``
        without importing that class into session.py.

        Returns:
            str: The active model name — pool-routed or static.
        """
        if self._agent is not None and self._agent.llm is not None:
            injected_llm = self._agent.llm
            if hasattr(injected_llm, "active_model_name"):
                return injected_llm.active_model_name  # type: ignore[attr-defined]
        return self._active_model_name or ""

    @property
    def active_reasoning_level(self) -> ReasoningLevel:
        """Return the current active reasoning level for this session.

        Returns:
            ReasoningLevel: Active canonical reasoning level used for
                title rendering and lazy agent builds.
        """
        return self._active_reasoning_level

    @property
    def workdir(self) -> Path:
        """The resolved absolute workdir. Read-only."""
        return self._workdir

    @property
    def model_pool_dao(self) -> Optional["ModelPoolDAO"]:
        """The configured model pool, or ``None`` for a single-model session.

        Read-only. Exposed so ``/new`` can carry the pool configuration into a
        replacement session without reaching into private config state.

        Returns:
            Optional[ModelPoolDAO]: The session's configured pool, or ``None``.
        """
        return self._config.model_pool_dao if self._config is not None else None

    @property
    def routed_model_name(self) -> str:
        """The model the pool is currently routing to (truthful identity).

        Read-only. For a pooled session this follows route switches; for a
        single-model session it equals the configured name. Title/status surfaces
        read this so they never lie about which model actually ran. Falls back to
        the configured name before the agent is built.

        Returns:
            str: The routed model name (or the configured name when no pool /
                not yet built).
        """
        return self._resolve_active_model_name() or self.active_model_name

    @property
    def session_id(self) -> str:
        """The per-process session identifier. Read-only."""
        return self._session_id

    @property
    def is_running(self) -> bool:
        """True while ``invoke`` is in flight."""
        return self._is_running

    @property
    def history_store(self) -> Optional[SessionHistoryStoreProtocol]:
        """The active history store (or ``None`` when history is disabled)."""
        return self._history_store

    @property
    def history_projector(self) -> SessionHistoryProjector:
        """The active history projector."""
        return self._history_projector

    @property
    def history_root(self) -> Optional[Path]:
        """Return the configured history root when history is enabled.

        Returns:
            Optional[Path]: Resolved history root, or ``None`` when history is disabled.
        """
        if self._history_store is None:
            return None
        return self._history_store.root

    @property
    def history_enabled(self) -> bool:
        """Return whether persisted history is enabled for this session.

        Returns:
            bool: True when canonical on-disk history is enabled.
        """
        return self._enable_history

    @property
    def startup_fallback_notice(self) -> Optional[str]:
        """Return the operator-visible fallback notice, if any.

        Returns:
            Optional[str]: Notice text when the requested model was invalid,
                otherwise ``None``.
        """
        return self._startup_fallback_notice

    @property
    def session_name(self) -> Optional[str]:
        """Return the active persisted session name when present.

        Returns:
            Optional[str]: Human-readable session name, or ``None`` when unnamed.
        """
        if not self._enable_history or self._history_store is None:
            return None
        session_json = self._history_store.root / self._session_id / "session.json"
        try:
            metadata: SessionHistoryMetadataDAO = SessionHistoryMetadataDAO.model_validate(
                json.loads(session_json.read_text(encoding="utf-8"))
            )
        except (FileNotFoundError, ValueError):
            return None
        return metadata.session_name

    def usage_snapshot(self) -> SessionUsageSnapshotDAO:
        """Return the current session-owned usage snapshot.

        Returns:
            SessionUsageSnapshotDAO: Deep-copied usage snapshot for the TUI.
        """
        return self._usage_snapshot.model_copy(deep=True)

    def refresh_usage_snapshot(self) -> SessionUsageSnapshotDAO:
        """Recompute and return the session-owned usage snapshot.

        Returns:
            SessionUsageSnapshotDAO: Fresh usage snapshot.
        """
        self._sync_usage_snapshot_commit()
        return self._rebuild_usage_snapshot().model_copy(deep=True)

    async def context_window_snapshot(self) -> ContextWindowSnapshotDAO:
        """Measure the active Context Window Snapshot without mutating history.

        Returns:
            ContextWindowSnapshotDAO: Capacity and durable replay estimate when readable.
        """
        model_name: str = self.routed_model_name
        events: Optional[list[SessionHistoryEventDAO]] = await self._existing_history_events()
        if events is None:
            return ContextWindowSnapshotService.without_history(
                model_name=model_name, snapshot=self.catalog_snapshot
            )
        return ContextWindowSnapshotService.build(
            events=events, model_name=model_name, snapshot=self.catalog_snapshot
        )

    async def refresh_context_window_snapshot(self) -> SessionUsageSnapshotDAO:
        """Cache a newly measured Context Window Snapshot for the footer.

        Returns:
            SessionUsageSnapshotDAO: Republished usage snapshot with the cached value.
        """
        if self._preparation_status != "ready":
            return self._rebuild_usage_snapshot().model_copy(deep=True)
        self._context_window_snapshot = await self.context_window_snapshot()
        await self._maybe_emit_compaction_advisory(snapshot=self._context_window_snapshot)
        self._sync_usage_snapshot_commit()
        return self._rebuild_usage_snapshot().model_copy(deep=True)

    @staticmethod
    def _compaction_advisory_threshold_tokens() -> int:
        """Return the positive advisory threshold or the 256k default.

        Called by ``_maybe_emit_compaction_advisory`` at each snapshot boundary.

        Returns:
            int: Resolved ``SLO_COMPACTION_ADVISORY_TOKENS`` or the default.
        """
        return positive_int_env(
            primary_name="SLO_COMPACTION_ADVISORY_TOKENS",
            default=_COMPACTION_ADVISORY_DEFAULT_TOKENS,
        )

    async def _maybe_emit_compaction_advisory(
        self,
        *,
        snapshot: ContextWindowSnapshotDAO,
    ) -> None:
        """Emit one latency advisory while the available snapshot is above threshold.

        Called by ``refresh_context_window_snapshot`` at each snapshot boundary.
        An unavailable estimate neither emits nor changes the armed state, and a
        below-threshold available snapshot re-arms the one-shot advisory. This method
        never compacts.

        Args:
            snapshot (ContextWindowSnapshotDAO): Freshly measured snapshot.
        """
        threshold_tokens: int = self._compaction_advisory_threshold_tokens()
        if not snapshot.estimate_available:
            return
        if snapshot.estimated_used_tokens < threshold_tokens:
            self._compaction_advisory_armed = True
            return
        if not self._compaction_advisory_armed:
            return
        self._compaction_advisory_armed = False
        await self._dispatch_event(
            event=AgentStreamEventDAO(
                kind="compaction_advised",
                content=f"Context is above {threshold_tokens:,} tokens; run /compact to help latency.",
                metadata={"estimated_used_tokens": snapshot.estimated_used_tokens},
            )
        )

    async def _existing_history_events(self) -> Optional[list[SessionHistoryEventDAO]]:
        """Read history without creating a session or mutating durable state.

        Returns:
            Optional[list[SessionHistoryEventDAO]]: Events, or ``None`` when unavailable.
        """
        if not self._enable_history or self._history_store is None:
            return None
        if not await self._history_store.session_exists(session_id=self._session_id):
            return None
        try:
            return await self._history_store.load_events(session_id=self._session_id)
        except (OSError, ValueError) as exc:
            log_error(
                msg="context_window_history_load_failed",
                session_id=self._session_id[:8],
                error=str(exc),
            )
            return None

    async def compact_context(self) -> ManualCompactionResultDAO:
        """Perform one lock-safe Manual Compaction while the session is idle.

        Returns:
            ManualCompactionResultDAO: Operator-safe terminal result.
        """
        if self._lock.locked():
            return ManualCompactionResultDAO(
                status="unavailable",
                detail="cannot compact while a prompt is in flight; run /abort first",
            )
        token = None
        try:
            async with self._lock:
                token = self._begin_reporting_operation()
                result: ManualCompactionResultDAO = await self._compact_context_locked()
                if result.status == "failed":
                    self.set_operator_attention(reason="Run failed; review Slo")
            return await self._with_refreshed_context_window(result=result)
        except Exception:
            self.set_operator_attention(reason="Run failed; review Slo")
            raise
        finally:
            if token is not None:
                self._refresh_final_reporting_usage()
                self._end_reporting_operation(token=token)

    async def _compact_context_locked(self) -> ManualCompactionResultDAO:
        """Validate history and run Manual Compaction under the session lock.

        Returns:
            ManualCompactionResultDAO: Result before its post-operation snapshot.
        """
        events, history_result = await self._read_manual_compaction_history()
        if history_result is not None:
            return history_result
        if not events or not Compacter.has_viable_cut_point(events=events):
            return ManualCompactionResultDAO(status="nothing_to_compact")
        await self._ensure_history_session()
        readiness_result: Optional[ManualCompactionResultDAO] = (
            await self._ensure_manual_compaction_agent_ready()
        )
        if readiness_result is not None:
            return readiness_result
        return await self._run_manual_compaction(events=events)

    async def _read_manual_compaction_history(
        self,
    ) -> tuple[Optional[list[SessionHistoryEventDAO]], Optional[ManualCompactionResultDAO]]:
        """Read viable Manual Compaction input once with typed guard outcomes.

        Returns:
            tuple[Optional[list[SessionHistoryEventDAO]], Optional[ManualCompactionResultDAO]]:
                Loaded events or the terminal guard result.
        """
        if not self._enable_history or self._history_store is None:
            return None, ManualCompactionResultDAO(
                status="unavailable",
                detail="session history is disabled; there is nothing to compact",
            )
        if not await self._history_store.session_exists(session_id=self._session_id):
            return None, ManualCompactionResultDAO(status="nothing_to_compact")
        try:
            events: list[SessionHistoryEventDAO] = await self._history_store.load_events(
                session_id=self._session_id,
            )
        except (OSError, ValueError):
            return None, ManualCompactionResultDAO(
                status="unavailable",
                detail="session history is unavailable; try again after repairing the session",
            )
        return events, None

    async def _ensure_manual_compaction_agent_ready(self) -> Optional[ManualCompactionResultDAO]:
        """Ensure an LLM exists before emitting Manual Compaction lifecycle events.

        Returns:
            Optional[ManualCompactionResultDAO]: Unavailable result or ``None``.
        """
        try:
            await self._ensure_agent_ready()
        except Exception as exc:  # noqa: BLE001
            log_error(msg="manual_compaction_agent_not_ready", error=str(exc))
            return self._manual_compaction_model_unavailable()
        if self._agent is not None and self._agent.llm is not None:
            return None
        return self._manual_compaction_model_unavailable()

    @staticmethod
    def _manual_compaction_model_unavailable() -> ManualCompactionResultDAO:
        """Build the exact unavailable result for an unready model.

        Returns:
            ManualCompactionResultDAO: Stable model-readiness detail.
        """
        return ManualCompactionResultDAO(
            status="unavailable",
            detail="the model is not ready; compaction needs an active model",
        )

    async def _run_manual_compaction(
        self,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> ManualCompactionResultDAO:
        """Run the shared forced compaction pipeline after all guards pass.

        Args:
            events (list[SessionHistoryEventDAO]): Validated events handed to the pipeline.

        Returns:
            ManualCompactionResultDAO: ``compacted`` or ``failed`` result.
        """
        turn_id: str = self._allocate_turn_id()
        await self._emit_compaction_event(kind="compaction_started")
        try:
            await self._run_compaction_if_needed(turn_id=turn_id, force=True, events=events)
        except Exception as exc:  # noqa: BLE001
            log_error(
                msg="manual_compaction_failed",
                error_class=type(exc).__name__,
                stack_trace=False,
            )
            detail: str = await self._report_compaction_failure(turn_id=turn_id, error=exc)
            return ManualCompactionResultDAO(status="failed", detail=detail)
        await self._emit_compaction_event(kind="compaction_completed")
        return ManualCompactionResultDAO(status="compacted")

    @classmethod
    def _safe_compaction_failure_message(cls, *, error: BaseException) -> str:
        """Return bounded redacted text safe for a result, event, and history audit.

        Called by ``_report_compaction_failure`` and
        ``_persist_compaction_failure_audit`` for every manual or overflow
        compaction failure. The exception message is passed through the local
        ordered redaction rules, whitespace is collapsed, and the result is
        truncated to ``_COMPACTION_FAILURE_MESSAGE_LIMIT`` characters. When
        nothing readable remains, the exception class name is returned.

        Args:
            error (BaseException): Raw exception raised by the compaction pipeline.

        Returns:
            str: Deterministic single-line redacted message.
        """
        redacted: str = str(error)
        for pattern, replacement in _COMPACTION_REDACTION_RULES:
            redacted = pattern.sub(replacement, redacted)
        collapsed: str = re.sub(r"\s+", " ", redacted).strip()
        if not collapsed:
            return type(error).__name__
        return collapsed[:_COMPACTION_FAILURE_MESSAGE_LIMIT]

    @classmethod
    def _compaction_failure_text(cls, *, error: BaseException) -> str:
        """Return the operator-facing exception class and redacted message.

        Called by ``_report_compaction_failure`` so the manual result detail,
        live stream event, and durable audit all share the same actionable
        text.

        Args:
            error (BaseException): Raw compaction exception.

        Returns:
            str: ``"<ExceptionClass>: <safe message>"``.
        """
        return f"{type(error).__name__}: {cls._safe_compaction_failure_message(error=error)}"

    def _compaction_failure_metadata(
        self,
        *,
        error: BaseException,
        safe_message: str,
    ) -> dict[str, object]:
        """Build the safe metadata bag shared by the event and history audit.

        Called by ``_report_compaction_failure`` and
        ``_persist_compaction_failure_audit``. Only redacted facts are copied:
        the failure scope, exception class, safe message, and the optionally
        available provider name and HTTP status. Raw exception text, headers,
        and request payloads are never included.

        Args:
            error (BaseException): Raw compaction exception.
            safe_message (str): Redacted message from
                ``_safe_compaction_failure_message``.

        Returns:
            dict[str, object]: Bounded safe metadata.
        """
        provider: Optional[ProviderName] = self._resolve_active_provider()
        signal: Optional[ProviderErrorSignalDAO] = self._inspect_provider_error(error=error)
        return {
            "failure_scope": "compaction",
            "error_class": type(error).__name__,
            "safe_message": safe_message,
            "provider_name": provider.value if provider is not None else None,
            "status_code": signal.status_code if signal is not None else None,
        }

    async def _persist_compaction_failure_audit(
        self,
        *,
        turn_id: str,
        error: BaseException,
    ) -> None:
        """Best-effort append one replay-excluded existing-kind failure audit.

        Called by ``_report_compaction_failure`` before the live event is
        dispatched. It reuses the existing ``run_failed`` history kind with
        ``metadata["failure_scope"] == "compaction"``; ``run_failed`` is already
        excluded from model replay. A persistence error is swallowed and logged
        by exception class only so the live event and manual result still reach
        the operator.

        Args:
            turn_id (str): Turn anchoring the audit — the allocated manual turn
                or the failed overflow attempt's turn.
            error (BaseException): Raw compaction exception.
        """
        safe_message: str = self._safe_compaction_failure_message(error=error)
        try:
            await self._append_history_event(
                event=self._build_event(
                    kind="run_failed",
                    turn_id=turn_id,
                    payload=SessionHistoryEventPayloadDAO(
                        error_message=safe_message,
                        model_name=self._resolve_active_model_name(),
                        metadata=self._compaction_failure_metadata(
                            error=error,
                            safe_message=safe_message,
                        ),
                    ),
                ),
            )
        except Exception as persist_exc:  # noqa: BLE001
            log_error(
                msg="compaction_failure_audit_failed",
                error_class=type(persist_exc).__name__,
                stack_trace=False,
            )

    async def _report_compaction_failure(
        self,
        *,
        turn_id: str,
        error: BaseException,
    ) -> str:
        """Persist and emit redacted data for one manual or overflow failure.

        Called by the manual ``/compact`` exception branch and the forced
        overflow compaction exception branch. It produces the safe text and
        metadata once, appends the best-effort scoped ``run_failed`` audit, then
        dispatches the existing ``compaction_failed`` stream event with the same
        content and metadata.

        Args:
            turn_id (str): Turn anchoring the durable audit.
            error (BaseException): Raw compaction exception.

        Returns:
            str: Safe ``"<ExceptionClass>: <safe message>"`` for the manual
                result detail.
        """
        safe_message: str = self._safe_compaction_failure_message(error=error)
        text: str = self._compaction_failure_text(error=error)
        await self._persist_compaction_failure_audit(turn_id=turn_id, error=error)
        await self._emit_compaction_event(
            kind="compaction_failed",
            content=text,
            metadata=self._compaction_failure_metadata(error=error, safe_message=safe_message),
        )
        return text

    async def _with_refreshed_context_window(
        self,
        *,
        result: ManualCompactionResultDAO,
    ) -> ManualCompactionResultDAO:
        """Attach a best-effort post-operation Context Window Snapshot.

        Args:
            result (ManualCompactionResultDAO): Terminal operation result.

        Returns:
            ManualCompactionResultDAO: Result enriched with a snapshot when available.
        """
        try:
            await self.refresh_context_window_snapshot()
        except Exception as exc:  # noqa: BLE001
            log_error(msg="context_window_refresh_failed", error=str(exc))
            return result
        return result.model_copy(update={"context_window_snapshot": self._context_window_snapshot})

    async def should_show_startup_notice(self) -> bool:
        """Tell the mounted TUI whether to show the existing startup block.

        New sessions show the block once. A launch carrying a model fallback
        notice shows it again, even on resume, so the explanation is visible
        and the following tip names the model actually used.

        Returns:
            bool: True for a fallback launch or a session without a startup marker.
        """
        if self._startup_fallback_notice:
            return True
        if not self._enable_history or self._history_store is None:
            return not self._startup_notice_shown_in_memory
        if not await self._history_store.session_exists(session_id=self._session_id):
            return True
        metadata = await self._history_store.read_metadata(session_id=self._session_id)
        return metadata.startup_notice_shown_at is None

    async def mark_startup_notice_shown(self) -> None:
        """Persist that the startup notice has been rendered once."""
        if not self._enable_history or self._history_store is None:
            self._startup_notice_shown_in_memory = True
            return
        await self._ensure_history_session()
        metadata = await self._history_store.read_metadata(session_id=self._session_id)
        now_utc: datetime = datetime.now(timezone.utc)
        metadata.startup_notice_shown_at = metadata.startup_notice_shown_at or now_utc
        metadata.updated_at = now_utc
        await self._history_store.write_metadata(metadata=metadata)

    async def rename_session(self, *, session_name: str) -> SessionHistoryMetadataDAO:
        """Persist a human-readable session name for the active session.

        Args:
            session_name (str): Requested session name.

        Returns:
            SessionHistoryMetadataDAO: Persisted updated metadata.

        Raises:
            RuntimeError: When history is disabled for this session.
            ValueError: When the name is blank or conflicts with another session.
        """
        if not self._enable_history or self._history_store is None:
            raise RuntimeError("Cannot rename a session when history is disabled.")
        await self._ensure_history_session()
        metadata = await self._history_store.rename_session(
            session_id=self._session_id,
            session_name=session_name,
        )
        self._publish_herdr_snapshot()
        return metadata

    async def record_workflow_update(
        self,
        *,
        text: str,
        message_id: str,
        workflow_id: str,
    ) -> bool:
        """Persist one workflow note as a synthetic completed turn (spec 57.a.4).

        Invoked by the TUI's ``context_note`` inbox branch after rendering the
        transcript line. The event is appended with a fresh ``turn_id`` and no
        run envelope — terminal by construction — so
        ``SessionHistoryProjector`` includes it in model context in true
        chronological position. Idempotent on ``message_id``: a note that is
        already recorded (inbox re-delivery after a crash-before-ack) is
        skipped.

        Args:
            text (str): The full note text (already formatted by the notifier).
            message_id (str): Originating inbox message id — the idempotency key.
            workflow_id (str): Owning workflow, recorded in the event payload.

        Returns:
            bool: ``True`` when a new event was persisted, ``False`` on a
                duplicate ``message_id`` or when history is disabled.
        """
        if not self._enable_history or self._history_store is None:
            return False
        await self._ensure_history_session()
        seen_message_ids: set[str] = await self._seen_workflow_message_ids()
        if message_id in seen_message_ids:
            return False
        event: SessionHistoryEventDAO = SessionHistoryEventDAO(
            session_id=self._session_id,
            turn_id=str(uuid4()),
            kind="workflow_update",
            payload=SessionHistoryEventPayloadDAO(
                content=text,
                metadata={
                    "workflow_id": workflow_id,
                    "inbox_message_id": message_id,
                },
            ),
        )
        await self._history_store.append_event(event=event)
        seen_message_ids.add(message_id)
        return True

    async def _seen_workflow_message_ids(self) -> set[str]:
        """Return the persisted workflow inbox message ids, seeding the cache once.

        Scans the event log for ``workflow_update`` events on first use and
        caches their ``inbox_message_id`` payload values in memory — the set is
        small (one entry per delivered phase note).

        Returns:
            set[str]: Mutable cache of already-recorded inbox message ids.
        """
        if self._workflow_message_ids_seen is not None:
            return self._workflow_message_ids_seen
        if self._history_store is None:
            self._workflow_message_ids_seen = set()
            return self._workflow_message_ids_seen
        events: list[SessionHistoryEventDAO] = await self._history_store.load_events(
            session_id=self._session_id,
        )
        self._workflow_message_ids_seen = {
            str(event.payload.metadata["inbox_message_id"])
            for event in events
            if event.kind == "workflow_update" and event.payload.metadata.get("inbox_message_id")
        }
        return self._workflow_message_ids_seen

    def subscribe(self, *, handler: AgentEventSubscriber) -> None:
        """Register an async event handler."""
        self._subscribers.append(handler)

    def unsubscribe(self, *, handler: AgentEventSubscriber) -> None:
        """Remove a previously-registered handler. No-op if absent."""
        try:
            self._subscribers.remove(handler)
        except ValueError:
            pass

    @property
    def event_relay(self) -> AgentEventSubscriber:
        """Return a relay callable matching the ``AgentEventSubscriber`` contract.

        ``SubAgentPool`` and ``SubAgentProcess`` call the relay with the
        ``AgentStreamEventDAO`` as a single **positional** argument, matching
        the ``Callable[[AgentStreamEventDAO], Awaitable[None]]`` type alias.
        ``_dispatch_event`` uses a keyword-only ``event`` parameter (``*, event``),
        so returning ``self._dispatch_event`` directly would raise
        ``TypeError: _dispatch_event() takes 1 positional argument but 2 were given``
        the moment the pool invokes ``await relay(tagged_event)``.

        This wrapper bridges the two calling conventions without changing the
        internal ``_dispatch_event`` signature.

        Returns:
            AgentEventSubscriber: Coroutine that accepts one positional
                ``AgentStreamEventDAO`` and dispatches it to all subscribers.
        """

        async def _positional_relay(event: AgentStreamEventDAO) -> None:
            """Forward ``event`` to ``_dispatch_event`` using its keyword signature.

            Args:
                event (AgentStreamEventDAO): The event to dispatch.
            """
            await self._dispatch_event(event=event)

        return _positional_relay

    def _begin_standard_orchestrator_attachment(self) -> bool:
        """Permit only pristine configured policy before ordinary bootstrap."""
        config = self._config
        return (
            config is not None
            and self._herdr_pristine_origin
            and not self._herdr_policy_invalidated
            and not self._agent_is_injected
            and (
                config.system_prompt is None
                and config.append_system_prompt is None
                and not config.extra_tools
                and config.should_stop_after_turn_hook is None
            )
        )

    def _finish_standard_orchestrator_attachment(
        self, *, permitted: bool, expected_tools: tuple[BaseTool, ...] = ()
    ) -> None:
        """Verify final standard additions before granting process-local provenance.

        Args:
            permitted (bool): Unchanged pristine source verdict from bootstrap.
            expected_tools (tuple[BaseTool, ...]): Exact tools built by bootstrap.
        """
        if not permitted or not self._matches_standard_orchestrator_additions(tools=expected_tools):
            self._withdraw_stale_herdr_capture()
            self._publish_herdr_snapshot()
            return
        assert self._config is not None  # Established by the final additions guard.
        self._standard_orchestrator_attachment = HerdrOrchestratorProvenanceDAO(
            tools=tuple(self._config.extra_tools or ()),
            system_prompt=self._config.system_prompt,
            append_system_prompt=self._config.append_system_prompt,
        )
        self._adopt_herdr_capture(capture=self._capture_herdr_restore())
        self._publish_herdr_snapshot()

    def _matches_standard_orchestrator_additions(self, *, tools: tuple[BaseTool, ...]) -> bool:
        """Check the construction result, not arbitrary final values, before attestation."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        )

        config = self._config
        if config is None or not tools or not isinstance(config.extra_tools, list):
            return False
        return (
            len(config.extra_tools) == len(tools)
            and all(actual is expected for actual, expected in zip(config.extra_tools, tools))
            and config.system_prompt == DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
            and config.append_system_prompt == ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM
            and config.should_stop_after_turn_hook is None
        )

    @property
    def workflow_visualizer_destination(self) -> HerdrDestination:
        """Return captured destination without allowing failed authority to fall back."""
        if self._herdr_destination == "herdr" and self._herdr_reporter.destination != "herdr":
            return "unavailable"
        return self._herdr_destination

    async def open_editor(self, *, argv: tuple[str, ...]) -> VisualizerLaunchOutcomeDAO:
        """Submit an editor only through this session's retained reporter authority.

        Args:
            argv: Validated editor executable, option terminator and absolute file.

        Returns:
            Safe submission evidence, never a fallback or process-readiness claim.
        """
        editor = self._herdr_editor
        if self._herdr_closing or self.workflow_visualizer_destination != "herdr" or editor is None:
            return VisualizerLaunchOutcomeDAO(status="failed")
        return await editor.invoke(argv=argv)

    async def open_workflow_visualizer(self, *, parent_session_id: str) -> VisualizerLaunchOutcomeDAO:
        """Submit a saved workflow parent to this session's existing pane owner.

        Args:
            parent_session_id (str): Exact canonical workflow parent, not the TUI owner.

        Returns:
            VisualizerLaunchOutcomeDAO: Fixed skipped result when eligibility is absent.

        Raises:
            asyncio.CancelledError: After the retained eligibility reads finish;
                cancellation never reaches pane submission.
        """
        viewer = self._herdr_visualizer
        if not is_canonical_uuid_session_id(value=parent_session_id) or not self._may_open_workflow_viewer():
            return VisualizerLaunchOutcomeDAO(status="skipped")
        task = asyncio.create_task(
            coro=self._workflow_parent_is_persisted(parent_session_id=parent_session_id)
        )
        cancelled = await HerdrTaskJoin.wait(task=task)
        try:
            eligible = task.result()
        except Exception:
            eligible = False
        if cancelled:
            raise asyncio.CancelledError
        if not eligible or not self._may_open_workflow_viewer() or viewer is not self._herdr_visualizer:
            return VisualizerLaunchOutcomeDAO(status="skipped")
        assert viewer is not None and self._history_store is not None
        return await viewer.invoke(
            request=HerdrVisualizerRequestDAO(
                parent_session_id=parent_session_id,
                history_root=self._history_store.root,
            )
        )

    def _may_open_workflow_viewer(self) -> bool:
        """Recheck session eligibility and live reporter authority after awaited reads."""
        self._withdraw_stale_herdr_capture()
        return (
            not self._herdr_closing
            and self._herdr_capture is not None
            and self._herdr_visualizer is not None
            and self.workflow_visualizer_destination == "herdr"
            and isinstance(self._herdr_reporter, HerdrReporter)
            and self._herdr_reporter.allows_viewer_admission()
        )

    async def _workflow_parent_is_persisted(self, *, parent_session_id: str) -> bool:
        """Read existing parent evidence only; private context never leaves this boundary."""
        assert self._history_store is not None
        current_default = await asyncio.to_thread(default_history_root)
        if await asyncio.to_thread(self._history_store.root.resolve) != current_default:
            return False
        metadata = await self._history_store.read_metadata(session_id=parent_session_id)
        if metadata.session_id != parent_session_id:
            return False
        if await asyncio.to_thread(metadata.workdir.resolve) != self._herdr_workdir:
            return False
        if not await asyncio.to_thread(shutil.which, cmd="slo"):
            return False
        context = await asyncio.to_thread(
            OrchestratorContextReader.load,
            history_root=self._history_store.root,
            parent_session_id=parent_session_id,
        )
        if context is None:
            events = await self._history_store.load_events(session_id=parent_session_id)
            if not any(
                event.session_id == parent_session_id and event.kind == "sub_agent_spawned"
                for event in events
            ):
                return False
        # Recheck the default after all evidence awaits; activation's root is not authority.
        return current_default == await asyncio.to_thread(default_history_root)

    async def start_external_reporting(self, *, interactive: bool = False) -> None:
        """Activate the optional Herdr reporter exactly once and join it.

        WHAT: Starts one session-owned activation task on the first eligible
            activating call, then waits for it. Later calls join the same
            retained task; activation is never duplicated. Disabled calls
            (``_herdr_closing``, suppressed via ``suppress_external_reporting``,
            or an inactive environment — ``HERDR_ENV != "1"`` or
            ``SLO_HERDR_DISABLED`` truthy) allocate nothing, do zero I/O, and
            do not pin the interactive mode; only the first call that actually
            creates the activation task records ``interactive``. Successful
            activation can publish the Herdr snapshot inside the activation
            task before its waiter returns. An ordinary (non-cancelled) failed
            activation returns with its partial owner retained: the
            destination becomes ``unavailable`` and close uncertainty is
            marked, but no close task is created and ``reporter.close`` is not
            called here. Joining a failed activation is not closing it —
            cleanup of the retained owner belongs to a later lifecycle
            finalizer (``close_external_reporting`` and, when resources remain
            retained, ``finish_retired_reporting_cleanup``). Only a cancelled
            waiter joins the activation and then runs the close gateway before
            the cancellation escapes.
        WHO: ``SloTUI._finish_replacement_runtime`` (``interactive=True``) and
            ``HeadlessRunner`` (default non-interactive) call it after delivery
            initialization.
        WHEN: Once per mounted/adopted session, after the session's own
            runtime/delivery setup and before any publication.

        Args:
            interactive (bool, optional): Whether native restore may be eligible.
                Only the first eligible activating call's value is recorded;
                disabled calls record nothing and later calls joining the
                existing task cannot change the mode. Defaults to False.

        Raises:
            asyncio.CancelledError: Propagated only after the activation task
                has been joined; the cancelled waiter then closes reporting via
                ``close_external_reporting`` so cleanup still runs to
                completion before the cancellation escapes. The retained
                activation task itself is never cancelled from outside.
        """
        if self._herdr_closing or self._herdr_suppressed:
            return
        if self._herdr_start_task is None and self._herdr_environment_is_inactive():
            return
        if self._herdr_start_task is None:
            self._herdr_interactive = interactive
            self._herdr_start_task = asyncio.create_task(coro=self._start_herdr_once())
        cancelled = await HerdrTaskJoin.wait(task=self._herdr_start_task)
        self._herdr_start_task.result()
        if cancelled:
            await self.close_external_reporting()
            raise asyncio.CancelledError

    @staticmethod
    def _herdr_environment_is_inactive() -> bool:
        """Refuse disabled/outside activation before allocating an async task."""
        return os.environ.get("HERDR_ENV") != "1" or os.environ.get(
            "SLO_HERDR_DISABLED", ""
        ).strip().lower() in ("1", "true", "yes", "on")

    async def _start_herdr_once(self) -> None:
        """Retain partial assembly before starting any adapter-owned work."""
        try:
            self._herdr_reporter = await self._prepare_herdr_reporter()
            if self._herdr_closing:
                self._herdr_reporter.revoke_viewer_admission()
                return
            await self._herdr_reporter.start()
            if not self._herdr_closing:
                self._herdr_destination = self._herdr_reporter.destination
                if self._herdr_destination == "herdr":
                    self._herdr_visualizer = self._herdr_reporter.build_visualizer()
                    if isinstance(self._herdr_reporter, HerdrReporter):
                        self._herdr_editor = self._herdr_reporter.build_editor()
                    self._herdr_reporting_started = True
                    self._publish_herdr_snapshot()
        except (Exception, asyncio.CancelledError):
            # This retained task is never publicly cancelled; an inner cancellation
            # is an activation defect. The partial owner stays retained; closing
            # it belongs to the later close gateway, not to this failure path.
            self._herdr_close_uncertain = True
            self._herdr_destination = "unavailable"
            self._log_herdr_publication_failure()

    def _log_herdr_publication_failure(self) -> None:
        """Delegate fixed diagnostics without making the sink mandatory."""
        try:
            self._herdr_reporter.record_publication_failure()
        except Exception:
            pass

    def set_operator_attention(self, *, reason: OperatorAttentionReason) -> int:
        """Publish a fixed human-action requirement and return its completion token.

        WHAT: Replaces any current attention with a new session-owned record
            and republishes the Herdr snapshot. Attention is process-local
            observation state only; it never becomes a history event and never
            controls execution.
        WHO: Session gateways that require human intervention (for example
            model-preparation gating in ``invoke``).
        WHEN: Synchronously at the moment the blocking condition is detected.

        Args:
            reason (OperatorAttentionReason): One of the fixed literal reasons
                ("Authentication required", "Model preparation required",
                "Run failed; review Slo", "Approval required").

        Returns:
            int: A new session-owned attention serial token. Only this exact
                token completes this attention via ``clear_operator_attention``;
                tokens are never reused within a session.
        """
        attention = OperatorAttentionDAO(token=self._attention_serial + 1, reason=reason)
        self._attention_serial = attention.token
        self._operator_attention = attention
        self._publish_herdr_snapshot()
        return attention.token

    def clear_operator_attention(self, *, token: int) -> None:
        """Clear only the requesting owner's matching attention, never a newer one.

        WHAT: Matching-completion-only semantics: the current attention is
            cleared only when ``token`` equals the token returned by the
            ``set_operator_attention`` call that created it. A stale or unknown
            token is a silent no-op, so a late completion can never clear a
            newer owner's attention. Clearing also drops any suspended
            reporting operation and republishes the Herdr snapshot.
        WHO: The session gateway that resolved the blocking condition (for
            example ``_startup_reporting_scope`` after preparation succeeds).
        WHEN: Synchronously when the human-action requirement no longer holds.

        Args:
            token (int): Completion token previously returned by
                ``set_operator_attention`` for this exact attention record.
        """
        if self._operator_attention is None or self._operator_attention.token != token:
            return
        self._operator_attention = None
        self._suspended_reporting_operation = None
        self._publish_herdr_snapshot()

    def _begin_reporting_operation(self) -> int:
        """Observe admitted work until its owner retires the returned token in finally."""
        self._operation_serial += 1
        self._reporting_operations.add(self._operation_serial)
        self._publish_herdr_snapshot()
        return self._operation_serial

    def _end_reporting_operation(self, *, token: int) -> None:
        """Retire this owner only, after its final usage has been committed."""
        self._reporting_operations.discard(token)
        if self._suspended_reporting_operation == token:
            self._suspended_reporting_operation = None
        self._publish_herdr_snapshot()

    def _suspend_reporting_operation(self, *, token: int) -> None:
        """Observe an actual human wait only for an active owner with attention."""
        if token not in self._reporting_operations or self._operator_attention is None:
            return
        self._suspended_reporting_operation = token
        self._publish_herdr_snapshot()

    def _reporting_state(self) -> SessionReportingStateDAO:
        """Project unsuspended work before fixed attention, without execution authority."""
        if self._reporting_operations - {self._suspended_reporting_operation}:
            return SessionReportingStateDAO(state="working")
        if self._operator_attention is not None:
            return SessionReportingStateDAO(state="blocked", block_reason=self._operator_attention.reason)
        return SessionReportingStateDAO(state="idle")

    def _publish_herdr_snapshot(self) -> None:
        """Pair current public facts with committed private capture without I/O."""
        if not self._herdr_reporting_started or self._herdr_closing:
            return
        try:
            self._withdraw_stale_herdr_capture()
            state = self._reporting_state()
            self._herdr_reporter.publish(
                publication=HerdrPublicationDAO(
                    configuration_generation=self._herdr_configuration_generation,
                    snapshot=HerdrSnapshotProjector.build(
                        session_id=self._session_id,
                        state=state.state,
                        block_reason=state.block_reason,
                        history_enabled=self._enable_history,
                        usage=self._usage_snapshot,
                        metadata_profile=self._herdr_metadata_profile,
                    ),
                    restore_capture=self._herdr_capture,
                )
            )
        except Exception:
            self._log_herdr_publication_failure()

    def suppress_external_reporting(self) -> None:
        """Permanently refuse successor reporting before activation.

        Raises:
            RuntimeError: Activation was already requested; its owner is retained.
        """
        if self._herdr_start_task is not None:
            raise RuntimeError("Reporting activation already requested")
        self._herdr_suppressed = True
        self._herdr_destination = "unavailable"

    def begin_external_reporting_close(self) -> None:
        """Synchronously revoke optional authority without cancelling execution."""
        if self._herdr_closing:
            return
        self._herdr_closing = True
        self._herdr_reporting_started = False
        try:
            self._herdr_reporter.revoke_viewer_admission()
        except (Exception, asyncio.CancelledError):
            self._herdr_close_uncertain = True

    async def close_external_reporting(self) -> HerdrReporterCloseOutcomeDAO:
        """Revoke reporting authority, drain every current owner, and join cleanup.

        WHAT: Synchronously revokes viewer admission via
            ``begin_external_reporting_close``, then runs one retained close
            task that joins the activation task, drains the viewer, and closes
            reporter and transport — each gateway attempted independently, with
            failures retained as sticky uncertainty rather than skipped. The
            outcome carries two independent dimensions: ``replacement``
            (whether a successor reporter may safely be adopted; remote or
            defect uncertainty is sticky and survives even a fully drained
            local close) and ``resources`` (final local disposal evidence;
            an intermediate reporter gateway's default of drained is not
            disposal permission — a throwing final gateway can never inherit
            drained evidence). A completed close is cached: repeated calls
            join the same retained task and return the same outcome, never
            re-running cleanup. Caller cancellation waits for the retained
            cleanup to finish before propagating (join-before-cancel).
        WHO: ``SloTUI`` shutdown/replacement, ``HeadlessRunner``'s outer
            finalizer, ``dispose_unmounted_session``, the cancellation path of
            ``start_external_reporting``, and the internal
            ``_finish_herdr_cleanup_once``.
        WHEN: At session close, replacement commit, candidate disposal, or
            caller cancellation after activation joined.

        Returns:
            HerdrReporterCloseOutcomeDAO: Independent remote/local evidence.
                Any final-drain caller (``SloTUI._finish_shutdown_owner``,
                ``HeadlessRunner._close_external_reporting``) that observes
                ``resources=retained`` must keep the session owner strongly
                retained and finish through
                ``finish_retired_reporting_cleanup`` instead of dropping it.

        Raises:
            asyncio.CancelledError: Propagated only after the retained close
                task has been joined, never instead of cleanup.
        """
        self.begin_external_reporting_close()
        if self._herdr_close_task is None:
            self._herdr_close_task = asyncio.create_task(coro=self._close_herdr_once())
        cancelled = await HerdrTaskJoin.wait(task=self._herdr_close_task)
        outcome = self._herdr_close_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _close_herdr_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Drain all current owners despite ordinary optional cleanup failures."""
        if self._herdr_start_task is not None:
            await HerdrTaskJoin.wait(task=self._herdr_start_task)
            try:
                self._herdr_start_task.result()
            except (Exception, asyncio.CancelledError):
                # Inner task cancellation is defective activation, not caller cancellation.
                self._herdr_close_uncertain = True
        if self._herdr_editor is not None:
            try:
                await self._herdr_editor.close()
            except (Exception, asyncio.CancelledError):
                self._herdr_viewer_drain_failed = True
                self._herdr_close_uncertain = True
        if self._herdr_visualizer is not None:
            try:
                await self._herdr_visualizer.close()
            except (Exception, asyncio.CancelledError):
                self._herdr_viewer_drain_failed = True
                self._herdr_close_uncertain = True
        final_resources_retained = True
        for cleanup in (self._herdr_reporter.close, self._herdr_reporter.close_transport):
            # Each gateway must supply its own evidence. In particular, a throwing
            # final gateway cannot inherit the intermediate default of drained.
            final_resources_retained = True
            try:
                outcome = await cleanup()
                final_resources_retained = outcome.resources == "retained"
                # Remote/defect uncertainty survives even a successful final local drain.
                self._herdr_close_uncertain |= outcome.replacement == "uncertain"
            except (Exception, asyncio.CancelledError):
                self._herdr_close_uncertain = True
        try:
            retained = (
                self._herdr_viewer_drain_failed
                or final_resources_retained
                or self._herdr_reporter.retains_external_resources
            )
        except (Exception, asyncio.CancelledError):
            retained = True
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain" if retained or self._herdr_close_uncertain else "safe",
            resources="retained" if retained else "drained",
        )

    async def dispose_unmounted_session(self) -> None:
        """Dispose an inactive failed candidate, never a mounted or running session.

        The caller owns the unmounted-candidate precondition. History and detached
        workflows are preserved; only this session's attached pool is drained.

        Raises:
            asyncio.CancelledError: After reporting and candidate pool cleanup join.
        """
        try:
            await self.close_external_reporting()
        finally:
            try:
                await self._drain_unmounted_pool()
            finally:
                await self.finish_retired_reporting_cleanup()

    async def _drain_unmounted_pool(self) -> None:
        """Retain and join the candidate's existing pool drain exactly once."""
        if self._sub_agent_pool is None:
            return
        if self._candidate_pool_cleanup_task is None:
            self._candidate_pool_cleanup_task = asyncio.create_task(
                coro=self._sub_agent_pool.abort_and_drain()
            )
        cancelled = await HerdrTaskJoin.wait(task=self._candidate_pool_cleanup_task)
        try:
            self._candidate_pool_cleanup_task.result()
        except Exception:
            self._log_herdr_publication_failure()
        if cancelled:
            raise asyncio.CancelledError

    async def finish_retired_reporting_cleanup(self) -> HerdrReporterCloseOutcomeDAO:
        """Finish local ownership before a final caller may drop this session.

        Persistent retained resources intentionally leave this gateway pending;
        caller cancellation cannot abandon its single retained cleanup task.

        Returns:
            HerdrReporterCloseOutcomeDAO: Drained evidence with sticky uncertainty.

        Raises:
            asyncio.CancelledError: After cleanup finishes, never instead of cleanup.
        """
        self.begin_external_reporting_close()
        if self._herdr_finish_cleanup_task is None:
            self._herdr_finish_cleanup_task = asyncio.create_task(coro=self._finish_herdr_cleanup_once())
        cancelled = await HerdrTaskJoin.wait(task=self._herdr_finish_cleanup_task)
        outcome = self._herdr_finish_cleanup_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _finish_herdr_cleanup_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Allow one final local attempt, never polling or retrying remote withdrawal."""
        outcome = await self.close_external_reporting()
        if outcome.resources == "drained":
            return outcome
        outcome = await self.drain_retained_external_resources()
        if outcome.resources == "retained":
            await asyncio.Future()
        return outcome

    async def drain_retained_external_resources(self) -> HerdrReporterCloseOutcomeDAO:
        """Join one local-only final drain after close, preserving remote uncertainty.

        Returns:
            HerdrReporterCloseOutcomeDAO: Cached evidence, never remote release proof.

        Raises:
            RuntimeError: Close has not completed.
            asyncio.CancelledError: Only after the retained local attempt completes.
        """
        if self._herdr_close_task is None or not self._herdr_close_task.done():
            raise RuntimeError("Reporting close must complete before final drain")
        if self._herdr_retired_drain_task is None:
            self._herdr_retired_drain_task = asyncio.create_task(coro=self._drain_retired_herdr_once())
        cancelled = await HerdrTaskJoin.wait(task=self._herdr_retired_drain_task)
        outcome = self._herdr_retired_drain_task.result()
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def _drain_retired_herdr_once(self) -> HerdrReporterCloseOutcomeDAO:
        """Retain ownership on local drain or evidence failure without remote retry."""
        try:
            outcome = await self._herdr_reporter.drain_retained_external_resources()
            retained = (
                self._herdr_viewer_drain_failed
                or outcome.resources == "retained"
                or self._herdr_reporter.retains_external_resources
            )
        except (Exception, asyncio.CancelledError):
            retained = True
        return HerdrReporterCloseOutcomeDAO(
            replacement="uncertain", resources="retained" if retained else "drained"
        )

    async def _prepare_herdr_reporter(self) -> HerdrReporterProtocol:
        """Classify before private input I/O, then assemble inert enabled owners.

        Returns:
            HerdrReporterProtocol: Retained adapter or an allocation-free null owner.
        """
        environment = dict(os.environ)
        state_root = Path(environment.get("SLO_HOME") or str(Path.home() / ".slo")) / "integrations" / "herdr"
        gate = HerdrEnvironmentGate.build(environment=environment, state_root=state_root)
        if not isinstance(gate, HerdrReporterConfigDAO):
            return gate
        if not is_canonical_uuid_session_id(value=self._session_id):
            return NullHerdrReporter(destination="unavailable")
        self._herdr_metadata_profile = gate.metadata_profile
        await self._prepare_herdr_capture_inputs(interactive=self._herdr_interactive)
        await asyncio.to_thread(self._prepare_herdr_parent, state_root=state_root)
        return HerdrReporter.build(environment=environment, state_root=state_root)

    @staticmethod
    def _prepare_herdr_parent(*, state_root: Path) -> None:
        """Prepare only the integration parent beneath the private configured home."""
        HerdrFileLease.validate(path=state_root.parent.parent, directory=True)
        state_root.parent.mkdir(mode=0o700, exist_ok=True)
        HerdrFileLease.validate(path=state_root.parent, directory=True)

    async def _prepare_herdr_capture_inputs(self, *, interactive: bool) -> None:
        """Establish private activation facts without creating history.

        Called only after enabled-environment admission by the lifetime owner.
        Ordinary failures deny restore; cancellation remains owned by the caller.

        Args:
            interactive (bool): Whether the activating process is interactive.
        """
        self._herdr_interactive = interactive
        self._herdr_default_history = False
        if not interactive or self._agent_is_injected or not self._enable_history:
            self._adopt_herdr_capture(capture=None)
            return
        try:
            await asyncio.to_thread(self._resolve_herdr_capture_paths)
            if self._history_store is not None:
                metadata = await self._history_store.read_metadata(session_id=self._session_id)
                self._herdr_history_persisted = metadata.session_id == self._session_id
                if self._config is not None and self._config.workspace_file is None:
                    self._herdr_workspace_file = (
                        await asyncio.to_thread(metadata.workspace_file.resolve)
                        if metadata.workspace_file is not None
                        else None
                    )
        except FileNotFoundError:
            self._herdr_history_persisted = False
        except Exception:
            self._herdr_default_history = False
        self._adopt_herdr_capture(capture=self._capture_herdr_restore())

    def _resolve_herdr_capture_paths(self) -> None:
        """Resolve activation paths off-loop; never called from an event callback."""
        if self._history_store is None or self._config is None:
            return
        self._herdr_path_sources = self._herdr_current_path_sources()
        self._herdr_workdir = self._workdir.resolve()
        self._herdr_plugin_paths = tuple(path.resolve() for path in self._plugin_paths)
        self._herdr_default_history = self._history_store.root.resolve() == default_history_root().resolve()
        self._herdr_workspace_file = (
            self._config.workspace_file.resolve() if self._config.workspace_file is not None else None
        )

    def _herdr_current_path_sources(self) -> tuple[object, ...]:
        """Copy lexical inputs to detect unsupported mutation without filesystem I/O."""
        config = self._config
        return (
            self._workdir,
            tuple(self._plugin_paths),
            self._history_store.root if self._history_store is not None else None,
            config.workdir if config is not None else None,
            config.workspace_file if config is not None else None,
            config.history_root if config is not None else None,
            tuple(config.plugin_paths) if config is not None else (),
        )

    def _adopt_herdr_capture(
        self,
        *,
        capture: Optional[HerdrRestoreCaptureDAO],
        model_selection: bool = False,
        reasoning_commit: bool = False,
    ) -> None:
        """Advance only exact configuration/eligibility identity, never display usage.

        Args:
            capture (Optional[HerdrRestoreCaptureDAO]): Committed policy or ineligibility.
        """
        try:
            sources = self._herdr_current_policy_sources()
            previous = self._herdr_policy_sources
            unchanged = previous is None or (
                sources is not None
                and sources.permits_commit(
                    previous=previous, model_selection=model_selection, reasoning_commit=reasoning_commit
                )
            )
            if unchanged:
                self._herdr_policy_sources = sources
            else:
                self._herdr_policy_invalidated = True
                capture = None
        except (ValueError, TypeError, AttributeError):
            self._herdr_policy_invalidated = True
            capture = None
        if self._herdr_policy_invalidated:
            capture = None
        if capture == self._herdr_capture and self._session_id == self._herdr_capture_session_id:
            return
        self._herdr_configuration_generation += 1
        self._herdr_capture = capture
        self._herdr_capture_session_id = self._session_id

    def _herdr_policy_sources_match(self, *, expected: Optional[HerdrPolicySourcesDAO]) -> bool:
        """Fail closed at bootstrap boundaries without changing ordinary attachment results."""
        try:
            return self._herdr_current_policy_sources() == expected
        except Exception:
            self._herdr_policy_invalidated = True
            return False

    def _snapshot_herdr_policy_sources(self) -> Optional[HerdrPolicySourcesDAO]:
        """Refuse malformed optional policy without interrupting ordinary construction.

        Construction and bootstrap use this memory-only boundary. A refused snapshot
        invalidates restore eligibility; it never substitutes a trusted empty policy.
        """
        try:
            return self._herdr_current_policy_sources()
        except Exception:
            self._herdr_policy_invalidated = True
            return None

    def _herdr_current_policy_sources(self) -> Optional[HerdrPolicySourcesDAO]:
        """Copy lexical/scalar policy at commit for memory-only mutation detection."""
        config = self._config
        if config is None:
            return None
        # Validate raw field values, not model_dump coercions or trusted model instances.
        # The existing config contract remains the authority; this copy never mutates it.
        SessionConfigDAO.model_validate(dict(config.__dict__), strict=True)
        return HerdrPolicySourcesDAO(
            model_name=config.model_name,
            configured_reasoning=config.reasoning_level,
            history_enabled=config.enable_history,
            effective_reasoning=self._active_reasoning_level,
            paths=self._herdr_current_path_sources(),
            pool=self._capture_herdr_pool(pool=config.model_pool_dao),
        )

    def _withdraw_stale_herdr_capture(self) -> None:
        """Revoke unsupported mutation on publication; never recapture it as committed."""
        if self._herdr_policy_invalidated and self._herdr_capture is None:
            return
        if self._herdr_capture is None:
            try:
                if self._herdr_policy_sources != self._herdr_current_policy_sources():
                    self._herdr_policy_invalidated = True
            except (ValueError, TypeError, AttributeError):
                self._herdr_policy_invalidated = True
            return
        try:
            current = (
                self._session_id == self._herdr_capture_session_id
                and self._herdr_capture_eligible()
                and self._herdr_policy_sources == self._herdr_current_policy_sources()
            )
        except (ValueError, TypeError, AttributeError):
            current = False
        if not current:
            self._herdr_policy_invalidated = True
            self._herdr_configuration_generation += 1
            self._herdr_capture = None

    def _herdr_capture_eligible(self) -> bool:
        """Use established activation and persistence facts without filesystem work."""
        return (
            self._herdr_interactive
            and not self._herdr_policy_invalidated
            and not self._agent_is_injected
            and self._enable_history
            and self._config is not None
            and self._config.enable_history is True
            and (self._history_session_ensured or self._herdr_history_persisted)
            and self._herdr_default_history
            and self._herdr_path_sources == self._herdr_current_path_sources()
            and is_canonical_uuid_session_id(value=self._session_id)
            and self._herdr_policy_is_reproducible()
        )

    def _capture_herdr_restore(self) -> Optional[HerdrRestoreCaptureDAO]:
        """Copy exact configured policy into private immutable data, or refuse it.

        Returns:
            Optional[HerdrRestoreCaptureDAO]: Memory-only policy, never an event payload.
        """
        if not self._herdr_capture_eligible():
            return None
        assert self._config is not None
        try:
            return HerdrRestoreCaptureDAO(
                config=HerdrRestoreConfigDAO(
                    session_id=self._session_id,
                    model_name=self.active_model_name,
                    model_pool_dao=self._capture_herdr_pool(pool=self._config.model_pool_dao),
                    reasoning_level=self._active_reasoning_level,
                    workdir=self._herdr_workdir,
                    workspace_file=self._herdr_workspace_file,
                    plugin_paths=self._herdr_plugin_paths,
                )
            )
        except (ValueError, TypeError, AttributeError):
            return None

    @classmethod
    def _capture_herdr_pool(cls, *, pool: Optional[ModelPoolDAO] = None) -> Optional[HerdrRestorePoolDAO]:
        """Copy ordered configured scalars, revalidating mutable source policy.

        Args:
            pool (Optional[ModelPoolDAO]): Configured policy, never runtime cooldowns.

        Returns:
            Optional[HerdrRestorePoolDAO]: Independent frozen policy or None.

        Raises:
            ValueError: The mutable policy no longer satisfies its validators.
        """
        if pool is None:
            return None
        ModelPoolDAO.model_validate(dict(pool.__dict__), strict=True)
        entries = tuple(cls._capture_herdr_pool_entry(entry=entry) for entry in pool.entries)
        return HerdrRestorePoolDAO(entries=entries)

    @classmethod
    def _capture_herdr_pool_entry(cls, *, entry: ModelPoolEntryDAO) -> HerdrRestorePoolEntryDAO:
        """Validate and freeze all five configured scalars without retaining aliases.

        Args:
            entry (ModelPoolEntryDAO): Potentially mutated configured entry.

        Returns:
            HerdrRestorePoolEntryDAO: Strict immutable scalar copy.

        Raises:
            ValueError: Scalar types or provider ownership are invalid.
        """
        frozen = HerdrRestorePoolEntryDAO(
            model_name=entry.model_name,
            provider=entry.provider,
            priority=entry.priority,
            cooldown_seconds=entry.cooldown_seconds,
            rate_limit_cooldown_seconds=entry.rate_limit_cooldown_seconds,
        )
        ModelPoolEntryDAO.model_validate(frozen.model_dump())
        return frozen

    def _herdr_policy_is_reproducible(self) -> bool:
        """Compare exact tool identities and prompt additions without I/O."""
        config = self._config
        if config is None or self._agent_is_injected or config.should_stop_after_turn_hook is not None:
            return False
        provenance = self._standard_orchestrator_attachment
        if provenance is None:
            return self._begin_standard_orchestrator_attachment()
        tools = tuple(config.extra_tools or ())
        return (
            len(tools) == len(provenance.tools)
            and all(left is right for left, right in zip(tools, provenance.tools))
            and config.system_prompt == provenance.system_prompt
            and config.append_system_prompt == provenance.append_system_prompt
        )

    def attach_sub_agent_pool(
        self,
        *,
        pool: "SubAgentPool",
        spawn_tool: Optional[BaseTool] = None,
        spawn_tools: Optional[list[BaseTool]] = None,
    ) -> None:
        """Promote this session to orchestrator mode by attaching a pool and tools.

        Merges the orchestrator tools into the session config's ``extra_tools``
        list and appends ``ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM`` to the config's
        ``append_system_prompt`` so the next lazy agent build picks up both.

        Must be called before the first prompt (i.e. before ``self._agent`` is
        built). Raises ``RuntimeError`` if called after the agent has already
        been constructed, since re-building it mid-session would discard the
        conversation history held in the graph state.

        Args:
            pool (SubAgentPool): The pool that manages child processes for
                this session.
            spawn_tool (Optional[BaseTool]): Deprecated single-tool form — the
                bound ``spawn_sub_agents`` tool. Normalised into a one-element
                list. Prefer ``spawn_tools``.
            spawn_tools (Optional[list[BaseTool]]): Orchestrator tool list
                (``spawn_sub_agents`` plus optional ``launch_workflow`` /
                ``workflow_status``). Takes precedence over ``spawn_tool``.

        Raises:
            RuntimeError: When the lazy agent has already been built.
            ValueError: When neither ``spawn_tool`` nor ``spawn_tools`` supplies
                at least one tool.
        """
        self._attach_sub_agent_pool(pool=pool, spawn_tool=spawn_tool, spawn_tools=spawn_tools)
        self._publish_herdr_snapshot()

    def _attach_sub_agent_pool(
        self,
        *,
        pool: "SubAgentPool",
        spawn_tool: Optional[BaseTool] = None,
        spawn_tools: Optional[list[BaseTool]] = None,
    ) -> None:
        """Apply tools without publishing an intermediate standard-bootstrap state.

        General attachment publishes immediately through the public gateway;
        standard bootstrap publishes only after its provenance identity proof.
        """
        if self._agent is not None:
            raise RuntimeError(
                "attach_sub_agent_pool() must be called before the first prompt. "
                "The agent has already been built for this session."
            )
        self._standard_orchestrator_attachment = None
        resolved_tools: list[BaseTool] = (
            list(spawn_tools) if spawn_tools is not None else ([spawn_tool] if spawn_tool is not None else [])
        )
        if not resolved_tools:
            raise ValueError("attach_sub_agent_pool() requires at least one tool.")
        from src.agents.slo_agent.orchestrator.spawn_tool import (  # noqa: PLC0415
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
            DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT,
        )

        assert self._config is not None  # orchestrator sessions are always config-built
        existing_extra: list[BaseTool] = list(self._config.extra_tools or [])
        existing_append: str = self._config.append_system_prompt or ""
        update: dict = {
            "extra_tools": existing_extra + resolved_tools,
            "append_system_prompt": existing_append + ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        }
        if self._config.system_prompt is None:
            update["system_prompt"] = DEFAULT_ORCHESTRATOR_SYSTEM_PROMPT
        self._config = self._config.model_copy(update=update)
        self._sub_agent_pool = pool

    @property
    def sub_agent_pool(self) -> Optional["SubAgentPool"]:
        """Return the pool attached by orchestrator bootstrap, if any.

        WHAT: Exposes the session-owned pool without transferring ownership.
        WHO: Called by HeadlessRunner cleanup paths.
        WHEN: After bootstrap attaches orchestrator tools and before teardown.

        Returns:
            Optional[SubAgentPool]: Attached pool, or None for ordinary sessions.
        """
        return self._sub_agent_pool

    def attached_dispatch_snapshot(self) -> "AttachedDispatchSnapshotDAO":
        """Return the attached pool's latest admitted batch for TUI observation.

        WHAT: Delegates to the pool's explicit dispatch projection, or returns the
            explicit empty value when no pool is attached; never inspects private
            pool fields and has no side effects.
        WHO: Bound by app composition as the workflow service's attached supplier
            (feature 94 a.2); every TUI refresh calls it afresh.
        WHEN: On mount and on each observation poll.

        Returns:
            AttachedDispatchSnapshotDAO: Latest batch entries, or the empty value.
        """
        from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO  # noqa: PLC0415

        if self._sub_agent_pool is None:
            return AttachedDispatchSnapshotDAO.empty()
        return self._sub_agent_pool.attached_dispatch_snapshot()

    async def abort_child(self, *, request: "ChildAbortRequestDAO") -> "ChildAbortOutcomeDAO":
        """Ask the attached pool to stop one exact child, or report unavailable.

        WHAT: Delegates to the pool's sole child-abort gateway, which revalidates
            the request itself; without an attached pool returns the fixed
            unavailable outcome. Whole-session ``abort`` is unaffected.
        WHO: Bound by app composition as the workflow service's attached abort
            seam (feature 94 a.4); the TUI never reaches the pool directly.
        WHEN: After operator confirmation of an attached child.

        Args:
            request (ChildAbortRequestDAO): Exact current-run child identity.

        Returns:
            ChildAbortOutcomeDAO: The pool's observed outcome, or unavailable.
        """
        from src.agents.slo_agent.orchestrator.dao import ChildAbortOutcomeDAO  # noqa: PLC0415

        if self._sub_agent_pool is None:
            return ChildAbortOutcomeDAO.for_request(request=request, outcome="unavailable")
        return await self._sub_agent_pool.abort_child(request=request)

    def child_control_capability(self) -> Optional["ChildControlCapabilityDAO"]:
        """Return the attached pool's typed child-control capability, if any.

        WHAT: Exposes the pool's run/owner/parent identity and accepting state
            without private-field inspection; valid with or without history files.
        WHO: Bound by app composition as the workflow service's attached
            capability supplier (feature 94 a.4).
        WHEN: At confirmation and submission time; no side effects.

        Returns:
            Optional[ChildControlCapabilityDAO]: Capability, or None without a pool.
        """
        if self._sub_agent_pool is None:
            return None
        return self._sub_agent_pool.child_control_capability()

    @property
    def orchestration_tools(self) -> list[BaseTool]:
        """Return the orchestrator tools attached by ``attach_sub_agent_pool``.

        Test seam only — exposes the tools stored in ``_config.extra_tools``
        after a successful ``attach_sub_agent_pool`` call so tests can assert
        on the exact bundle without inspecting private config state directly.

        Returns:
            list[BaseTool]: The tool list passed to ``attach_sub_agent_pool``
                as ``spawn_tools``, or an empty list when the session has no
                config or no extra tools have been attached yet.
        """
        if self._config is None:
            return []
        return list(self._config.extra_tools or [])

    def steer(self, *, message: str | BaseMessage) -> None:
        """Queue a steering message for the next agent turn."""
        self.agent.steer(message=message)

    def abort(self) -> None:
        """Request graceful cancellation of the in-flight run.

        Aborts the active ``SloAgent`` turn and schedules the pool's ordered
        seal-and-drain shutdown when an orchestrator pool is active.
        """
        if self._agent is not None:
            self._agent.abort()
        if self._sub_agent_pool is not None:
            asyncio.ensure_future(self._sub_agent_pool.abort_and_drain())

    async def refresh_model_catalog(self) -> str:
        """Refresh OpenRouter catalog state through the session admission owner.

        WHAT: Delegates manual catalog refresh to the existing catalog service
            and adopts its published snapshot only for future submissions.
        WHO: ``SlashRouter`` calls this for the exact ``/model refresh`` action.
        WHEN: It may run while a prompt is active because admitted prompts retain
            their existing snapshot.

        Returns:
            str: Fixed safe catalog outcome suitable for transcript rendering.
        """
        result = await ModelCatalogService.refresh(provider=ProviderName.OPENROUTER, force=True)
        snapshot = ModelCatalogService.load()
        if result.status in {"fresh", "refreshed"}:
            self._catalog_snapshot = snapshot
        count = sum(
            entry.provider is ProviderName.OPENROUTER
            and entry.visible_in_picker
            and entry.availability == "available"
            for entry in snapshot.entries.values()
        )
        checked_at = ModelCatalogService.lifecycle_status().catalog_checked_at
        checked = checked_at.isoformat(timespec="seconds") if checked_at is not None else "unknown"
        return f"{result.safe_message[:140]} {count} models; last complete check: {checked}."

    async def prepare_model_selection(self, *, model_name: str) -> str:
        """Prepare and atomically commit one operator-selected route.

        WHAT: Validates the effective provider credential and requested route,
            then commits the complete selection only while the prompt lock is idle.
        WHO: ``SlashRouter`` invokes it for ``/model <canonical-route>``.
        WHEN: Runs outside a prompt; preparation may await catalog work before the
            method reacquires the lock for its final commit.

        Args:
            model_name (str): Exact canonical route selected by the operator.

        Returns:
            str: Safe success or actionable preparation outcome.
        """
        if self._preparation_status == "pending" and model_name.startswith("openrouter:"):
            return "model preparation is pending; wait before selecting a model"
        if self.is_running:
            return "cannot switch models while a prompt is in flight"
        try:
            self._validate_model_selection_credential(model_name=model_name)
            snapshot: ModelCatalogSnapshotDAO = await ModelCatalogService.prepare_models(
                model_names=(model_name,)
            )
        except ModelPreparationRequiredError:
            return f"model '{model_name}' is unavailable; run /model refresh or /auth"
        except ValueError as error:
            return str(error)
        async with self._lock:
            if self._preparation_status == "pending" and model_name.startswith("openrouter:"):
                return "model preparation is pending; wait before selecting a model"
            if self.is_running:
                return "cannot switch models while a prompt is in flight"
            try:
                self._validate_model_selection_credential(model_name=model_name, snapshot=snapshot)
            except ValueError as error:
                return str(error)
            self._commit_model_selection(model_name=model_name, snapshot=snapshot)
        try:
            UserPreferencesStore.upsert(model_name=model_name)
        except OSError:
            return f"active model switched to {model_name}. Preference was not saved."
        return f"active model switched to {model_name}. Preference saved."

    def _validate_model_selection_credential(
        self, *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> None:
        """Require credentials for the exact provider selected by the operator.

        WHAT: Restores provider authentication validation at the session boundary
            before catalog preparation or preference mutation.
        WHO: ``prepare_model_selection`` calls this for every direct selection.
        WHEN: Before preparation and again under the lock immediately before commit.

        Args:
            model_name (str): Canonical direct or OpenRouter route.
            snapshot: Prepared view for final validation; None for preliminary validation.

        Raises:
            ValueError: Missing credentials or an incompatible OpenAI backend.
        """
        provider: ProviderName = provider_for_model(model_name=model_name)
        credential = CredentialResolver.require(provider=provider)
        if provider is not ProviderName.OPENAI:
            return
        ModelCatalogService.entry_for_model(
            model_name=model_name, snapshot=snapshot
        ).require_backend_eligibility(auth_type=credential.auth_type)

    def _commit_model_selection(
        self,
        *,
        model_name: str,
        snapshot: ModelCatalogSnapshotDAO,
    ) -> None:
        """Commit a prepared selection after every fallible local value is resolved.

        WHAT: Derives the new reasoning level before replacing session route,
            pool, snapshot, and lazy-agent state together.
        WHO: ``prepare_model_selection`` calls this while holding the prompt lock.
        WHEN: After route membership and credential validation have succeeded.

        Args:
            model_name (str): Prepared route to activate.
            snapshot (ModelCatalogSnapshotDAO): Exact prepared catalog generation.
        """
        if not self._allows_model_switching:
            raise RuntimeError(
                "Cannot switch models on a pre-built SloAgentSession. "
                "Build the session from SessionConfigDAO instead."
            )
        resolved_reasoning_level: ReasoningLevel = clamp_reasoning_level(
            model_name=model_name,
            requested_level=self.active_reasoning_level,
            snapshot=snapshot,
        )
        assert self._config is not None
        self._withdraw_stale_herdr_capture()
        self._config = self._config.model_copy(
            update={"model_name": model_name, "model_pool_dao": None, "fallback_notice": None}
        )
        self._active_model_name = model_name
        self._catalog_snapshot = snapshot
        self._preparation_status = "ready"
        self._active_reasoning_level = resolved_reasoning_level
        self._adopt_herdr_capture(capture=self._capture_herdr_restore(), model_selection=True)
        self._agent = None
        self._context_window_dirty = True
        self._context_window_snapshot = None
        self._rebuild_usage_snapshot()

    def switch_model(self, *, model_name: str) -> None:
        """Switch the active model and invalidate lazy-built agent state.

        ``/model X`` is an explicit instruction to run model ``X``. On a pooled
        session, switching therefore **clears the configured pool** and drops to
        single-model mode with ``X`` — otherwise the pool branch would keep
        routing by priority and silently ignore the operator's choice. Re-clamps
        the active reasoning level against the new model's capability range so the
        title bar and the next lazy build stay truthful. The new configured name
        is persisted to ``session.json`` on the next turn via
        ``_persist_routed_model_if_changed`` (this method is synchronous).

        Args:
            model_name (str): Supported model to activate.

        Raises:
            RuntimeError: If this session wraps a pre-built agent and
                therefore cannot safely rebind models.
        """
        if self._preparation_status != "ready":
            raise RuntimeError("Model preparation required; use the asynchronous selection gateway.")
        if not self._allows_model_switching:
            raise RuntimeError(
                "Cannot switch models on a pre-built SloAgentSession. "
                "Build the session from SessionConfigDAO instead."
            )
        self._validate_model_selection_credential(model_name=model_name, snapshot=self.catalog_snapshot)
        resolved_reasoning_level: ReasoningLevel = clamp_reasoning_level(
            model_name=model_name,
            requested_level=self.active_reasoning_level,
            snapshot=self.catalog_snapshot,
        )
        if self._config is not None and self._config.model_pool_dao is not None:
            log_info(msg="model_switch_clears_pool", model_name=model_name)
        self._withdraw_stale_herdr_capture()
        if self._config is not None:
            self._config = self._config.model_copy(
                update={"model_name": model_name, "model_pool_dao": None, "fallback_notice": None}
            )
        self._active_model_name = model_name
        self._active_reasoning_level = resolved_reasoning_level
        self._adopt_herdr_capture(capture=self._capture_herdr_restore(), model_selection=True)
        self._agent = None
        # The new model may have a smaller context window than the one the
        # post-turn check last validated against; flag a one-shot pre-flight
        # compaction check on the next turn.
        self._context_window_dirty = True
        self._rebuild_usage_snapshot()

    def switch_reasoning_level(
        self,
        *,
        reasoning_level: ReasoningLevel,
    ) -> ReasoningLevel:
        """Switch the active reasoning level for future lazy agent builds.

        Args:
            reasoning_level (ReasoningLevel): Requested canonical
                reasoning level.

        Returns:
            ReasoningLevel: Final clamped active reasoning level.

        Raises:
            RuntimeError: If this session wraps a pre-built agent and
                therefore cannot safely rebuild with a new reasoning
                configuration.
        """
        if not self._allows_model_switching:
            raise RuntimeError(
                "Cannot switch reasoning on a pre-built SloAgentSession. "
                "Build the session from SessionConfigDAO instead."
            )
        clamped_level: ReasoningLevel = clamp_reasoning_level(
            model_name=self.active_model_name,
            requested_level=reasoning_level,
            snapshot=self.catalog_snapshot,
        )
        if clamped_level == self._active_reasoning_level:
            return clamped_level
        self._withdraw_stale_herdr_capture()
        self._active_reasoning_level = clamped_level
        self._adopt_herdr_capture(capture=self._capture_herdr_restore(), reasoning_commit=True)
        self._agent = None
        self._rebuild_usage_snapshot()
        return clamped_level

    async def invoke(
        self,
        *,
        text: str,
        history: Optional[list[dict]] = None,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Run one user prompt submission to completion.

        A "submission" is the user's action of sending one prompt. A single
        submission may execute multiple "attempts" (for example, an initial
        attempt and a future retry after compaction), but the operator only
        sees one coherent response.

        Each attempt follows the same lifecycle:

        1. Build a ``PromptAttemptPlanDAO`` describing what the attempt should do.
        2. Prepare runtime context: allocate a turn id, ensure session/agent
           readiness, run optional preflight compaction, load replay history,
           and resolve rate policy.
        3. Execute the attempt lifecycle: persist opening history events,
           stream the agent response, and persist the terminal event.
        4. Freeze the attempt outcome into a ``PromptAttemptResultDAO``.
        5. Ask ``_derive_next_attempt_plan`` whether another attempt is needed.
           For an initial attempt that failed with a recognized context-overflow
           error, it runs forced compaction and returns a one-shot retry plan.
           For all other outcomes it returns ``None``.
        6. If no follow-up attempt exists, re-raise any captured failure or
           return normally.

        Opening history events are the records written before the agent runs:
        ``run_started`` and ``user_message``. Terminal history events are the
        records written after the agent finishes: ``run_completed``,
        ``run_aborted``, or ``run_failed``.

        Args:
            text (str): User prompt text for this submission.
            history (Optional[list[dict]]): Optional legacy caller-supplied
                history used only by tests. The production path loads history
                from the persistent store.

        Yields:
            AgentStreamEventDAO: Live stream events from the active attempt,
                including thinking deltas, text deltas, tool calls, and
                terminal events.

        Raises:
            RuntimeError: If another prompt is already in flight on this session.
            BaseException: The terminal provider or runtime failure when the
                attempt failed and no retry plan is available.
        """
        if self._preparation_status != "ready":
            if not self._is_running:
                self.set_operator_attention(reason="Model preparation required")
            raise ModelPreparationRequiredError("Model preparation required; use /auth or /model refresh.")
        self._assert_no_prompt_in_flight()
        async with self._session_run_scope():
            plan: PromptAttemptPlanDAO = self._build_initial_attempt_plan(
                text=text,
            )
            pending_session_events: list[AgentStreamEventDAO] = []
            while True:
                prepared: PreparedPromptAttemptDAO = await self._prepare_attempt_context(
                    plan=plan,
                )
                for event in pending_session_events:
                    yield event
                pending_session_events = []
                tracker: PromptAttemptTrackerDAO = self._build_attempt_tracker(
                    turn_id=prepared.turn_id,
                )
                try:
                    async for event in self._run_attempt_lifecycle(
                        prepared=prepared,
                        tracker=tracker,
                        history=history,
                    ):
                        yield event
                except Exception as exc:
                    if self._should_reraise_attempt_exception(
                        tracker=tracker,
                    ):
                        raise
                    self._record_unhandled_attempt_exception(
                        tracker=tracker,
                        error=exc,
                    )
                result: PromptAttemptResultDAO = self._build_attempt_result(
                    tracker=tracker,
                )
                next_plan: PromptAttemptPlanDAO | None = await self._derive_next_attempt_plan(
                    plan=plan,
                    result=result,
                )
                if next_plan is not None:
                    if next_plan.attempt_kind == "stream_reconnect":
                        pending_session_events.append(self._build_stream_reconnecting_event(result=result))
                    if next_plan.attempt_kind == "stream_continuation":
                        pending_session_events.append(
                            self._build_stream_continuation_retrying_event(plan=next_plan)
                        )
                    plan = next_plan
                    continue
                self._raise_if_attempt_failed(
                    result=result,
                )
                return

    def _assert_no_prompt_in_flight(self) -> None:
        """Raise if another prompt is already running on this session.

        Checks ``self._is_running`` before lock acquisition so the caller gets
        a clear error message without waiting.

        Returns:
            None: When no prompt is in flight.

        Raises:
            RuntimeError: When ``self._is_running`` is ``True``.
        """
        if not self._is_running:
            return
        raise RuntimeError(
            "SloAgentSession already processing a prompt. Steer or follow_up "
            "if you want to inject a message; or await completion first."
        )

    @asynccontextmanager
    async def _session_run_scope(self) -> AsyncIterator[None]:
        """Acquire the prompt lock and set ``_is_running`` for one submission.

        This context manager guarantees that:

        - only one prompt runs at a time,
        - ``self._is_running`` is ``True`` while inside the scope,
        - ``self._is_running`` is reset to ``False`` when the scope exits,
          even if an exception escapes.

        Yields:
            None: The scope inside which one submission executes.
        """
        async with self._lock:
            self._is_running = True
            self._clear_terminal_reporting_attention()
            token = self._begin_reporting_operation()
            try:
                await self._prepare_run_snapshot()
                with CredentialResolver.bind_operation_credential(
                    credential=self._admitted_openrouter_credential
                ):
                    yield
            except ModelPreparationRequiredError:
                self.set_operator_attention(reason="Model preparation required")
                raise
            except Exception:
                self._set_terminal_reporting_failure()
                raise
            finally:
                self._refresh_final_reporting_usage()
                self._admitted_run_snapshot = None
                self._admitted_openrouter_credential = None
                self._is_running = False
                self._end_reporting_operation(token=token)

    def _set_terminal_reporting_failure(self) -> None:
        """Retain an explicit authentication requirement over a generic run failure."""
        if self._operator_attention is not None:
            if self._operator_attention.reason == "Authentication required":
                return
        self.set_operator_attention(reason="Run failed; review Slo")

    def _clear_terminal_reporting_attention(self) -> None:
        """A newly admitted submission clears only the previous terminal run failure."""
        attention = self._operator_attention
        if attention is not None and attention.reason == "Run failed; review Slo":
            self.clear_operator_attention(token=attention.token)

    def _refresh_final_reporting_usage(self) -> None:
        """Refresh before settlement without replacing the original submission outcome."""
        try:
            self.refresh_usage_snapshot()
        except Exception:
            self._log_herdr_publication_failure()

    def _build_initial_attempt_plan(
        self,
        *,
        text: str,
    ) -> PromptAttemptPlanDAO:
        """Return the plan for the first attempt of a prompt submission.

        The initial attempt:

        - persists a ``user_message`` event so the prompt appears in history,
        - does not exclude any prior turns from replay,
        - respects the ``_context_window_dirty`` flag when deciding whether to
          run preflight compaction.

        Args:
            text (str): User-submitted prompt text.

        Returns:
            PromptAttemptPlanDAO: Plan describing the initial attempt.
        """
        return PromptAttemptPlanDAO(
            attempt_kind="initial",
            text=text,
            persist_user_message=True,
            excluded_turn_ids=frozenset(),
            preflight_compaction_mode="respect_dirty_flag",
            source_failed_turn_id=None,
            submission_attempt_number=1,
            max_submission_attempts=provider_stream_continuation_max_attempts(),
            original_text=text,
        )

    async def _prepare_attempt_context(
        self,
        *,
        plan: PromptAttemptPlanDAO,
    ) -> PreparedPromptAttemptDAO:
        """Resolve all runtime collaborators needed for one attempt.

        This method performs setup in a strict order:

        1. Allocate a fresh ``turn_id``. This id is used in every persisted
           history event for this attempt and is required before compaction
           runs, because a compaction summary must be anchored to the turn
           that triggered it.
        2. Ensure the on-disk session metadata exists.
        3. Ensure the agent is built and its credentials are fresh.
        4. Run the attempt's preflight compaction policy.
        5. Load projected message history from durable events. Any turn ids
           listed in ``plan.excluded_turn_ids`` are omitted from this replay
           only; they remain on disk.
        6. Build the runtime trace handler and resolve the rate policy.

        Args:
            plan (PromptAttemptPlanDAO): Plan describing the attempt to realize.

        Returns:
            PreparedPromptAttemptDAO: Container holding every collaborator the
                execution phase needs.
        """
        turn_id: str = self._allocate_turn_id()
        await self._ensure_history_session()
        self._admit_run_snapshot()
        await self._ensure_agent_ready()
        await self._run_plan_preflight_compaction(
            plan=plan,
            turn_id=turn_id,
        )
        message_history: list[BaseMessage] = await self._load_message_history(
            excluded_turn_ids=set(plan.excluded_turn_ids),
        )
        runtime_handler: Optional[AgentRuntimeHandler] = self._build_runtime_handler_for_attempt(
            turn_id=turn_id,
        )
        policy: ModelRateLimitPolicyDAO = self._resolve_attempt_policy()
        return PreparedPromptAttemptDAO(
            plan=plan,
            turn_id=turn_id,
            message_history=message_history,
            runtime_handler=runtime_handler,
            policy=policy,
        )

    def _allocate_turn_id(self) -> str:
        """Return a new UUID4 turn identifier for one attempt.

        Returns:
            str: A fresh turn id that will be stamped onto every history event
                belonging to this attempt.
        """
        return str(uuid4())

    async def _run_plan_preflight_compaction(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        turn_id: str,
    ) -> None:
        """Decide whether this attempt should run the preflight compaction check.

        The preflight compaction check compacts the session history before the
        turn starts when the effective context window may have changed (for
        example, after a model switch or on the first turn after resume).

        Conditions:

        - If ``plan.preflight_compaction_mode`` is ``"skip"``, do nothing.
        - Otherwise, delegate to ``_preflight_compaction_if_dirty``, which
          compacts only when ``self._context_window_dirty`` is ``True``.

        Args:
            plan (PromptAttemptPlanDAO): Plan controlling preflight behavior.
            turn_id (str): Turn id allocated for this attempt.
        """
        if plan.preflight_compaction_mode == "skip":
            return
        await self._preflight_compaction_if_dirty(
            turn_id=turn_id,
        )

    def _build_runtime_handler_for_attempt(
        self,
        *,
        turn_id: str,
    ) -> Optional[AgentRuntimeHandler]:
        """Return the history trace handler for one attempt.

        The handler maps runtime agent trace events (assistant deltas, tool
        calls, tool results, etc.) into canonical ``SessionHistoryEventDAO``
        records and appends them to the store. It is only needed when history
        persistence is enabled.

        Args:
            turn_id (str): Turn id for the current attempt.

        Returns:
            Optional[AgentRuntimeHandler]: The runtime trace handler when
                history is enabled, otherwise ``None``.
        """
        if not self._enable_history:
            return None
        return self._runtime_handler_for_turn(
            turn_id=turn_id,
        )

    def _resolve_attempt_policy(self) -> ModelRateLimitPolicyDAO:
        """Return the rate policy for the active routed model.

        The policy is used by ``_stream_prompt_with_retries`` to decide
        preflight wait behavior and iteration retry budgets.

        Returns:
            ModelRateLimitPolicyDAO: Rate policy for ``self.active_model_name``
                or the pool-routed model name when a model pool is active.
        """
        return policy_for_model(
            model_name=self._resolve_active_model_name() or self.active_model_name,
            snapshot=self.catalog_snapshot,
        )

    def _build_attempt_tracker(
        self,
        *,
        turn_id: str,
    ) -> PromptAttemptTrackerDAO:
        """Create a fresh mutable tracker for one attempt.

        The tracker records the terminal outcome while the attempt streams.
        It is later converted into an immutable ``PromptAttemptResultDAO``.

        Args:
            turn_id (str): Turn identifier for the attempt.

        Returns:
            PromptAttemptTrackerDAO: A tracker initialized with no terminal
                state and an empty final response.
        """
        return PromptAttemptTrackerDAO(
            turn_id=turn_id,
        )

    async def _run_attempt_lifecycle(
        self,
        *,
        prepared: PreparedPromptAttemptDAO,
        tracker: PromptAttemptTrackerDAO,
        history: Optional[list[dict]],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Execute one prepared attempt and yield its live stream events.

        Lifecycle steps:

        1. Persist the opening history events (``run_started`` and optionally
           ``user_message``) for this attempt.
        2. Stream the agent response through ``_stream_prompt_with_retries``.
           For each event, mirror terminal outcomes into the tracker and
           persist any ``run_retrying`` diagnostics.
        3. If the stream raises an exception, finalize the attempt as failed
           and stop streaming.
        4. If the stream ends normally, finalize the attempt as completed or
           aborted.
        5. In the ``finally`` block, write a fallback ``run_failed`` event if
           no terminal event was successfully persisted.

        Args:
            prepared (PreparedPromptAttemptDAO): Resolved runtime context for
                the attempt.
            tracker (PromptAttemptTrackerDAO): Mutable tracker to update.
            history (Optional[list[dict]]): Legacy caller-supplied history
                forwarded to the agent stream when persistent history is empty.

        Yields:
            AgentStreamEventDAO: Live events produced by the agent during the
                attempt.
        """
        try:
            await self._persist_attempt_opening_events(
                plan=prepared.plan,
                turn_id=prepared.turn_id,
            )
            try:
                async for event in self._stream_prompt_with_retries(
                    text=prepared.plan.text,
                    history=history,
                    message_history=prepared.message_history,
                    runtime_handler=prepared.runtime_handler,
                    policy=prepared.policy,
                    tracker=tracker,
                ):
                    self._record_attempt_stream_event(
                        tracker=tracker,
                        event=event,
                    )
                    if event.kind == "run_retrying":
                        await self._persist_run_retrying_event(
                            event=event,
                            turn_id=prepared.turn_id,
                        )
                    elif event.kind == "preflight_bypassed" and self._enable_history:
                        await self._persist_preflight_bypassed_event(
                            event=event,
                            turn_id=prepared.turn_id,
                        )
                    elif event.kind == "recovery_started":
                        await self._persist_recovery_events(
                            event=event,
                            turn_id=prepared.turn_id,
                        )
                    yield event
            except asyncio.CancelledError:
                tracker.aborted = True
                await self._finalize_successful_attempt(
                    tracker=tracker,
                    turn_id=prepared.turn_id,
                )
                yield AgentStreamEventDAO(kind="run_aborted", content="<aborted>")
                return
            except Exception as exc:
                await self._finalize_failed_attempt(
                    tracker=tracker,
                    turn_id=prepared.turn_id,
                    error=exc,
                )
                return
            await self._finalize_successful_attempt(
                tracker=tracker,
                turn_id=prepared.turn_id,
            )
        finally:
            await self._append_fallback_terminal_event_if_needed(
                tracker=tracker,
            )
            self._preflight_decisions_by_turn.pop(tracker.turn_id, None)

    def _assembled_system_prompt(self) -> str:
        """Compute the effective system prompt that will be passed to SloAgent.

        Combines the base system prompt from config with any appended fragment
        (e.g. the orchestrator addendum injected by ``attach_sub_agent_pool``).
        Returns an empty string when no config is available (pre-built agent path).

        Returns:
            str: Assembled system prompt combining base and append fragments.
        """
        if self._config is None:
            return ""
        base: str = self._config.system_prompt or ""
        append: str = self._config.append_system_prompt or ""
        return base + append

    async def _write_orchestrator_context(self, *, user_prompt: str) -> None:
        """Persist the orchestrator invocation context to disk once.

        Written once per session on the first user message. Best-effort:
        ``OSError`` is logged but never propagated so the workflow continues
        even if the capture write fails. Skipped when history is disabled.

        Args:
            user_prompt (str): Content of the first user message that triggered
                this workflow run.
        """
        if self._sub_agent_pool is None:
            return
        if self._orchestrator_context_written:
            return
        if not self._enable_history or self._history_store is None:
            return
        self._orchestrator_context_written = True
        context_path: Path = self._history_store.root / self._session_id / "orchestrator_context.json"
        if context_path.exists():
            return
        try:
            from src.agents.slo_agent.orchestrator.context_dao import (  # noqa: PLC0415
                OrchestratorContextDAO,
                dump_json_bytes,
            )

            context: OrchestratorContextDAO = OrchestratorContextDAO.build(
                system_prompt=self._assembled_system_prompt(),
                user_prompt=user_prompt,
                model=self._resolve_active_model_name() or self._active_model_name,
            )
            data: bytes = dump_json_bytes(model=context)
            context_dir: Path = context_path.parent
            context_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=context_dir, delete=False) as tmp:
                tmp.write(data)
                tmp_name: str = tmp.name
            os.replace(tmp_name, context_path)
        except OSError as exc:
            log_warning(
                msg="orchestrator_context_write_failed",
                session_id=self._session_id,
                error=str(exc),
            )

    async def _persist_attempt_opening_events(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        turn_id: str,
    ) -> None:
        """Persist the history events that open a turn.

        Opening events are written before the agent starts executing. They are:

        - ``run_started``: lifecycle marker carrying the prompt text and active
          model name.
        - ``user_message``: the user's prompt content as a conversational
          message, written only when ``plan.persist_user_message`` is ``True``.

        A retry attempt of the same prompt sets ``persist_user_message=False``
        so the prompt is not duplicated in durable history.

        Args:
            plan (PromptAttemptPlanDAO): Plan governing what to persist.
            turn_id (str): Turn identifier to stamp onto the events.

        Returns:
            None: Events are appended synchronously to the history store.

        Raises:
            Exception: Any exception raised by ``_append_history_event``
                propagates and aborts the attempt.
        """
        await self._append_history_event(
            event=self._build_event(
                kind="run_started",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    content=plan.text,
                    model_name=self._resolve_active_model_name(),
                ),
            ),
        )
        if not plan.persist_user_message:
            return
        await self._append_history_event(
            event=self._build_event(
                kind="user_message",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    role="user",
                    content=plan.text,
                ),
            ),
        )
        await self._write_orchestrator_context(user_prompt=plan.text)

    def _record_attempt_stream_event(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
        event: AgentStreamEventDAO,
    ) -> None:
        """Update the tracker when a terminal stream event is observed.

        Only ``run_completed`` and ``run_aborted`` terminal outcomes are
        mirrored here. Other events (thinking deltas, text deltas, tool calls)
        pass through without mutating the tracker.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker to update.
            event (AgentStreamEventDAO): One event yielded from the agent stream.

        Returns:
            None: The tracker is mutated in place.
        """
        if SloAgent._is_committed_output_event(event=event):
            tracker.committed_visible_output = True
        if event.kind == "run_completed":
            tracker.final_response = event.content or ""
            tracker.aborted = False
            tracker.terminal_kind = "run_completed"
            return
        if event.kind == "run_aborted":
            tracker.final_response = "<aborted>"
            tracker.aborted = True
            tracker.terminal_kind = "run_aborted"

    async def _finalize_successful_attempt(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
        turn_id: str,
    ) -> None:
        """Persist the terminal outcome for a successful or aborted attempt.

        Steps:

        1. Drain and persist any ModelPool route-switch audit records.
        2. Sync the routed model name into session metadata if it changed.
        3. Write ``run_aborted`` if the tracker is marked aborted, otherwise
           write ``run_completed`` with the final assistant text.
        4. Mark the tracker so the fallback guard knows a terminal event was
           appended.
        5. Run the post-turn compaction check.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker holding the observed
                terminal state.
            turn_id (str): Turn identifier for the attempt.

        Returns:
            None: Terminal event and optional compaction are persisted.
        """
        await self._drain_and_persist_route_switches(
            turn_id=turn_id,
        )
        await self._persist_routed_model_if_changed()
        if tracker.aborted:
            await self._append_history_event(
                event=self._build_event(
                    kind="run_aborted",
                    turn_id=turn_id,
                ),
            )
            tracker.terminal_kind = "run_aborted"
            tracker.terminal_event_appended = True
        else:
            await self._append_history_event(
                event=self._build_event(
                    kind="run_completed",
                    turn_id=turn_id,
                    payload=SessionHistoryEventPayloadDAO(
                        content=tracker.final_response,
                    ),
                ),
            )
            tracker.terminal_kind = "run_completed"
            tracker.terminal_event_appended = True
        await self._run_compaction_if_needed(
            turn_id=turn_id,
        )

    async def _finalize_failed_attempt(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
        turn_id: str,
        error: BaseException,
    ) -> None:
        """Persist the terminal outcome for a failed attempt.

        Steps:

        1. Drain and persist any ModelPool route-switch audit records.
        2. Sync the routed model name into session metadata if it changed.
        3. Write ``run_failed`` with the exception type and message.
        4. Mark the tracker as failed so the result builder can report it.
        5. Record whether the failure was a provider context overflow so
           ``_derive_next_attempt_plan`` can decide on recovery. Forced
           compaction is no longer run here — it now runs in
           ``_derive_next_attempt_plan`` where it is coupled to the retry
           decision rather than running speculatively.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker to update.
            turn_id (str): Turn identifier for the attempt.
            error (BaseException): Exception that terminated the attempt.

        Returns:
            None: Terminal event is persisted; overflow eligibility is recorded.
        """
        await self._drain_and_persist_route_switches(
            turn_id=turn_id,
        )
        await self._persist_routed_model_if_changed()
        signal: ProviderErrorSignalDAO | None = self._inspect_provider_error(error=error)
        if signal is not None and tracker.preflight_decision is not None:
            await self._persist_provider_limit_observation(
                turn_id=turn_id,
                signal=signal,
                decision=tracker.preflight_decision,
            )
        await self._append_history_event(
            event=self._build_event(
                kind="run_failed",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    error_message=self._safe_attempt_error_message(error=error),
                    model_name=self._resolve_active_model_name(),
                    metadata=self._stream_failure_metadata(error=error),
                ),
            ),
        )
        tracker.error = error
        tracker.aborted = False
        tracker.terminal_kind = "run_failed"
        tracker.terminal_event_appended = True
        tracker.overflow_recovery_eligible = (
            signal is not None
            and signal.kind is ProviderErrorKind.CONTEXT_OVERFLOW
            and not tracker.committed_visible_output
        )
        tracker.provider_signal = signal
        tracker.stream_failure = error if isinstance(error, ProviderStreamFailure) else None

    async def _append_fallback_terminal_event_if_needed(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
    ) -> None:
        """Write a fallback ``run_failed`` if no terminal event was persisted.

        This guard covers cases where an unexpected cancellation or helper
        failure prevented ``_finalize_successful_attempt`` or
        ``_finalize_failed_attempt`` from writing a terminal record. Without
        this fallback, the turn would appear incomplete to the projector on
        the next load.

        Conditions:

        - Skip if a terminal event was already appended.
        - Skip when history persistence is disabled.
        - Otherwise, append ``run_failed`` with a generic message.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker for the current attempt.

        Returns:
            None: A fallback terminal event may be appended to history.
        """
        if tracker.terminal_event_appended:
            return
        if not self._enable_history:
            return
        try:
            await self._append_history_event(
                event=self._build_event(
                    kind="run_failed",
                    turn_id=tracker.turn_id,
                    payload=SessionHistoryEventPayloadDAO(
                        error_message="turn terminated without explicit outcome",
                        model_name=self._resolve_active_model_name(),
                    ),
                ),
            )
            tracker.terminal_kind = tracker.terminal_kind or "run_failed"
            tracker.final_response = tracker.final_response or ""
            tracker.terminal_event_appended = True
        except Exception as exc:  # noqa: BLE001
            log_error(
                msg="SloAgentSession: failed to write fallback terminal event",
                e=exc,
                stack_trace=False,
            )

    def _record_unhandled_attempt_exception(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
        error: BaseException,
    ) -> None:
        """Capture an exception that escaped ``_run_attempt_lifecycle``.

        This should rarely happen, because ``_run_attempt_lifecycle`` catches
        stream exceptions and converts them into failed attempts. If an
        exception escapes anyway (for example, from the fallback terminal
        guard), this method records it on the tracker so the orchestrator
        can still report a failed result.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker to update.
            error (BaseException): The escaped exception.

        Returns:
            None: The tracker is mutated in place.
        """
        tracker.error = error
        tracker.aborted = False
        tracker.terminal_kind = tracker.terminal_kind or "run_failed"

    def _should_reraise_attempt_exception(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
    ) -> bool:
        """Return True when an escaped lifecycle exception must propagate.

        An exception that escapes after a terminal event was already appended
        is likely a post-terminal helper failure (for example, a compaction
        error after ``run_completed``). In that case the original terminal
        outcome is already recorded, and the new exception should propagate
        so the caller sees it.

        Conditions:

        - Return ``False`` if no terminal event was appended yet; the
          orchestrator will synthesize a failed result from the tracker.
        - Return ``True`` if the attempt already ended in ``run_completed``
          or ``run_aborted`` and a later helper raised.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker for the current attempt.

        Returns:
            bool: Whether the escaped exception should be re-raised.
        """
        if not tracker.terminal_event_appended:
            return False
        return tracker.terminal_kind in ("run_completed", "run_aborted")

    def _build_attempt_result(
        self,
        *,
        tracker: PromptAttemptTrackerDAO,
    ) -> PromptAttemptResultDAO:
        """Convert mutable tracker state into an immutable attempt result.

        The result is the only object the top-level orchestrator uses to
        decide whether to finish the submission or proceed to a follow-up
        attempt.

        Args:
            tracker (PromptAttemptTrackerDAO): Tracker whose state should be
                frozen.

        Returns:
            PromptAttemptResultDAO: Immutable terminal summary of the attempt.
        """
        terminal_kind: Literal["run_completed", "run_aborted", "run_failed"] = (
            tracker.terminal_kind or "run_failed"
        )
        return PromptAttemptResultDAO(
            turn_id=tracker.turn_id,
            terminal_kind=terminal_kind,
            final_response=tracker.final_response,
            aborted=tracker.aborted,
            error=tracker.error,
            overflow_recovery_eligible=tracker.overflow_recovery_eligible,
            committed_visible_output=tracker.committed_visible_output,
            stream_failure=tracker.stream_failure,
            provider_signal=tracker.provider_signal,
            preflight_decision=tracker.preflight_decision,
            originating_provider=self._resolve_active_provider(),
        )

    async def _derive_next_attempt_plan(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        result: PromptAttemptResultDAO,
    ) -> Optional[PromptAttemptPlanDAO]:
        """Decide whether the submission needs a follow-up attempt.

        Returns a one-shot overflow-recovery plan when
        ``_is_overflow_recovery_eligible`` returns ``True``, which requires:

        1. The attempt was the initial one (``attempt_kind == "initial"``),
           enforcing a one-retry budget so a second overflow cannot loop.
        2. ``result.overflow_recovery_eligible`` is ``True``, which was set in
           ``_finalize_failed_attempt`` when the error was a recognized context
           overflow.

        When both hold, this method emits compaction lifecycle events, runs
        forced compaction, persists a diagnostic ``run_retrying`` event, and
        returns the retry plan. The top-level orchestration loop then executes
        the retry automatically.

        If forced compaction itself raises, the original overflow error must
        still reach the caller. This method therefore returns ``None`` on
        compaction failure; ``_raise_if_attempt_failed`` then re-raises
        ``result.error`` — the original provider overflow — unchanged.

        Returns ``None`` in all other cases: normal completion, abort, non-
        overflow failure, second overflow after retry budget spent.

        Args:
            plan (PromptAttemptPlanDAO): Plan for the attempt that just finished.
            result (PromptAttemptResultDAO): Terminal result of that attempt.

        Returns:
            Optional[PromptAttemptPlanDAO]: Retry plan when overflow recovery
                should continue, otherwise ``None``.
        """
        stream_reconnect_plan: Optional[PromptAttemptPlanDAO] = (
            await self._derive_stream_reconnect_attempt_plan(
                plan=plan,
                result=result,
            )
        )
        if stream_reconnect_plan is not None:
            return stream_reconnect_plan
        stream_continuation_plan: Optional[PromptAttemptPlanDAO] = (
            await self._derive_stream_continuation_attempt_plan(
                plan=plan,
                result=result,
            )
        )
        if stream_continuation_plan is not None:
            return stream_continuation_plan
        if not self._is_overflow_recovery_eligible(
            plan=plan,
            result=result,
        ):
            return None
        await self._emit_compaction_event(kind="compaction_started")
        try:
            compacted: bool = await self._run_compaction_if_needed(
                turn_id=result.turn_id,
                force=True,
            )
        except Exception as compaction_exc:  # noqa: BLE001
            log_error(
                msg="overflow_compaction_failed_before_retry",
                error_class=type(compaction_exc).__name__,
                stack_trace=False,
            )
            await self._report_compaction_failure(
                turn_id=result.turn_id,
                error=compaction_exc,
            )
            return None
        if not compacted:
            await self._emit_compaction_event(kind="compaction_failed")
            return None
        await self._emit_compaction_event(kind="compaction_completed")
        await self._persist_overflow_retry_diagnostic_event(
            failed_turn_id=result.turn_id,
            text=plan.text,
        )
        await self._emit_compaction_event(kind="compaction_retrying")
        return self._build_overflow_retry_attempt_plan(
            text=plan.text,
            failed_turn_id=result.turn_id,
        )

    async def _derive_stream_reconnect_attempt_plan(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        result: PromptAttemptResultDAO,
    ) -> Optional[PromptAttemptPlanDAO]:
        """Build and audit the one permitted fresh-connection attempt.

        Called by the submission attempt planner after a failed initial attempt.
        It never sleeps or replays committed output; the agent owns the typed
        commit-state decision and this session owns durable audit state.
        """
        failure: Optional[ProviderStreamFailure] = result.stream_failure
        if plan.attempt_kind != "initial" or failure is None:
            return None
        if failure.partial_output_committed:
            return None
        if failure.decision.action.value != "retry_fresh_connection":
            return None
        await self._persist_stream_reconnecting_event(
            failed_turn_id=result.turn_id,
            decision=failure.decision,
        )
        await asyncio.sleep(failure.decision.retry_delay_seconds)
        return PromptAttemptPlanDAO(
            attempt_kind="stream_reconnect",
            text=plan.text,
            persist_user_message=False,
            excluded_turn_ids=frozenset({result.turn_id}),
            preflight_compaction_mode="skip",
            source_failed_turn_id=result.turn_id,
            submission_attempt_number=plan.submission_attempt_number,
            max_submission_attempts=plan.max_submission_attempts,
            original_text=plan.original_text,
        )

    async def _derive_stream_continuation_attempt_plan(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        result: PromptAttemptResultDAO,
    ) -> Optional[PromptAttemptPlanDAO]:
        """Build a safe continuation plan for one committed stream interruption."""
        if not self._is_stream_continuation_eligible(plan=plan, result=result):
            return None
        continuation_plan: PromptAttemptPlanDAO = self._build_stream_continuation_attempt_plan(
            plan=plan,
            failed_turn_id=result.turn_id,
        )
        await self._persist_stream_continuation_retrying_event(
            failed_turn_id=result.turn_id,
            plan=continuation_plan,
            failure=result.stream_failure,
        )
        return continuation_plan

    @staticmethod
    def _is_stream_continuation_eligible(
        *,
        plan: PromptAttemptPlanDAO,
        result: PromptAttemptResultDAO,
    ) -> bool:
        """Return whether a committed stream interruption may continue safely."""
        failure: ProviderStreamFailure | None = result.stream_failure
        if result.originating_provider is ProviderName.OPENROUTER:
            return False
        if failure is None:
            return False
        if failure.decision.action is not StreamRecoveryAction.DO_NOT_REPLAY:
            return False
        if not failure.partial_output_committed:
            return False
        return plan.submission_attempt_number < plan.max_submission_attempts

    @staticmethod
    def _build_stream_continuation_attempt_plan(
        *,
        plan: PromptAttemptPlanDAO,
        failed_turn_id: str,
    ) -> PromptAttemptPlanDAO:
        """Build the next safe continuation request for the original task."""
        attempt_number: int = plan.submission_attempt_number + 1
        continuation_text: str = (
            f"Continuation attempt {attempt_number}/{plan.max_submission_attempts}.\n\n"
            "The prior provider stream ended unexpectedly after partial output. Before acting, "
            "inspect the current worktree, git diff, and task artifacts. Do not repeat a completed "
            "or side-effecting operation unless inspection shows it is still needed and safe. "
            "Continue the original task from the verified state.\n\n"
            f"Original task:\n{plan.original_text}"
        )
        return PromptAttemptPlanDAO(
            attempt_kind="stream_continuation",
            text=continuation_text,
            persist_user_message=True,
            excluded_turn_ids=frozenset(),
            preflight_compaction_mode="respect_dirty_flag",
            source_failed_turn_id=failed_turn_id,
            submission_attempt_number=attempt_number,
            max_submission_attempts=plan.max_submission_attempts,
            original_text=plan.original_text,
        )

    async def _persist_stream_continuation_retrying_event(
        self,
        *,
        failed_turn_id: str,
        plan: PromptAttemptPlanDAO,
        failure: ProviderStreamFailure | None,
    ) -> None:
        """Persist the redacted audit event before a stream continuation starts."""
        if failure is None:
            raise RuntimeError("stream continuation requires a typed stream failure")
        metadata: dict[str, object] = {
            "reason_code": failure.decision.reason_code,
            "attempt": plan.submission_attempt_number,
            "max_attempts": plan.max_submission_attempts,
            "exception_family": failure.decision.exception_family,
        }
        await self._append_history_event(
            event=self._build_event(
                kind="run_retrying",
                turn_id=failed_turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    message=self._stream_continuation_retry_message(plan=plan),
                    metadata=metadata,
                ),
            ),
        )

    @staticmethod
    def _build_stream_continuation_retrying_event(*, plan: PromptAttemptPlanDAO) -> AgentStreamEventDAO:
        """Build the public retrying event for a pending stream continuation."""
        return AgentStreamEventDAO(
            kind="run_retrying",
            content=SloAgentSession._stream_continuation_retry_message(plan=plan),
            metadata={
                "reason_code": "provider_stream_interrupted",
                "attempt": plan.submission_attempt_number,
                "max_attempts": plan.max_submission_attempts,
            },
        )

    @staticmethod
    def _stream_continuation_retry_message(*, plan: PromptAttemptPlanDAO) -> str:
        """Return the redacted status message for one continuation attempt."""
        return (
            "Provider stream interrupted; continuing from verified state "
            f"(attempt {plan.submission_attempt_number}/{plan.max_submission_attempts})."
        )

    async def _persist_stream_reconnecting_event(
        self,
        *,
        failed_turn_id: str,
        decision: StreamRecoveryDecisionDAO,
    ) -> None:
        """Persist and render the redacted reconnect audit before the fresh request.

        WHAT: Writes the diagnostic boundary event for the one permitted retry.
        WHO: Called by the session attempt planner before it sleeps and re-invokes.
        WHEN: Only after an initial pre-commit typed provider failure.
        """
        metadata: dict[str, object] = {
            "reason_code": decision.reason_code,
            "attempt": 1,
            "exception_family": decision.exception_family,
        }
        await self._append_history_event(
            event=self._build_event(
                kind="stream_reconnecting",
                turn_id=failed_turn_id,
                payload=SessionHistoryEventPayloadDAO(metadata=metadata),
            ),
        )
        await self._dispatch_event(
            event=AgentStreamEventDAO(kind="stream_reconnecting", metadata=metadata),
        )

    @staticmethod
    def _build_stream_reconnecting_event(
        *,
        result: PromptAttemptResultDAO,
    ) -> AgentStreamEventDAO:
        """Build the public reconnect event after the session persists its audit.

        ``invoke`` calls this helper before starting the fresh attempt so TUI and
        headless consumers receive the same reconnect boundary that subscribers
        receive from ``_persist_stream_reconnecting_event``.
        """
        failure: ProviderStreamFailure | None = result.stream_failure
        if failure is None:
            raise RuntimeError("stream reconnect plan requires a typed stream failure")
        return AgentStreamEventDAO(
            kind="stream_reconnecting",
            metadata={
                "reason_code": failure.decision.reason_code,
                "attempt": 1,
                "exception_family": failure.decision.exception_family,
            },
        )

    @staticmethod
    def _safe_attempt_error_message(*, error: BaseException) -> str:
        """Return redacted text for typed stream failures and legacy text otherwise."""
        if isinstance(error, ProviderStreamFailure):
            return str(error)
        return f"{type(error).__name__}: {error}"

    @staticmethod
    def _stream_failure_metadata(*, error: BaseException) -> dict[str, object]:
        """Return approved terminal metadata without provider exception content."""
        if not isinstance(error, ProviderStreamFailure):
            return {}
        return {
            "failure_code": error.decision.reason_code,
            "partial_output_committed": error.partial_output_committed,
            "attempts": error.attempt_number,
            "exception_family": error.decision.exception_family,
        }

    def _is_overflow_recovery_eligible(
        self,
        *,
        plan: PromptAttemptPlanDAO,
        result: PromptAttemptResultDAO,
    ) -> bool:
        """Return True when this attempt qualifies for one-shot overflow recovery.

        Both conditions must hold:

        1. The attempt is the initial attempt — ``attempt_kind == "initial"``.
           This enforces the one-retry budget: an overflow-retry attempt that
           overflows again is terminal.
        2. ``result.overflow_recovery_eligible`` is ``True`` and no committed
           visible output crossed the attempt boundary. The flag is set by
           ``_finalize_failed_attempt`` from the shared provider signal, so this
           method never re-classifies the raw exception.

        Args:
            plan (PromptAttemptPlanDAO): The plan for the attempt that just failed.
            result (PromptAttemptResultDAO): The frozen terminal result carrying
                the pre-computed overflow eligibility flag.

        Returns:
            bool: True when recovery via compaction-and-retry should be attempted.
        """
        if plan.attempt_kind != "initial":
            return False
        if result.committed_visible_output:
            return False
        return result.overflow_recovery_eligible

    def _build_overflow_retry_attempt_plan(
        self,
        *,
        text: str,
        failed_turn_id: str,
    ) -> PromptAttemptPlanDAO:
        """Construct the retry attempt plan for an overflow recovery.

        All retry-specific field values live here so ``_derive_next_attempt_plan``
        reads as a table of contents rather than a plan constructor.

        - ``attempt_kind="overflow_retry"`` marks it as the one-shot recovery
          so a second overflow in this attempt cannot loop.
        - ``persist_user_message=False`` prevents writing a duplicate
          ``user_message`` event.
        - ``excluded_turn_ids={failed_turn_id}`` ensures the projector omits the
          just-failed turn from immediate replay context.
        - ``preflight_compaction_mode="skip"`` avoids redundant compaction.
        - ``source_failed_turn_id=failed_turn_id`` is the audit link.

        Args:
            text (str): The original user prompt text to re-submit.
            failed_turn_id (str): Turn id of the failed overflow attempt.

        Returns:
            PromptAttemptPlanDAO: Retry plan for the same submission.
        """
        return PromptAttemptPlanDAO(
            attempt_kind="overflow_retry",
            text=text,
            persist_user_message=False,
            excluded_turn_ids=frozenset({failed_turn_id}),
            preflight_compaction_mode="skip",
            source_failed_turn_id=failed_turn_id,
            submission_attempt_number=1,
            max_submission_attempts=provider_stream_continuation_max_attempts(),
            original_text=text,
        )

    async def _persist_overflow_retry_diagnostic_event(
        self,
        *,
        failed_turn_id: str,
        text: str,
    ) -> None:
        """Persist a diagnostic ``run_retrying`` event for overflow recovery.

        Anchored to ``failed_turn_id`` so the record lives inside the turn
        that already carries ``run_started`` and ``run_failed`` — no orphan
        turn is created.  The event is excluded from model context by the
        projector and is used only for diagnostics and session replay audit.

        Args:
            failed_turn_id (str): Turn id of the attempt that overflowed.
                The ``run_retrying`` event is appended to this same turn.
            text (str): Original user prompt text.
        """
        await self._append_history_event(
            event=self._build_event(
                kind="run_retrying",
                turn_id=failed_turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    model_name=self._resolve_active_model_name(),
                    message=f"Context overflow on turn {failed_turn_id[:8]}. Retrying after compaction.",
                    metadata={
                        "reason": "post_compaction_overflow_retry",
                        "failed_turn_id": failed_turn_id,
                        "text_preview": text[:120],
                    },
                ),
            ),
        )

    async def _emit_compaction_event(
        self,
        *,
        kind: Literal[
            "compaction_started",
            "compaction_completed",
            "compaction_failed",
            "compaction_retrying",
        ],
        content: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> None:
        """Dispatch one live compaction lifecycle event to subscribers.

        Args:
            kind (Literal[...]): Compaction event kind.
            content (Optional[str]): User-visible status text.
            metadata (Optional[dict[str, object]]): Small debug metadata bag.
        """
        await self._dispatch_event(
            event=AgentStreamEventDAO(
                kind=kind,
                content=content,
                metadata=metadata or {},
            ),
        )

    def _raise_if_attempt_failed(
        self,
        *,
        result: PromptAttemptResultDAO,
    ) -> None:
        """Re-raise the captured failure if the attempt failed.

        This is the terminal step of the orchestration loop when no retry
        plan exists. Successful and aborted attempts return silently.

        Args:
            result (PromptAttemptResultDAO): Final result for the submission.

        Returns:
            None: When the result is ``run_completed`` or ``run_aborted``.

        Raises:
            BaseException: The captured error when the result is ``run_failed``
                and an exception was recorded.
            RuntimeError: When the result is ``run_failed`` but no exception
                was recorded (defensive fallback).
        """
        if result.terminal_kind != "run_failed":
            return
        if result.error is not None:
            raise result.error
        raise RuntimeError("prompt attempt failed without a captured exception")

    async def _stream_prompt_with_retries(
        self,
        *,
        text: str,
        history: Optional[list[dict]],
        message_history: list[BaseMessage],
        runtime_handler: Optional[AgentRuntimeHandler],
        policy: ModelRateLimitPolicyDAO,
        tracker: PromptAttemptTrackerDAO,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Run the prompt with local rate governance and bounded retries.

        Args:
            text (str): User prompt text.
            history (Optional[list[dict]]): Legacy caller-supplied history.
            message_history (list[BaseMessage]): Projected persisted history.
            runtime_handler (Optional[AgentRuntimeHandler]): Optional canonical trace handler.
            policy (ModelRateLimitPolicyDAO): Active model rate policy.
            tracker (PromptAttemptTrackerDAO): Attempt tracker receiving the
                successful preflight decision.

        Yields:
            AgentStreamEventDAO: Streamed prompt events plus retry-status events.

        Raises:
            BaseException: Re-raises non-retryable failures from the provider lane.
        """
        max_attempts: int = self._max_attempts(policy=policy)
        # Layer 1 — history-aware preflight wait runs once here. Layers 2 (pool
        # switch) and 3 (iteration retry) run inside the agent/pool: this method
        # no longer wraps the whole run in a retry envelope; the agent retries
        # per iteration via the injected policy.
        async for retry_event in self._preflight_wait_events(
            text=text,
            message_history=message_history,
            policy=policy,
            attempt_number=1,
            max_attempts=max_attempts,
            tracker=tracker,
        ):
            yield retry_event

        iteration_retry_policy: IterationRetryPolicy = self._build_iteration_retry_policy(policy=policy)
        iteration_recovery_policy: IterationRecoveryPolicy = self._build_iteration_recovery_policy()
        stream_timeout_seconds: float = _stream_inactivity_timeout_seconds()
        self.agent._plugin_dispatcher = self._plugin_dispatcher
        stream = self.agent.invoke(
            query=text,
            history=history if not message_history else None,
            message_history=message_history or None,
            runtime_handler=runtime_handler,
            iteration_retry_policy=iteration_retry_policy,
            iteration_recovery_policy=iteration_recovery_policy,
        )
        try:
            while True:
                try:
                    async with asyncio.timeout(stream_timeout_seconds):
                        event = await anext(stream)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        "main agent stream produced no events for "
                        f"{stream_timeout_seconds:.0f}s; treated as hung"
                    ) from exc
                self._sync_usage_snapshot_commit()
                self._mirror_retry_cooldown(event=event)
                await self._dispatch_event(event=event)
                yield event
        finally:
            await stream.aclose()
        self._clear_retry_cooldown()

    def _build_iteration_retry_policy(
        self,
        *,
        policy: ModelRateLimitPolicyDAO,
    ) -> IterationRetryPolicy:
        """Build the per-iteration retry decision for one prompt run.

        The returned callable treats rate-limit errors and the pool's
        ``AllModelsExhaustedError`` as retryable (cooldowns are timer-based, so a
        wait can clear them) up to the attempt budget; everything else is
        non-retryable. The wait is capped at the model's local retry-wait cap.

        Args:
            policy (ModelRateLimitPolicyDAO): Active routed-model rate policy.

        Returns:
            IterationRetryPolicy: Decision callable for ``react_streaming``.
        """
        max_attempts: int = self._max_attempts(policy=policy)

        def _decide(
            exc: BaseException,
            saw_visible_output_this_iteration: bool,
            attempt_number: int,
        ) -> RateLimitRetryPlanDAO:
            if not self._is_iteration_retryable_error(exc=exc):
                return RateLimitRetryPlanDAO(retryable=False, wait_seconds=0, message=str(exc))
            # Resolve the routed model at decision time, not at policy-construction
            # time: a mid-run pool switch must name the member actually in play.
            routed_name: str = self._resolve_active_model_name() or self.active_model_name
            plan: RateLimitRetryPlanDAO = retry_plan_from_error(
                model_name=routed_name,
                exc=exc,
                attempt_number=attempt_number,
                max_attempts=max_attempts,
            )
            return RateLimitRetryPlanDAO(
                retryable=plan.retryable,
                wait_seconds=min(plan.wait_seconds, policy.local_retry_wait_cap_seconds),
                message=plan.message,
            )

        return _decide

    def _is_iteration_retryable_error(self, *, exc: BaseException) -> bool:
        """Return True for errors an iteration retry should wait-and-retry.

        ``AllModelsExhaustedError`` is retryable because its pool cooldowns are
        time-bound. For a known provider, the shared classifier permits only
        rate-limit and transient-provider classifications. Credit exhaustion,
        auth, validation, and arbitrary errors remain terminal.

        Args:
            exc (BaseException): The provider/pool exception under inspection.

        Returns:
            bool: True when a timed wait could plausibly let the iteration succeed.
        """
        if isinstance(exc, ProviderStreamFailure):
            return False
        if isinstance(exc, AllModelsExhaustedError):
            return True
        provider: Optional[ProviderName] = self._resolve_active_provider()
        if provider is None:
            return False
        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=exc,
            provider=provider,
        )
        return kind in {
            ProviderErrorKind.RATE_LIMITED,
            ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE,
            ProviderErrorKind.STREAM_DISCONNECTED,
        }

    def _mirror_retry_cooldown(self, *, event: AgentStreamEventDAO) -> None:
        """Mirror an agent-emitted ``run_retrying`` wait into the cooldown surface.

        The agent now owns iteration retries and emits ``run_retrying`` events
        during a wait; the session mirrors their ``wait_seconds`` into the usage
        status bar's cooldown display and clears it on the next non-retry event.

        Args:
            event (AgentStreamEventDAO): The relayed stream event.
        """
        if event.kind == "run_retrying":
            wait_seconds = event.metadata.get("wait_seconds") if event.metadata else None
            if isinstance(wait_seconds, int) and wait_seconds > 0:
                self._set_retry_cooldown(wait_seconds=wait_seconds)
            return
        if self._cooldown_seconds_remaining is not None:
            self._clear_retry_cooldown()

    def _max_attempts(self, *, policy: ModelRateLimitPolicyDAO) -> int:
        """Return the total provider-attempt budget for one prompt.

        Args:
            policy (ModelRateLimitPolicyDAO): Active model rate policy.

        Returns:
            int: Total attempts including the initial attempt.
        """
        return max(1, policy.automatic_retry_attempts + 1)

    async def _preflight_wait_events(
        self,
        *,
        text: str,
        message_history: Sequence[BaseMessage],
        policy: ModelRateLimitPolicyDAO,
        attempt_number: int,
        max_attempts: int,
        tracker: PromptAttemptTrackerDAO,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Yield any local rate-window waiting event before the provider call.

        Uses the history-aware estimate so a resumed session's large replayed
        history triggers a wait the prompt-only estimate would have missed.

        Args:
            text (str): User prompt text.
            message_history (Sequence[BaseMessage]): Replayed history for this turn.
            policy (ModelRateLimitPolicyDAO): Active model rate policy.
            attempt_number (int): One-indexed attempt number.
            max_attempts (int): Total attempt budget.
            tracker (PromptAttemptTrackerDAO): Attempt owner for a successful
                decision that may later need provider-failure observation.

        Yields:
            AgentStreamEventDAO: Local waiting status event when needed.
        """
        try:
            decision: PreflightDecisionDAO = self._build_preflight_decision(
                text=text,
                message_history=message_history,
                policy=policy,
            )
        except Exception as exc:
            self._handle_degraded_preflight(exc=exc)
            return
        tracker.preflight_decision = decision
        self._preflight_decisions_by_turn[tracker.turn_id] = decision
        if decision.bypass is not None:
            bypass_event: AgentStreamEventDAO = self._preflight_bypassed_event(
                bypass=decision.bypass,
            )
            await self._dispatch_event(event=bypass_event)
            yield bypass_event
        if decision.wait_seconds <= 0:
            self._clear_retry_cooldown()
            self._record_preflight_attempt(decision=decision)
            return
        self._set_retry_cooldown(wait_seconds=decision.wait_seconds)
        retry_event: AgentStreamEventDAO = self._retrying_status_event(
            message=(
                f"Waiting {decision.wait_seconds}s for {self.active_model_name} local rate window "
                f"(attempt {attempt_number}/{max_attempts})."
            ),
            wait_seconds=decision.wait_seconds,
            attempt_number=attempt_number,
        )
        await self._dispatch_event(event=retry_event)
        yield retry_event
        await asyncio.sleep(decision.wait_seconds)
        self._clear_retry_cooldown()
        self._record_preflight_attempt(decision=decision)

    def _handle_degraded_preflight(self, *, exc: Exception) -> None:
        """Clear advisory state after a local preflight construction failure.

        Args:
            exc (Exception): Local bookkeeping failure, never a provider failure.
        """
        self._clear_retry_cooldown()
        log_warning(
            msg="local_preflight_degraded",
            error_type=type(exc).__name__,
            model_name=self._resolve_active_model_name() or self.active_model_name,
        )

    def _record_preflight_attempt(self, *, decision: PreflightDecisionDAO) -> None:
        """Record one successful decision using its original token estimate.

        Args:
            decision (PreflightDecisionDAO): Completed local preflight decision.
        """
        self._record_request_attempt(
            estimated_tokens=decision.estimated_tokens,
            now_seconds=time.monotonic(),
        )

    def _build_preflight_decision(
        self,
        *,
        text: str,
        message_history: Sequence[BaseMessage],
        policy: ModelRateLimitPolicyDAO,
    ) -> PreflightDecisionDAO:
        """Build the local advisory result for one provider attempt.

        Args:
            text (str): User prompt text.
            message_history (Sequence[BaseMessage]): Replayed context for this attempt.
            policy (ModelRateLimitPolicyDAO): Active routed-model rate policy.

        Returns:
            PreflightDecisionDAO: One immutable estimate, timestamp, and bounded wait.
        """
        estimated_tokens: int = self._estimated_request_tokens(
            text=text,
            message_history=message_history,
        )
        now_seconds: float = time.monotonic()
        cooldown_wait_seconds: int = self._cooldown_wait_seconds()
        window_wait_seconds: int = self._preflight_wait_seconds(
            policy=policy,
            now_seconds=now_seconds,
        )
        bypass: PreflightBypassNoticeDAO | None = self._preflight_bypass_notice(
            policy=policy,
            estimated_tokens=estimated_tokens,
        )
        return PreflightDecisionDAO(
            estimated_tokens=estimated_tokens,
            now_seconds=now_seconds,
            wait_seconds=min(
                max(cooldown_wait_seconds, window_wait_seconds),
                policy.local_retry_wait_cap_seconds,
            ),
            bypass=bypass,
        )

    def _preflight_bypass_notice(
        self,
        *,
        policy: ModelRateLimitPolicyDAO,
        estimated_tokens: int,
    ) -> PreflightBypassNoticeDAO | None:
        """Return an audit notice when local TPM waiting cannot help.

        Args:
            policy (ModelRateLimitPolicyDAO): Active model rate policy.
            estimated_tokens (int): One decision-owned request estimate.

        Returns:
            PreflightBypassNoticeDAO | None: Bypass fact for an empty oversized
                token window, otherwise ``None``.
        """
        if policy.tokens_per_minute is None:
            return None
        if self._recent_request_token_estimates:
            return None
        if estimated_tokens <= policy.tokens_per_minute:
            return None
        return PreflightBypassNoticeDAO(
            reason="empty_token_window_oversized_request",
            estimated_tokens=estimated_tokens,
            tokens_per_minute=policy.tokens_per_minute,
        )

    @staticmethod
    def _preflight_bypassed_event(
        *,
        bypass: PreflightBypassNoticeDAO,
    ) -> AgentStreamEventDAO:
        """Build the fixed audit event for one local TPM bypass.

        Args:
            bypass (PreflightBypassNoticeDAO): Decision-owned bypass details.

        Returns:
            AgentStreamEventDAO: Audit event that leaves the provider lane open.
        """
        return AgentStreamEventDAO(
            kind="preflight_bypassed",
            content=(
                "Local token preflight could not provide a useful wait; "
                "sending the request to the provider."
            ),
            metadata={
                "reason": bypass.reason,
                "estimated_tokens": bypass.estimated_tokens,
                "tokens_per_minute": bypass.tokens_per_minute,
            },
        )

    @staticmethod
    def _retrying_status_event(
        *,
        message: str,
        wait_seconds: int,
        attempt_number: int,
    ) -> AgentStreamEventDAO:
        """Build one transient retry-status event.

        Args:
            message (str): Operator-facing status message.
            wait_seconds (int): Seconds until the next attempt.
            attempt_number (int): Current one-indexed attempt number.

        Returns:
            AgentStreamEventDAO: Transient retrying status event.
        """
        return AgentStreamEventDAO(
            kind="run_retrying",
            content=message,
            metadata={
                "wait_seconds": wait_seconds,
                "attempt": attempt_number,
            },
        )

    # ---- Agent readiness + history orchestration helpers ------------------

    async def _prepare_run_snapshot(self) -> None:
        """Validate configured OpenRouter routes once under the submission lock.

        Invoke calls this before history or agent setup. Every retry shares the
        returned generation; failure leaves selection and the previous agent intact.
        Injected agents and direct-only sessions retain their existing behavior.

        Raises:
            ModelPreparationRequiredError: A configured OpenRouter route is unavailable.
            ValueError: Another configured pool member is invalid.
        """
        if self._config is None or self._agent_is_injected:
            return
        model_names = self._configured_model_names(config=self._config)
        if not any(name.startswith("openrouter:") for name in model_names):
            return
        credential = CredentialResolver.resolve(provider=ProviderName.OPENROUTER)
        snapshot = await ModelCatalogService.prepare_models(model_names=model_names)
        current = CredentialResolver.resolve(provider=ProviderName.OPENROUTER)
        if credential is None or current is None or credential.access_token != current.access_token:
            raise ModelPreparationRequiredError("OpenRouter credential changed; run /auth.")
        self._adopt_prepared_snapshot(snapshot=snapshot, model_names=model_names)
        self._admitted_openrouter_credential = credential
        if self._agent_openrouter_fingerprint != credential_fingerprint(access_token=credential.access_token):
            self._agent = None

    def _adopt_prepared_snapshot(
        self, *, snapshot: ModelCatalogSnapshotDAO, model_names: tuple[str, ...]
    ) -> None:
        """Pin validated metadata and invalidate a stale lazy agent before this run.

        Args:
            snapshot: Generation returned by the catalog admission gateway.
            model_names: Complete configured route set, never a filtered pool.
        """
        previous = self._agent_catalog_snapshot
        changed = previous is None or any(
            previous.entries.get(name) != snapshot.entries.get(name) for name in model_names
        )
        reasoning_level = clamp_reasoning_level(
            model_name=self.active_model_name,
            requested_level=self.active_reasoning_level,
            snapshot=snapshot,
        )
        self._catalog_snapshot = snapshot
        self._withdraw_stale_herdr_capture()
        self._admitted_run_snapshot = snapshot
        self._active_reasoning_level = reasoning_level
        self._adopt_herdr_capture(capture=self._capture_herdr_restore(), reasoning_commit=True)
        if changed:
            self._agent = None
            self._context_window_dirty = True
            self._context_window_snapshot = None
        self._rebuild_usage_snapshot()

    def _admit_run_snapshot(self) -> None:
        """Freeze this submission's prepared generation before lazy agent construction.

        WHAT: Copies the session-prepared snapshot to the admitted-run slot so
            later global publication cannot affect the current prompt.
        WHO: ``_prepare_attempt_context`` calls this inside the prompt lock.
        WHEN: Once at initial-attempt admission, before any factory invocation.

        Raises:
            ModelPreparationRequiredError: A direct OpenRouter route has no
                prepared catalog generation.
        """
        if self._admitted_run_snapshot is not None:
            return
        if self._config is not None:
            self._require_prepared_openrouter_route(
                config=self._config,
                snapshot=self._catalog_snapshot,
            )
        self._admitted_run_snapshot = self._catalog_snapshot

    def _validate_configured_backend_eligibility(self) -> None:
        """Reject incompatible OpenAI lanes before lazy readiness refreshes OAuth.

        Readiness checks the session view once per build; the factory separately
        checks its actual credential afterward. No credential is retained here.

        Raises:
            ValueError: Missing OpenAI auth or a configured record rejects its type.
        """
        if self._config is None:
            return
        names = tuple(
            name
            for name in self._configured_model_names(config=self._config)
            if provider_for_model(model_name=name) is ProviderName.OPENAI
        )
        if not names:
            return
        credential = self._require_reporting_credential(provider=ProviderName.OPENAI)
        snapshot = self.catalog_snapshot
        for name in names:
            ModelCatalogService.entry_for_model(
                model_name=name, snapshot=snapshot
            ).require_backend_eligibility(auth_type=credential.auth_type)

    async def _ensure_agent_ready(self) -> None:
        """Refresh OAuth creds if needed, then lazy-build the agent.

        ``invoke`` is already inside the session lock when it calls this
        helper, so the refresh and the lazy build are both
        single-flight for the session. Pre-built agents and already-
        built lazy agents short-circuit immediately.

        Returns:
            None: The method refreshes credentials when needed and
                ensures ``self._agent`` exists before returning.
        """
        if self._agent is not None:
            return
        self._validate_configured_backend_eligibility()
        await self._refresh_oauth_credential_if_needed()
        with CredentialResolver.bind_build_credential(credential=self._admitted_openrouter_credential):
            self._agent = self._build_agent()
        self._agent_catalog_snapshot = self.catalog_snapshot
        credential = self._admitted_openrouter_credential
        self._agent_openrouter_fingerprint = (
            credential_fingerprint(access_token=credential.access_token) if credential is not None else None
        )

    def _pool_providers(self) -> list[ProviderName]:
        """Return the distinct providers the session must keep credential-ready.

        Every provider in the configured pool when one exists; otherwise the
        single active model's provider. Used by credential refresh so a fallback
        member never hits a stale OAuth token.

        Returns:
            list[ProviderName]: Distinct providers to refresh, in priority order.
        """
        if self._config is not None and self._config.model_pool_dao is not None:
            seen: dict[ProviderName, None] = {}
            for entry in self._config.model_pool_dao.entries:
                seen.setdefault(entry.provider, None)
            return list(seen.keys())
        return [provider_for_model(model_name=self.active_model_name)]

    async def _refresh_oauth_credential_if_needed(self) -> None:
        """Refresh persisted OAuth credentials for every provider this session may use.

        The refresh runs only for lazy-config sessions. For a pooled session it
        warms each distinct pool provider so a fallback member's token is not
        stale; for a single-model session it warms the one provider.
        Pre-built-agent sessions bypass the helper. Any ``ValueError`` raised by
        ``CredentialResolver.require`` bubbles unchanged so the TUI can render
        the existing configuration error line.

        Returns:
            None: The method persists each refreshed credential when a refresh
                occurs and otherwise no-ops.
        """
        if self._config is None:
            return
        store: CredentialStore = CredentialStore()
        for provider in self._pool_providers():
            cred = self._require_reporting_credential(provider=provider)
            await refresh_if_stale(cred=cred, store=store)

    def _require_reporting_credential(self, *, provider: ProviderName) -> CredentialDAO:
        """Observe the existing auth requirement without adding credential lookups."""
        try:
            return CredentialResolver.require(provider=provider)
        except ValueError:
            self.set_operator_attention(reason="Authentication required")
            raise

    # ---- History orchestration helpers -----------------------------------

    async def _persist_run_retrying_event(
        self,
        *,
        event: AgentStreamEventDAO,
        turn_id: str,
    ) -> None:
        """Persist one ``run_retrying`` wait-and-retry decision to history.

        Makes "retried and still failed" distinguishable from "no retry
        attempted" when diagnosing a session from ``events.jsonl`` alone (37.a.6).

        Args:
            event (AgentStreamEventDAO): The relayed ``run_retrying`` stream event.
            turn_id (str): The owning turn id.
        """
        await self._append_history_event(
            event=self._build_event(
                kind="run_retrying",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    model_name=self._resolve_active_model_name(),
                    message=event.content,
                    metadata=dict(event.metadata or {}),
                ),
            ),
        )

    async def _persist_preflight_bypassed_event(
        self,
        *,
        event: AgentStreamEventDAO,
        turn_id: str,
    ) -> None:
        """Persist one decision-owned local TPM bypass audit event.

        Args:
            event (AgentStreamEventDAO): The bypass audit event.
            turn_id (str): Active history turn receiving the audit.
        """
        await self._append_history_event(
            event=self._build_event(
                kind="preflight_bypassed",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    model_name=self._resolve_active_model_name(),
                    message=event.content,
                    metadata=dict(event.metadata),
                ),
            ),
        )

    def _resolve_active_provider(self) -> Optional[ProviderName]:
        """Return the provider for the routed pool member or configured single model.

        A ModelPool exposes the selected member through ``active_provider``.
        A single LangChain model does not, so this method resolves the active
        model name through ``provider_for_model`` instead. Both the iteration
        retry and recovery policies call this method at decision time.

        Returns:
            Optional[ProviderName]: The current provider, or ``None`` when the
                configured model identifier is not recognized.
        """
        pooled_provider: Optional[ProviderName] = self._pooled_active_provider()
        if pooled_provider is not None:
            return pooled_provider
        return self._provider_for_active_model()

    def _pooled_active_provider(self) -> Optional[ProviderName]:
        """Return a ModelPool's current provider when the bound LLM exposes one.

        Returns:
            Optional[ProviderName]: The routed pool provider, or ``None`` for a
                single-model session.
        """
        if self._agent is None:
            return None
        active_provider: object = getattr(self._agent.llm, "active_provider", None)
        return active_provider if isinstance(active_provider, ProviderName) else None

    def _provider_for_active_model(self) -> Optional[ProviderName]:
        """Resolve the configured active model name to its provider when possible.

        Returns:
            Optional[ProviderName]: The provider mapped from the active model, or
                ``None`` when the model name is unsupported.
        """
        model_name: str = self._resolve_active_model_name()
        if not model_name:
            return None
        try:
            return provider_for_model(model_name=model_name)
        except ValueError:
            return None

    def _build_iteration_recovery_policy(self) -> IterationRecoveryPolicy:
        """Build the per-iteration LLM-recovery decision for one prompt run.

        The returned callable classifies an escaped iteration exception via
        ``RecoveryPolicy.classify`` against the active provider. Injected into
        ``self.agent.invoke`` alongside the retry policy.

        Returns:
            IterationRecoveryPolicy: Decision callable for the agent loop.
        """

        def _decide(
            exc: BaseException,
            recoveries_used: int,
        ) -> RecoveryDecisionDAO:
            """Classify ``exc`` for LLM recovery against the current provider."""
            return RecoveryPolicy.classify(
                exc=exc,
                provider=self._resolve_active_provider(),
            )

        return _decide

    async def _persist_recovery_events(
        self,
        *,
        event: AgentStreamEventDAO,
        turn_id: str,
    ) -> None:
        """Persist the audit + observation history events for one recovery.

        Writes a ``run_recovering`` audit event (excluded from model context by
        the projector) and a ``recovery_observation`` event (re-projected as a
        ``HumanMessage`` on replay). Invoked from the attempt stream loop when
        the agent yields ``recovery_started``.

        Args:
            event (AgentStreamEventDAO): The relayed ``recovery_started`` event.
                ``content`` is the observation text; ``metadata`` carries
                ``reason`` / ``error`` / ``recovery_class``.
            turn_id (str): The owning turn id (the attempt that failed).
        """
        await self._append_history_event(
            event=self._build_event(
                kind="run_recovering",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    model_name=self._resolve_active_model_name(),
                    message=str(event.metadata.get("reason", "")),
                    metadata=dict(event.metadata or {}),
                ),
            ),
        )
        await self._append_history_event(
            event=self._build_event(
                kind="recovery_observation",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    content=event.content,
                ),
            ),
        )

    async def _drain_and_persist_route_switches(self, *, turn_id: str) -> None:
        """Persist one ``route_switched`` history event per pool switch this turn.

        Duck-types the agent's bound LLM for ``drain_route_switch_log`` (present
        only on a ``ModelPool``); single-model sessions no-op. Called after the
        run so the audit trail records which member took over and why (37.a.6).

        Args:
            turn_id (str): The owning turn id.
        """
        if not self._enable_history or self._agent is None:
            return
        drain = getattr(self._agent.llm, "drain_route_switch_log", None)
        if drain is None:
            return
        for record in drain():
            await self._append_history_event(
                event=self._build_event(
                    kind="route_switched",
                    turn_id=turn_id,
                    payload=SessionHistoryEventPayloadDAO(
                        model_name=record.to_model_name,
                        error_message=record.safe_error_code,
                        metadata={
                            "from_model": record.from_model_name,
                            "to_model": record.to_model_name,
                            "kind": record.kind,
                        },
                    ),
                ),
            )
            await self._persist_pool_provider_limit_observation(
                turn_id=turn_id,
                record=record,
            )

    async def _persist_pool_provider_limit_observation(
        self,
        *,
        turn_id: str,
        record: RouteSwitchRecordDAO,
    ) -> None:
        """Persist one pool-caught provider observation without reclassification.

        Args:
            turn_id (str): Owning attempt turn identifier.
            record (RouteSwitchRecordDAO): Typed ModelPool route-switch audit record.
        """
        signal: ProviderErrorSignalDAO = record.signal
        provider: ProviderName = record.provider
        model_name: str = record.from_model_name
        if signal.kind not in {
            ProviderErrorKind.RATE_LIMITED,
            ProviderErrorKind.CONTEXT_OVERFLOW,
            ProviderErrorKind.REQUEST_BODY_TOO_LARGE,
        }:
            return
        decision: PreflightDecisionDAO | None = self._active_preflight_decision_for_turn(
            turn_id=turn_id,
        )
        if decision is None:
            return
        observation = self._build_provider_limit_observation(
            provider=provider,
            model_name=model_name,
            signal=signal,
            decision=decision,
        )
        await self._append_history_event(
            event=self._build_event(
                kind="provider_limit_observed",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    message="Provider rejected a request; recorded a redacted limit observation.",
                    metadata={"observation": observation.model_dump(mode="json")},
                ),
            ),
        )

    def _active_preflight_decision_for_turn(self, *, turn_id: str) -> PreflightDecisionDAO | None:
        """Return the exact decision retained by the currently executing turn.

        Args:
            turn_id (str): Turn whose provider lane was rejected.

        Returns:
            PreflightDecisionDAO | None: The decision for the active turn, or
                ``None`` when the lane bypassed degraded local preflight.
        """
        return self._preflight_decisions_by_turn.get(turn_id)

    def _build_provider_limit_observation(
        self,
        *,
        provider: ProviderName,
        model_name: str,
        signal: ProviderErrorSignalDAO,
        decision: PreflightDecisionDAO,
    ) -> ProviderLimitObservationDAO:
        """Build one observation from the exact decision that opened its lane.

        Args:
            provider (ProviderName): Provider that rejected the request.
            model_name (str): Failed routed model name.
            signal (ProviderErrorSignalDAO): Shared provider classification.
            decision (PreflightDecisionDAO): Original successful preflight.

        Returns:
            ProviderLimitObservationDAO: Redacted rejection audit facts.
        """
        rolling_token_estimate: int = sum(tokens for _, tokens in self._recent_request_token_estimates)
        return ProviderLimitObservationDAO(
            provider=provider,
            model_name=model_name,
            signal=signal,
            estimated_request_tokens=decision.estimated_tokens,
            rolling_request_count=len(self._recent_request_times),
            rolling_token_estimate=rolling_token_estimate,
        )

    async def _persist_routed_model_if_changed(self) -> None:
        """Update ``session.json``'s model_name to the routed model when it changed.

        Called after a turn completes. Ends the stale-identity drift where session
        metadata reports the configured model while the pool routed elsewhere.
        No-ops when history is disabled, the routed name is empty, or it already
        matches the persisted value.
        """
        if not self._enable_history or self._history_store is None:
            return
        routed: str = self._resolve_active_model_name()
        if not routed:
            return
        try:
            metadata: SessionHistoryMetadataDAO = await self._history_store.read_metadata(
                session_id=self._session_id,
            )
        except FileNotFoundError:
            return
        if metadata.model_name == routed:
            return
        await self._history_store.update_metadata_model_name(
            session_id=self._session_id,
            model_name=routed,
        )
        # The pool internally switched to a different model. The new model may
        # have a smaller context window than the one the session was configured
        # with, so the preflight compaction check must re-evaluate on the next
        # turn. Setting the dirty flag here ensures _preflight_compaction_if_dirty
        # runs and calls _run_compaction_if_needed with the correct window size.
        self._context_window_dirty = True

    async def _ensure_history_session(self) -> None:
        """Create or validate the persisted session metadata.

        Called once per submitted prompt. No-ops when history is
        disabled. Cached after the first successful call so we do not
        re-touch ``session.json`` on every turn.
        """
        if not self._enable_history or self._history_store is None:
            return
        if self._history_session_ensured:
            return
        await self._history_store.ensure_session(
            session_id=self._session_id,
            workdir=self._workdir,
            model_name=self.active_model_name,
            workspace_file=(self._config.workspace_file if self._config is not None else None),
        )
        self._history_session_ensured = True
        self._adopt_herdr_capture(capture=self._capture_herdr_restore())
        self._publish_herdr_snapshot()

    async def _load_message_history(
        self,
        *,
        excluded_turn_ids: Optional[set[str]] = None,
    ) -> list[BaseMessage]:
        """Load projected ``BaseMessage`` history for the next agent turn.

        Args:
            excluded_turn_ids (Optional[set[str]]): Completed turns omitted from
                this one history build. Defaults to None.

        Returns:
            list[BaseMessage]: Empty when history is disabled or the
                session has no completed turns yet.
        """
        if not self._enable_history or self._history_store is None:
            return []
        events: list[SessionHistoryEventDAO] = await self._history_store.load_events(
            session_id=self._session_id,
        )
        return await self._history_projector.build_message_history(
            events=events,
            excluded_turn_ids=excluded_turn_ids or set(),
        )

    async def _preflight_compaction_if_dirty(self, *, turn_id: str) -> None:
        """Run a one-shot compaction check when the context window may have shrunk.

        The post-turn check (``_run_compaction_if_needed`` after a completed
        turn) guarantees the session stays within budget for the model it last
        ran on, so a steady-state turn needs no pre-flight check. That invariant
        only breaks when the effective window changes underneath it — a model
        switch to a smaller window, or a freshly built / resumed session whose
        history has not been validated for the active model. ``_context_window_dirty``
        marks exactly those cases.

        The flag is cleared before the check runs, so a transient compaction
        failure can never turn this into a per-turn retry loop; the existing
        post-turn and on-overflow-failure paths remain as backstops. Compaction
        failures are logged and swallowed so a best-effort pre-flight never fails
        the turn outright.

        Args:
            turn_id (str): The turn id to anchor any written
                ``compaction_summary`` event to.
        """
        if not self._context_window_dirty:
            return
        self._context_window_dirty = False
        try:
            await self._run_compaction_if_needed(turn_id=turn_id)
        except Exception as exc:  # noqa: BLE001
            log_error(
                msg="preflight_compaction_failed",
                session_id=self._session_id[:8],
                error=str(exc),
            )

    async def _run_compaction_if_needed(
        self,
        *,
        turn_id: str,
        force: bool = False,
        events: Optional[list[SessionHistoryEventDAO]] = None,
    ) -> bool:
        """Check context size and compact session history when needed.

        Loads all current session events from the store, asks ``CompactionChecker``
        whether the cumulative token total exceeds the model's compaction threshold,
        and — when it does — runs ``Compacter`` to generate a summary then
        ``CompactedSessionUpdater`` to persist the ``compaction_summary`` event.

        When ``force=True``, the threshold check is bypassed and the compaction
        pipeline runs immediately. This is used after a provider has already
        rejected the request for context overflow: provider truth wins over the
        local chars/4 estimator.

        The next call to ``_load_message_history()`` will automatically pick up
        the ``compaction_summary`` event. ``SessionHistoryProjector`` (sub-spec
        01.a.5) skips pre-cut events and emits the summary as a ``HumanMessage``
        so the agent receives a clean context on the following turn.

        No-ops when history is disabled or when the store/agent is absent. With
        ``force=False`` (the default), also no-ops when
        ``CompactionChecker.should_compact()`` returns ``False``.

        Args:
            turn_id (str): The turn id that triggered the compaction check.
                Forwarded to ``CompactedSessionUpdater.update()`` so the written
                ``compaction_summary`` event is auditably anchored to the
                originating turn.
            force (bool, optional): When ``True``, bypass the threshold check
                and compact immediately. Defaults to ``False``.
        """
        if not self._enable_history or self._history_store is None:
            return False
        if self._agent is None or self._agent.llm is None:
            return False

        compaction_events: list[SessionHistoryEventDAO]
        if events is not None:
            compaction_events = events
        else:
            compaction_events = await self._history_store.load_events(session_id=self._session_id)
        model_name: str = self._resolve_active_model_name()

        if not force:
            should_compact: bool = await CompactionChecker.should_compact(
                events=compaction_events,
                model_name=model_name,
                snapshot=self.catalog_snapshot,
            )
            if not should_compact:
                return False

        log_info(
            msg="compaction_triggered",
            session_id=self._session_id[:8],
            event_count=len(compaction_events),
            model_name=model_name,
            force=force,
        )

        result = await Compacter.compact(
            events=compaction_events,
            model_name=model_name,
            llm=self._agent.llm,
            snapshot=self.catalog_snapshot,
        )
        await self._history_store.compact_to_boundary(
            session_id=self._session_id,
            events=compaction_events,
            result=result,
            turn_id=turn_id,
        )

        log_info(
            msg="compaction_completed",
            session_id=self._session_id[:8],
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
        )
        return True

    def _inspect_provider_error(self, *, error: BaseException) -> ProviderErrorSignalDAO | None:
        """Inspect an escaped provider error once when its provider is known.

        Args:
            error (BaseException): Escaped provider exception.

        Returns:
            ProviderErrorSignalDAO | None: Typed signal, or ``None`` for a
                local/non-provider error.
        """
        provider: ProviderName | None = self._resolve_active_provider()
        if provider is None:
            return None
        return ProviderErrorClassifier.inspect(error=error, provider=provider)

    async def _persist_provider_limit_observation(
        self,
        *,
        turn_id: str,
        signal: ProviderErrorSignalDAO,
        decision: PreflightDecisionDAO,
    ) -> None:
        """Persist one redacted provider rejection audit for the active lane.

        Args:
            turn_id (str): Failed attempt turn identifier.
            signal (ProviderErrorSignalDAO): Shared classifier output.
            decision (PreflightDecisionDAO): Exact successful preflight result
                that opened the rejected provider lane.
        """
        if signal.kind not in {
            ProviderErrorKind.RATE_LIMITED,
            ProviderErrorKind.CONTEXT_OVERFLOW,
            ProviderErrorKind.REQUEST_BODY_TOO_LARGE,
        }:
            return
        provider: ProviderName | None = self._resolve_active_provider()
        if provider is None:
            return
        observation = self._build_provider_limit_observation(
            provider=provider,
            model_name=self._resolve_active_model_name(),
            signal=signal,
            decision=decision,
        )
        await self._append_history_event(
            event=self._build_event(
                kind="provider_limit_observed",
                turn_id=turn_id,
                payload=SessionHistoryEventPayloadDAO(
                    message="Provider rejected a request; recorded a redacted limit observation.",
                    metadata={"observation": observation.model_dump(mode="json")},
                ),
            ),
        )

    async def _append_history_event(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> None:
        """Persist one canonical history event.

        Raises on failure so the session can enforce consistency. UI
        renderer subscribers are intentionally not invoked here.
        """
        if not self._enable_history or self._history_store is None:
            return
        await self._history_store.append_event(event=event)

    def _runtime_handler_for_turn(self, *, turn_id: str) -> AgentRuntimeHandler:
        """Build the trace handler that maps runtime events → persisted events.

        Args:
            turn_id (str): The turn id allocated for this prompt.

        Returns:
            AgentRuntimeHandler: Async callback the agent invokes per
                runtime trace event.
        """

        async def _handler(event: AgentRuntimeEventDAO) -> None:
            """Append one runtime trace event to canonical history.

            Args:
                event (AgentRuntimeEventDAO): Runtime trace event.
            """
            if event.kind in ("run_started", "run_completed", "run_aborted", "run_failed"):
                return

            if event.kind == "assistant_delta":
                await self._append_history_event(
                    event=self._build_event(
                        kind="assistant_delta",
                        turn_id=turn_id,
                        iteration=event.iteration,
                        payload=SessionHistoryEventPayloadDAO(
                            delta_kind=event.payload.delta_kind,
                            block_id=event.payload.block_id,
                            delta=event.payload.delta,
                            content=event.payload.content,
                            redacted=event.payload.redacted,
                            tool_arguments_delta=event.payload.tool_arguments_delta,
                            metadata=dict(event.payload.metadata),
                        ),
                    ),
                )
                return

            await self._append_history_event(
                event=self._build_event(
                    kind=event.kind,
                    turn_id=turn_id,
                    iteration=event.iteration,
                    payload=SessionHistoryEventPayloadDAO(
                        content=event.payload.content,
                        tool_name=event.payload.tool_name,
                        tool_call_id=event.payload.tool_call_id,
                        tool_calls=event.payload.tool_calls,
                        tool_input=event.payload.tool_input,
                        tool_output=event.payload.tool_output,
                        error_message=event.payload.error_message,
                        provider_message_extension=event.payload.provider_message_extension,
                        metadata=dict(event.payload.metadata or {}),
                    ),
                ),
            )

        return _handler

    def _build_event(
        self,
        *,
        kind: str,
        turn_id: Optional[str],
        payload: Optional[SessionHistoryEventPayloadDAO] = None,
        iteration: int = 0,
    ) -> SessionHistoryEventDAO:
        """Construct a canonical history event for this session.

        Args:
            kind (str): The event kind discriminator.
            turn_id (Optional[str]): The owning turn id.
            payload (Optional[SessionHistoryEventPayloadDAO]): Payload to
                attach. Defaults to an empty payload.
            iteration (int): ReAct iteration counter.

        Returns:
            SessionHistoryEventDAO: A canonical event ready to append.
        """
        return SessionHistoryEventDAO(
            session_id=self._session_id,
            turn_id=turn_id,
            kind=kind,  # type: ignore[arg-type]
            iteration=iteration,
            payload=payload or SessionHistoryEventPayloadDAO(),
        )

    # ---- Private helpers --------------------------------------------------

    async def _on_stream_event_for_history(self, event: AgentStreamEventDAO) -> None:
        """Persist sub-agent lifecycle events to the orchestrator's history.

        Internal subscriber registered at session construction when history is
        enabled. Invoked on every dispatched event; only sub-agent lifecycle
        kinds write history entries — all other events pass through without
        writing.

        ``sub_agent_spawned`` writes a ``sub_agent_spawned`` history event
        carrying the child's ``session_id`` and ``task_id`` in
        ``payload.metadata``.

        ``sub_agent_completed``, ``sub_agent_failed``, and ``sub_agent_aborted``
        all write a ``sub_agent_completed`` history event so the on-disk trace
        records the terminal kind for future forensics.

        Both audit records also copy the pool's dispatch identity
        (``dispatch_id``, ``dispatch_sequence``, ``execution_id``) when the event
        carries it (feature 94 a.2). ``sub_agent_dispatch_started`` has no
        ``sub_agent_id`` and stays stream-only; no history kind is added.

        Args:
            event (AgentStreamEventDAO): Event to inspect and optionally persist.
        """
        if event.sub_agent_id is None:
            return
        if event.kind == "sub_agent_spawned":
            await self._append_history_event(
                event=self._build_event(
                    kind="sub_agent_spawned",
                    turn_id=None,
                    payload=SessionHistoryEventPayloadDAO(
                        metadata={
                            "sub_agent_id": event.sub_agent_id,
                            "task_id": event.task_id,
                            **self._dispatch_audit_identity(event=event),
                        }
                    ),
                ),
            )
        elif event.kind in ("sub_agent_completed", "sub_agent_failed", "sub_agent_aborted"):
            await self._append_history_event(
                event=self._build_event(
                    kind="sub_agent_completed",
                    turn_id=None,
                    payload=SessionHistoryEventPayloadDAO(
                        metadata={
                            "sub_agent_id": event.sub_agent_id,
                            "task_id": event.task_id,
                            "terminal_kind": event.kind,
                            **self._dispatch_audit_identity(event=event),
                        }
                    ),
                ),
            )

    async def _on_herdr_event(self, event: AgentStreamEventDAO) -> None:
        """Observe parent route boundaries without interpreting content or adding usage."""
        if event.is_sub_agent_event or event.kind.startswith("sub_agent_"):
            return
        if event.kind.endswith("_delta") or event.kind == "tool_output_update":
            return
        try:
            if self.routed_model_name != self._usage_snapshot.active_model_name:
                self._rebuild_usage_snapshot()
        except Exception:
            self._log_herdr_publication_failure()

    @staticmethod
    def _dispatch_audit_identity(*, event: AgentStreamEventDAO) -> dict[str, object]:
        """Return the dispatch identity keys a pool lifecycle event carries.

        Args:
            event (AgentStreamEventDAO): Child lifecycle event from the pool relay.

        Returns:
            dict[str, object]: ``dispatch_id``, ``dispatch_sequence`` and
                ``execution_id`` present in the event metadata; empty for
                events emitted without dispatch identity.
        """
        return {key: event.metadata[key] for key in _DISPATCH_AUDIT_KEYS if key in event.metadata}

    async def _dispatch_event(self, *, event: AgentStreamEventDAO) -> None:
        """Forward ``event`` to every registered subscriber (failure-isolated)."""
        if self._plugin_dispatcher is not None:
            await self._plugin_dispatcher.emit(event)
        for subscriber in list(self._subscribers):
            try:
                await subscriber(event)
            except Exception as exc:  # noqa: BLE001 — protect the stream
                log_error(
                    msg=f"SloAgentSession: subscriber {subscriber!r} raised",
                    e=exc,
                    stack_trace=False,
                )
